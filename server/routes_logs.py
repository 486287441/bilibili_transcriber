"""Read-only access to files under logs/."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

import config

router = APIRouter(prefix="/api/logs", tags=["logs"])

_LOGS_DIR = config.PROJECT_ROOT / "logs"
_MAX_TAIL_LINES = 2000
_DEFAULT_TAIL_LINES = 500


def _logs_dir() -> Path:
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return _LOGS_DIR.resolve()


def _safe_log_path(name: str) -> Path:
    if not name or name != Path(name).name:
        raise HTTPException(
            status_code=400,
            detail={"error": "无效的日志文件名", "code": "INVALID_LOG_NAME"},
        )
    if not name.endswith(".log"):
        raise HTTPException(
            status_code=400,
            detail={"error": "仅支持 .log 文件", "code": "INVALID_LOG_NAME"},
        )
    path = (_logs_dir() / name).resolve()
    if path.parent != _logs_dir():
        raise HTTPException(
            status_code=400,
            detail={"error": "无效的日志路径", "code": "INVALID_LOG_PATH"},
        )
    return path


def _tail_lines(path: Path, *, max_lines: int) -> tuple[str, bool]:
    if not path.is_file():
        return "", False

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()

    truncated = len(lines) > max_lines
    if truncated:
        lines = lines[-max_lines:]
    return "".join(lines), truncated


@router.get("")
async def list_logs() -> dict:
    log_dir = _logs_dir()
    items: list[dict] = []
    for path in sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return {"files": items}


@router.get("/activity")
async def read_activity_log(
    limit: int = Query(200, ge=1, le=500),
) -> dict:
    from server import model_manager
    from server.user_activity_log import recent

    items = recent(limit=limit)
    if model_manager.is_loading():
        from server.queue_service import queue_service

        elapsed = int(model_manager.load_elapsed_seconds())
        active = next(
            (item for item in queue_service.list() if item.status == "transcribing"),
            None,
        )
        # A deleted task can leave the third-party model loader unwinding in
        # the background.  Do not show that internal work as an active user
        # task after its durable queue row has already been removed.
        if active is not None:
            items.insert(
                0,
                {
                    "id": "live-model-loading",
                    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "level": "warning" if elapsed >= 120 else "info",
                    "message": f"语音识别模型正在加载，已等待 {elapsed} 秒",
                    "detail": (
                        "模型加载时间明显偏长，任务正在等待模型，音频下载已经完成。"
                        if elapsed >= 120
                        else "首次加载模型时需要读取本地模型文件并初始化显卡。"
                    ),
                    "task_id": active.id,
                    "title": active.title,
                    "live": True,
                },
            )
    return {"items": items[:limit], "updated_at": datetime.now().astimezone().isoformat()}


@router.get("/{name}")
async def read_log(
    name: str,
    lines: int = Query(_DEFAULT_TAIL_LINES, ge=1, le=_MAX_TAIL_LINES),
) -> dict:
    path = _safe_log_path(name)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"error": "日志文件不存在", "code": "LOG_NOT_FOUND"},
        )
    content, truncated = _tail_lines(path, max_lines=lines)
    stat = path.stat()
    return {
        "name": path.name,
        "content": content,
        "truncated": truncated,
        "lines_requested": lines,
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }
