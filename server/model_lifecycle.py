"""Persist last model load/unload timestamps for settings UI."""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger("server.model_lifecycle")

_PATH = config.PROJECT_ROOT / "data" / "model_lifecycle.json"
_LOG_PATH = config.PROJECT_ROOT / "logs" / "server.log"
_LOG_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*正在卸载 SenseVoice 模型"
)
_lock = threading.Lock()


def _ensure_data_dir() -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)


def _read() -> dict[str, Any]:
    _ensure_data_dir()
    if not _PATH.is_file():
        return {}
    try:
        with _PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        logger.warning("读取 model_lifecycle.json 失败，将使用空状态")
        return {}


def _write(data: dict[str, Any]) -> None:
    _ensure_data_dir()
    with _PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _local_log_time_to_iso(ts: str) -> str:
    naive = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    local = naive.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return local.astimezone(timezone.utc).isoformat()


def _unload_from_log() -> str | None:
    if not _LOG_PATH.is_file():
        return None
    last_ts: str | None = None
    try:
        # Only scan recent lines; full server.log can be large.
        with _LOG_PATH.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 256_000))
            if size > 256_000:
                f.readline()
            text = f.read().decode("utf-8", errors="replace")
        for line in text.splitlines():
            match = _LOG_TS_RE.match(line)
            if match:
                last_ts = match.group(1)
    except OSError:
        logger.warning("读取 server.log 失败，跳过卸载时间回填")
        return None
    if not last_ts:
        return None
    return _local_log_time_to_iso(last_ts)


def _persist_unload(at: datetime, source: str) -> None:
    iso = at.isoformat()
    with _lock:
        data = _read()
        data["last_unloaded_at"] = iso
        data["last_unload_source"] = source
        _write(data)
    from server import progress_db

    progress_db.record_model_unload(source=source, recorded_at=iso)


def record_loaded() -> None:
    with _lock:
        data = _read()
        data["last_loaded_at"] = datetime.now(timezone.utc).isoformat()
        _write(data)


def record_unloaded(*, source: str = "unload") -> None:
    _persist_unload(datetime.now(timezone.utc), source)


def reconcile_on_startup() -> None:
    """Infer unload time when the process restarted while model was still in memory."""
    from server import model_manager, progress_db
    from server.runtime import uptime_seconds

    if model_manager.is_model_loaded():
        return

    last_loaded = _read().get("last_loaded_at") or progress_db.last_model_load_at()
    if not last_loaded:
        return

    last_unloaded = _best_unload_time(persist_backfill=False)
    loaded_dt = _parse_iso(last_loaded)
    if last_unloaded:
        unloaded_dt = _parse_iso(last_unloaded)
        if unloaded_dt >= loaded_dt:
            return

    started_at = datetime.now(timezone.utc) - timedelta(seconds=uptime_seconds())
    if started_at < loaded_dt:
        started_at = datetime.now(timezone.utc)
    _persist_unload(started_at, "process_restart")
    logger.info("推断模型于服务启动时不在显存（进程重启） unload_at=%s", started_at.isoformat())


def _best_unload_time(*, persist_backfill: bool) -> str | None:
    with _lock:
        data = _read()
    last_unloaded = data.get("last_unloaded_at")
    if last_unloaded:
        return last_unloaded

    from server import progress_db

    last_unloaded = progress_db.last_model_unload_at()
    if last_unloaded:
        if persist_backfill:
            with _lock:
                data = _read()
                data["last_unloaded_at"] = last_unloaded
                _write(data)
        return last_unloaded

    log_unload = _unload_from_log()
    if log_unload and persist_backfill:
        with _lock:
            data = _read()
            data["last_unloaded_at"] = log_unload
            data["last_unload_source"] = "log_backfill"
            _write(data)
        from server import progress_db

        progress_db.record_model_unload(source="log_backfill", recorded_at=log_unload)
    return log_unload


def lifecycle_fields() -> dict[str, str | None]:
    with _lock:
        data = _read()
    last_loaded = data.get("last_loaded_at")
    if not last_loaded:
        from server import progress_db

        last_loaded = progress_db.last_model_load_at()
    last_unloaded = _best_unload_time(persist_backfill=True)
    return {
        "model_last_loaded_at": last_loaded,
        "model_last_unloaded_at": last_unloaded,
    }
