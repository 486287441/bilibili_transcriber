"""History business logic and WebSocket events (M07)."""

from __future__ import annotations

import asyncio
import logging
import os

from server import history_db
from server.article_store import delete_polished, load_polished
from server.history_db import HistoryRow, init_history
from server.queue_db import TaskRow
from server.websocket_manager import ws_manager

logger = logging.getLogger("server.history")


class HistoryService:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def initialize(self) -> None:
        init_history()

    def archive_task(
        self,
        task: TaskRow,
        *,
        processing_duration_sec: float | None,
        local_audio_path: str | None = None,
    ) -> HistoryRow:
        row = history_db.upsert_from_task(
            task_id=task.id,
            url=task.url,
            title=task.title,
            duration_sec=task.duration_sec,
            site=task.site,
            source=task.source,
            status=task.status,
            processing_duration_sec=processing_duration_sec,
            output_doc_url=task.output_doc_url,
            output_text_path=task.output_text_path,
            local_audio_path=local_audio_path,
            error_message=task.error_message,
        )
        self._broadcast("history.created", {"id": row.id, "task_id": task.id, "status": row.status})
        return row

    def get(self, history_id: str) -> HistoryRow:
        row = history_db.get_history(history_id)
        if not row:
            raise KeyError(history_id)
        return row

    def get_article_text(self, history_id: str) -> str:
        row = self.get(history_id)
        polished = load_polished(row.task_id)
        if polished:
            return polished
        raise FileNotFoundError("整理后文稿不可用")

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        query: str | None = None,
    ) -> dict:
        rows, total = history_db.list_history(
            page=page, page_size=page_size, status=status, query=query
        )
        return {
            "items": [r.to_dict() for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def delete(self, history_id: str, *, remove_files: bool = True) -> None:
        row = self.get(history_id)
        history_db.delete_history(history_id)
        if remove_files:
            delete_polished(row.task_id)
            for path in (row.local_audio_path, row.output_text_path):
                if path and os.path.isfile(path):
                    try:
                        os.remove(path)
                    except OSError:
                        logger.warning("删除历史关联文件失败: %s", path)
        self._broadcast("history.deleted", {"id": history_id})

    def _broadcast(self, event_type: str, payload: dict) -> None:
        from server.bootstrap_cache import refresh_async

        refresh_async()
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(event_type, payload), self._loop)


history_service = HistoryService()
