"""Independent, recoverable Feishu publishing queue.

The main video worker finishes as soon as local Markdown is durable.  Feishu
network calls run here so a slow document write never blocks the next video.
"""

from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime

from feishu_client import create_video_document
from server import history_db
from server.article_store import load_polished

logger = logging.getLogger("server.feishu_publish")


class FeishuPublishQueue:
    def __init__(self) -> None:
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._queued: set[str] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="feishu-publisher",
            daemon=True,
        )
        self._thread.start()
        resumed = 0
        for row in history_db.list_pending_publications():
            if row.task_id and self.enqueue(row.task_id):
                resumed += 1
        logger.info("飞书后台发布线程已启动，恢复待发布任务 %d 条", resumed)

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._queue.put(None)
        thread = self._thread
        if thread:
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("飞书后台发布仍在收尾，将随进程退出")
        self._thread = None

    def enqueue(self, task_id: str) -> bool:
        task_id = (task_id or "").strip()
        if not task_id:
            return False
        with self._lock:
            if task_id in self._queued:
                return False
            self._queued.add(task_id)
        self._queue.put(task_id)
        return True

    def _run(self) -> None:
        while not self._stop_event.is_set():
            task_id = self._queue.get()
            if task_id is None:
                self._queue.task_done()
                break
            try:
                self._publish(task_id)
            except Exception:
                logger.exception("飞书后台发布线程异常 task_id=%s", task_id)
            finally:
                with self._lock:
                    self._queued.discard(task_id)
                self._queue.task_done()

    def _publish(self, task_id: str) -> None:
        from pipeline import open_feishu_in_browser
        from server.history_service import history_service
        from server.settings_store import should_auto_open_feishu

        row = history_db.get_history_by_task_id(task_id)
        if not row or row.status != "completed" or row.publish_status == "published":
            return
        body_md = load_polished(task_id)
        if not body_md:
            history_service.update_publish_state(
                task_id,
                "failed",
                error="本地 Markdown 不存在，无法发布到飞书",
            )
            return

        history_service.update_publish_state(task_id, "publishing")
        try:
            transcribed_at = datetime.fromisoformat(row.processed_at)
        except (TypeError, ValueError):
            transcribed_at = datetime.now()

        delays = (0, 5, 20)
        last_error: Exception | None = None
        for attempt, delay in enumerate(delays, start=1):
            if delay and self._stop_event.wait(delay):
                history_service.update_publish_state(task_id, "pending")
                return
            try:
                doc_url = create_video_document(
                    title=row.title or "未命名视频",
                    url=row.url,
                    transcribed_at=transcribed_at,
                    body_md=body_md,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "飞书后台发布失败 task_id=%s attempt=%d/%d: %s",
                    task_id,
                    attempt,
                    len(delays),
                    exc,
                )
                continue

            history_service.update_publish_state(
                task_id,
                "published",
                output_doc_url=doc_url,
            )
            logger.info("飞书后台发布完成 task_id=%s doc=%s", task_id, doc_url)
            if should_auto_open_feishu():
                open_feishu_in_browser(doc_url)
            return

        history_service.update_publish_state(
            task_id,
            "failed",
            error=str(last_error or "飞书发布失败"),
        )


feishu_publish_queue = FeishuPublishQueue()
