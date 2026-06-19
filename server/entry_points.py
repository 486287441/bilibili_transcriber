"""Unified URL submission for clipboard and API entry points."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from server.queue_db import TaskRow
from server.queue_service import DuplicateTaskError, queue_service
from video_urls import detect_site

logger = logging.getLogger("server.entry")

Source = Literal["clipboard", "api"]


@dataclass
class SubmitResult:
    task: TaskRow | None
    duplicate: bool = False
    skipped_history: bool = False
    existing_id: str | None = None

    @property
    def skipped_recent(self) -> bool:
        """Backward-compatible alias for history-based skip."""
        return self.skipped_history


def submit_url(
    url: str,
    *,
    source: Source,
    silent_duplicate: bool = False,
    emit_clipboard_detected: bool = False,
) -> SubmitResult:
    """Enqueue a validated video URL unless it already exists in history."""
    from server import history_db

    history_db.init_history()
    existing_history = history_db.find_by_url(url)
    if existing_history:
        logger.debug("跳过已在历史记录中的 URL: %s history_id=%s", url, existing_history.id)
        return SubmitResult(
            task=None,
            skipped_history=True,
            existing_id=existing_history.id,
        )

    try:
        task = queue_service.enqueue(
            url,
            source=source,
            site=detect_site(url),
        )
    except DuplicateTaskError as exc:
        if silent_duplicate:
            logger.debug("重复 URL 已忽略: %s", url)
        return SubmitResult(task=None, duplicate=True, existing_id=exc.existing_id)

    if emit_clipboard_detected and source == "clipboard":
        queue_service.emit_clipboard_detected(url, detect_site(url))

    return SubmitResult(task=task)


def pending_count() -> int:
    from server import queue_db

    return queue_db.count_by_status("pending")
