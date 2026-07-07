"""In-memory snapshot for instant first page load after boot warmup."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("server.bootstrap")

_lock = threading.Lock()
_ready = False
_snapshot: dict[str, Any] | None = None


def _build_snapshot() -> dict[str, Any]:
    from server.history_service import history_service
    from server.queue_service import queue_service
    from server.secrets import get_secrets_mask
    from server.settings_store import load_settings

    return {
        "settings": load_settings().model_dump(),
        "secrets": get_secrets_mask(),
        "queue": [t.to_dict() for t in queue_service.list()],
        "history": history_service.list(page=1, page_size=20),
    }


def warm() -> None:
    """Load queue, history, settings into memory (call after PyTorch warmup)."""
    global _snapshot, _ready
    t0 = __import__("time").monotonic()
    snap = _build_snapshot()
    with _lock:
        _snapshot = snap
        _ready = True
    elapsed_ms = (__import__("time").monotonic() - t0) * 1000
    logger.info(
        "Bootstrap 缓存就绪 queue=%d history=%d/%d (%.0fms)",
        len(snap["queue"]),
        len(snap["history"].get("items", [])),
        snap["history"].get("total", 0),
        elapsed_ms,
    )


def refresh() -> None:
    """Rebuild snapshot after queue/history/settings change."""
    global _snapshot
    if not _ready:
        return
    try:
        snap = _build_snapshot()
        with _lock:
            _snapshot = snap
    except Exception:
        logger.exception("刷新 Bootstrap 缓存失败")


def refresh_async() -> None:
    if not _ready:
        return
    threading.Thread(target=refresh, name="bootstrap-refresh", daemon=True).start()


def is_ready() -> bool:
    return _ready


def get_bootstrap() -> dict[str, Any]:
    from server.status_builder import build_status_payload

    with _lock:
        if not _ready or _snapshot is None:
            warm()
        snap = dict(_snapshot)
    snap["status"] = build_status_payload()
    return snap
