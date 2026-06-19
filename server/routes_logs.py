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
