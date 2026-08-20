"""Persistent, user-facing Chinese activity timeline.

This is deliberately separate from ``server.log``: technical tracebacks remain
available for developers, while the settings UI receives concise explanations
that are safe and useful to ordinary users.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Literal

import config

Level = Literal["info", "success", "warning", "error"]

_PATH = config.PROJECT_ROOT / "logs" / "activity.jsonl"
_LOCK = threading.Lock()


def explain_error(error: object, *, fallback: str = "处理失败，请稍后重试。") -> str:
    """Translate common dependency/network failures into concise Chinese."""
    text = str(error or "").strip()
    lower = text.lower()
    translations = (
        (("timeout", "timed out"), "操作等待超时，请检查网络后重试。"),
        (("connection", "connect"), "网络连接失败，请检查网络或代理设置。"),
        (("cuda out of memory", "out of memory"), "显卡显存不足，请关闭占用显卡的程序后重试。"),
        (("cuda", "cudnn"), "显卡运行环境异常，请检查 CUDA、驱动和模型安装。"),
        (("cookie", "sessdata"), "登录 Cookie 不可用或已经失效。"),
        (("ffmpeg", "ffprobe"), "音视频处理工具运行失败，请检查 FFmpeg 安装。"),
        (("429", "rate limit"), "接口请求过于频繁，请稍后再试。"),
        (("401", "unauthorized"), "接口鉴权失败，请检查 API Key。"),
    )
    for needles, translated in translations:
        if any(needle in lower for needle in needles):
            return translated
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return text[:300]
    return fallback


def record(
    message: str,
    *,
    level: Level = "info",
    task_id: str | None = None,
    title: str | None = None,
    detail: str | None = None,
) -> dict:
    event = {
        "id": uuid.uuid4().hex,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "level": level,
        "message": str(message).strip(),
        "task_id": task_id,
        "title": (title or "").strip() or None,
        "detail": (detail or "").strip() or None,
    }
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with _PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def recent(*, limit: int = 200) -> list[dict]:
    if not _PATH.is_file():
        return []
    rows: deque[dict] = deque(maxlen=max(1, min(int(limit), 500)))
    with _LOCK:
        with _PATH.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(item, dict) and item.get("message"):
                    rows.append(item)
    return list(reversed(rows))
