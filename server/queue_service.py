"""Task queue business logic, state machine, and WebSocket notifications."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable

from server import queue_db
from server.error_summary import summarize_task_error
from server.progress_tracker import progress_tracker
from server.queue_db import TaskRow, init_db, recover_interrupted
from server.websocket_manager import ws_manager
from video_urls import detect_site

logger = logging.getLogger("server.queue")

# Valid transitions: each status maps to allowed next statuses.
_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"downloading", "failed", "cancelled"},
    "downloading": {"transcribing", "failed", "pending", "cancelled"},
    "transcribing": {"polishing", "failed", "pending", "cancelled"},
    "polishing": {"completed", "failed", "pending", "cancelled"},
    "completed": set(),
    "failed": {"pending"},
    "cancelled": set(),
}

ACTIVE_STATUSES = frozenset({"pending", "downloading", "transcribing", "polishing"})


class DuplicateTaskError(Exception):
    def __init__(self, existing_id: str) -> None:
        self.existing_id = existing_id
        super().__init__(f"duplicate active url: {existing_id}")


class InvalidTransitionError(Exception):
    pass


class TaskNotFoundError(Exception):
    pass


class TaskInProgressError(Exception):
    pass


class QueueService:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._cancel_requests: set[str] = set()
        self._on_enqueue_metadata: Callable[[str, str], None] | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def set_metadata_hook(self, hook: Callable[[str, str], None]) -> None:
        self._on_enqueue_metadata = hook

    def initialize(self) -> None:
        init_db()
        from server import progress_db
        from server.history_service import history_service

        progress_db.init_progress_stats()
        history_service.initialize()
        recovered = recover_interrupted()
        if recovered:
            logger.info("恢复中断任务 %d 条: %s", len(recovered), recovered)
        purged = queue_db.purge_completed_tasks()
        if purged:
            logger.info("清理已完成队列任务 %d 条", purged)

    def is_cancel_requested(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._cancel_requests

    def request_cancel(self, task_id: str) -> None:
        with self._lock:
            self._cancel_requests.add(task_id)

    def clear_cancel(self, task_id: str) -> None:
        with self._lock:
            self._cancel_requests.discard(task_id)

    def finish_cancel(self, task_id: str, old_status: str) -> None:
        self.clear_cancel(task_id)
        self._emit_state_changed(task_id, old_status, "cancelled")
        self._emit_queue_updated("cancel", task_id)

    def validate_transition(self, old: str, new: str) -> None:
        allowed = _TRANSITIONS.get(old, set())
        if new not in allowed:
            raise InvalidTransitionError(f"illegal transition {old} -> {new}")

    def transition(self, task_id: str, new_status: str, **extra: Any) -> TaskRow:
        task = queue_db.get_task(task_id)
        if not task:
            raise TaskNotFoundError(task_id)
        self.validate_transition(task.status, new_status)
        old_status = task.status
        updated = queue_db.update_task_fields(task_id, status=new_status, **extra)
        assert updated is not None
        self._emit_state_changed(task_id, old_status, new_status)
        return updated

    def enqueue(
        self,
        url: str,
        *,
        source: str = "api",
        telegram_chat_id: int | None = None,
        site: str | None = None,
        reprocess_mode: str | None = None,
        history_source_id: str | None = None,
        local_audio_path: str | None = None,
        title: str | None = None,
        duration_sec: float | None = None,
    ) -> TaskRow:
        from server import activity

        activity.touch()
        existing = queue_db.find_active_by_url(url)
        if existing:
            raise DuplicateTaskError(existing.id)

        task = queue_db.create_pending_task(
            url=url,
            source=source,
            telegram_chat_id=telegram_chat_id,
            site=site or detect_site(url),
            reprocess_mode=reprocess_mode,
            history_source_id=history_source_id,
            local_audio_path=local_audio_path,
            title=title,
            duration_sec=duration_sec,
        )

        logger.info("任务入队 id=%s url=%s", task.id, url)
        self._emit_queue_updated("enqueue", task.id)
        if self._on_enqueue_metadata:
            self._on_enqueue_metadata(task.id, url)
        return task

    def get(self, task_id: str) -> TaskRow:
        task = queue_db.get_task(task_id)
        if not task:
            raise TaskNotFoundError(task_id)
        return task

    def list(self, *, status: str | None = None) -> list[TaskRow]:
        return queue_db.list_tasks(status=status)

    def delete(self, task_id: str) -> None:
        task = self.get(task_id)
        if task.status in ACTIVE_STATUSES - {"pending"}:
            raise TaskInProgressError("进行中的任务需先取消")
        if task.status == "pending":
            queue_db.delete_task(task_id)
            self._emit_queue_updated("delete", task_id)
            return
        if task.status in {"completed", "failed", "cancelled"}:
            queue_db.delete_task(task_id)
            self._emit_queue_updated("delete", task_id)
            return
        raise TaskInProgressError("无法删除该状态的任务")

    def cancel(self, task_id: str) -> TaskRow:
        task = self.get(task_id)
        if task.status == "pending":
            updated = self.transition(task_id, "cancelled")
            queue_db.delete_task(task_id)
            self._emit_queue_updated("cancel", task_id)
            return updated
        if task.status in {"downloading", "transcribing", "polishing"}:
            old_status = task.status
            self.request_cancel(task_id)
            queue_db.delete_task(task_id)
            progress_tracker.clear_task(task_id)
            self.finish_cancel(task_id, old_status)
            return task
        raise TaskInProgressError("只能取消 pending 或进行中的任务")

    def retry(self, task_id: str, *, reset_retry_count: bool = True) -> TaskRow:
        task = self.get(task_id)
        if task.status not in {"failed", "cancelled"}:
            raise InvalidTransitionError("只有 failed 任务可手动重试")
        fields: dict[str, Any] = {
            "status": "pending",
            "error_message": None,
            "completed_at": None,
            "output_doc_url": None,
        }
        if reset_retry_count:
            fields["retry_count"] = 0
        old_status = task.status
        updated = queue_db.update_task_fields(task_id, **fields)
        assert updated is not None
        self._emit_state_changed(task_id, old_status, "pending")
        self._emit_queue_updated("retry", task_id)
        return updated

    def reorder(self, ids: list[str]) -> list[TaskRow]:
        if not ids:
            return self.list()
        existing = {t.id for t in self.list()}
        if set(ids) - existing:
            raise TaskNotFoundError("reorder 包含未知任务 id")
        tasks = queue_db.reorder_tasks(ids)
        self._emit_queue_updated("reorder", None)
        return tasks

    def handle_failure(self, task_id: str, message: str) -> TaskRow:
        task = self.get(task_id)
        brief = summarize_task_error(message) or message
        retry_count = task.retry_count + 1
        if retry_count < task.max_retries:
            updated = queue_db.update_task_fields(
                task_id,
                status="pending",
                retry_count=retry_count,
                error_message=brief,
            )
            assert updated is not None
            self._emit_state_changed(task_id, task.status, "pending")
            logger.warning(
                "任务失败将重试 id=%s retry=%d/%d err=%s",
                task_id,
                retry_count,
                task.max_retries,
                message,
            )
            return updated

        updated = queue_db.update_task_fields(
            task_id,
            status="failed",
            retry_count=retry_count,
            error_message=brief,
            completed_at=queue_db._now_iso(),
        )
        assert updated is not None
        self._emit_state_changed(task_id, task.status, "failed")
        return updated

    def complete(
        self,
        task_id: str,
        *,
        doc_url: str,
        text_path: str | None = None,
    ) -> TaskRow:
        return self.transition(
            task_id,
            "completed",
            output_doc_url=doc_url,
            output_text_path=text_path,
            completed_at=queue_db._now_iso(),
            error_message=None,
        )

    def update_metadata(
        self,
        task_id: str,
        *,
        title: str | None,
        duration_sec: float | None,
    ) -> TaskRow:
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if duration_sec is not None:
            fields["duration_sec"] = duration_sec
        if not fields:
            return self.get(task_id)
        updated = queue_db.update_task_fields(task_id, **fields)
        assert updated is not None
        self._emit_metadata_ready(
            task_id,
            updated.title,
            updated.duration_sec,
        )
        return updated

    def emit_clipboard_detected(self, url: str, site: str) -> None:
        self._broadcast("clipboard.detected", {"url": url, "site": site})

    def claim_next(self) -> TaskRow | None:
        return queue_db.claim_next_pending()

    def _broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(event_type, payload), self._loop)

    def _emit_queue_updated(self, action: str, task_id: str | None) -> None:
        self._broadcast("queue.updated", {"action": action, "task_id": task_id})

    def _emit_state_changed(self, task_id: str, old_status: str, new_status: str) -> None:
        self._broadcast(
            "task.state_changed",
            {"task_id": task_id, "old_status": old_status, "new_status": new_status},
        )

    def _emit_metadata_ready(
        self,
        task_id: str,
        title: str | None,
        duration_sec: float | None,
    ) -> None:
        self._broadcast(
            "task.metadata_ready",
            {"task_id": task_id, "title": title, "duration_sec": duration_sec},
        )


queue_service = QueueService()
