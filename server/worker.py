"""Background pipeline worker driven by SQLite queue."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path

import config
from server import activity, model_manager, progress_db
from server.history_service import history_service
from server.idle_manager import idle_manager
from server.metadata import schedule_metadata_fetch
from server.pipeline_runner import (
    download_with_progress,
    polish_with_progress,
    transcribe_with_progress,
)
from server.polish_estimate import estimate_input_tokens
from server.settings_store import should_auto_open_feishu
from server.progress_tracker import progress_tracker
from server.queue_db import TaskRow
from server.queue_service import TaskNotFoundError, queue_service
from server.runtime import set_processing, set_worker_state
from server.websocket_manager import ws_manager

logger = logging.getLogger("server.worker")

_QUEUE_LOG_PATH = config.PROJECT_ROOT / "downloads" / "queue_events.log"


class WorkerService:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._processing_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._current_task_id: str | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        queue_service.set_event_loop(loop)
        progress_tracker.set_event_loop(loop)
        history_service.set_event_loop(loop)
        idle_manager.set_event_loop(loop)

    def _schedule_metadata(self, task_id: str, url: str) -> None:
        schedule_metadata_fetch(task_id, url, self._on_metadata_ready)

    def _on_metadata_ready(
        self,
        task_id: str,
        title: str | None,
        duration_sec: float | None,
    ) -> None:
        try:
            updated = queue_service.update_metadata(task_id, title=title, duration_sec=duration_sec)
            progress_tracker.start_task(task_id, duration_sec=updated.duration_sec)
        except Exception:
            logger.exception("写入 metadata 失败 task_id=%s", task_id)

    @property
    def worker_state(self) -> str:
        if self._stop_event.is_set() and self._thread and self._thread.is_alive():
            return "stopping"
        if self._processing_lock.locked():
            return "busy"
        return "idle"

    def start(self) -> None:
        queue_service.set_metadata_hook(self._schedule_metadata)
        queue_service.initialize()
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="pipeline-worker", daemon=False)
        self._thread.start()
        logger.info("Worker 线程已启动（SQLite 队列）")
        self._broadcast_state()

    def stop(self, *, timeout: float = 30.0) -> None:
        if not self._thread:
            return
        logger.info("正在停止 Worker（最长等待 %.0f 秒）…", timeout)
        self._stop_event.set()
        self._broadcast_state()
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            logger.warning("Worker 未在超时内结束，继续关闭")
        self._thread = None
        model_manager.unload_model(unload_source="shutdown")
        set_processing(False)
        set_worker_state("idle")

    def enqueue(self, url: str, *, source: str = "api", **kwargs) -> TaskRow:
        return queue_service.enqueue(url, source=source, **kwargs)

    def list_tasks(self, *, status: str | None = None) -> list[dict]:
        return [t.to_dict() for t in queue_service.list(status=status)]

    def _broadcast_state(self) -> None:
        if not self._loop:
            return
        payload = {
            "worker_state": self.worker_state,
            "model_loaded": model_manager.is_model_loaded(),
            "is_processing": self._processing_lock.locked(),
        }
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast("service.state", payload),
            self._loop,
        )

    def _append_queue_log(self, event: str, task: TaskRow) -> None:
        _QUEUE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "task_id": task.id,
            "source": task.source,
            "url": task.url,
            "status": task.status,
        }
        if task.error_message:
            row["error_message"] = task.error_message
        with _QUEUE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            task = queue_service.claim_next()
            if not task:
                time.sleep(0.5)
                continue

            with self._processing_lock:
                self._current_task_id = task.id
                activity.touch()
                set_processing(True)
                set_worker_state("busy")
                self._broadcast_state()
                try:
                    self._process_task(task)
                finally:
                    self._current_task_id = None
                    queue_service.clear_cancel(task.id)
                    progress_tracker.clear_task(task.id)
                    set_processing(False)
                    set_worker_state("idle")
                    activity.touch()
                    self._broadcast_state()

    def _check_cancelled(self, task: TaskRow) -> bool:
        if not queue_service.is_cancel_requested(task.id):
            return False
        old_status = task.status
        try:
            current = queue_service.get(task.id)
            old_status = current.status
            queue_service.transition(task.id, "cancelled")
            from server import queue_db

            queue_db.delete_task(task.id)
        except TaskNotFoundError:
            pass
        queue_service.finish_cancel(task.id, old_status)
        progress_tracker.clear_task(task.id)
        logger.info("任务已取消 task_id=%s", task.id)
        return True

    def _maybe_cleanup_audio(self, audio_file: str | None) -> None:
        if not audio_file or not os.path.isfile(audio_file):
            return
        from bilibili_transcriber import _cleanup_audio

        _cleanup_audio(audio_file)

    def _finalize_task(
        self,
        task: TaskRow,
        final: TaskRow,
        *,
        started_at: float,
        audio_file: str | None,
    ) -> None:
        elapsed = time.monotonic() - started_at
        if final.status in {"completed", "failed"}:
            history_service.archive_task(
                final,
                processing_duration_sec=round(elapsed, 2),
                local_audio_path=None,
            )
        if final.status == "completed":
            progress_tracker.complete_task(task.id)
            try:
                queue_service.delete(task.id)
            except TaskNotFoundError:
                pass
        self._append_queue_log("finished", final)

    def _process_task(self, task: TaskRow) -> None:
        started_mono = time.monotonic()
        phase_times: dict[str, float] = {}
        audio_file: str | None = None
        transcript_dir = config.PROJECT_ROOT / "downloads" / "transcripts"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        text_path = str(transcript_dir / f"{task.id}.txt")

        self._append_queue_log("started", task)
        logger.info("开始处理 task_id=%s url=%s mode=%s", task.id, task.url, task.reprocess_mode)
        progress_tracker.start_task(task.id, duration_sec=task.duration_sec)

        if self._check_cancelled(task):
            return

        try:
            if task.reprocess_mode == "polish_only":
                final = self._run_polish_only(task, text_path=text_path)
                self._finalize_task(task, final, started_at=started_mono, audio_file=None)
                return

            meta = {"title": task.title or "未命名视频", "url": task.url}

            if task.reprocess_mode == "transcribe_and_polish" and task.local_audio_path:
                audio_file = task.local_audio_path
                if not os.path.isfile(audio_file):
                    final = queue_service.handle_failure(task.id, "本地音频文件不存在")
                    self._finalize_task(task, final, started_at=started_mono, audio_file=None)
                    return
            else:
                if task.retry_count > 0:
                    delay = min(2 ** task.retry_count, 10)
                    logger.info(
                        "下载重试退避 task_id=%s retry=%d delay=%ds",
                        task.id,
                        task.retry_count,
                        delay,
                    )
                    time.sleep(delay)
                t0 = time.monotonic()
                audio_file, meta_dl, dl_error = download_with_progress(task.url, task.id)
                phase_times["download"] = time.monotonic() - t0
                if not (audio_file and os.path.exists(audio_file) and meta_dl):
                    msg = dl_error or "下载音频失败"
                    logger.error("下载失败 task_id=%s url=%s err=%s", task.id, task.url, msg)
                    final = queue_service.handle_failure(task.id, msg)
                    self._finalize_task(task, final, started_at=started_mono, audio_file=audio_file)
                    return
                meta = meta_dl
                title = (meta.get("title") or "").strip()
                if title:
                    task = queue_service.update_metadata(
                        task.id,
                        title=title,
                        duration_sec=task.duration_sec,
                    )
                if self._check_cancelled(task):
                    self._maybe_cleanup_audio(audio_file)
                    return

            queue_service.transition(task.id, "transcribing")
            idle_manager.set_transcribing(True)
            try:
                if self._check_cancelled(task):
                    return
                t0 = time.monotonic()
                text = transcribe_with_progress(
                    audio_file,
                    model_manager.get_model(),
                    task.id,
                    duration_sec=task.duration_sec or meta.get("duration"),
                )
                phase_times["transcribe"] = time.monotonic() - t0
            finally:
                idle_manager.set_transcribing(False)

            if not text:
                final = queue_service.handle_failure(task.id, "转写失败")
                self._finalize_task(task, final, started_at=started_mono, audio_file=audio_file)
                return

            Path(text_path).write_text(text.strip() + "\n", encoding="utf-8")
            from server import queue_db

            queue_db.update_task_fields(task.id, output_text_path=text_path)

            if self._check_cancelled(task):
                return

            queue_service.transition(task.id, "polishing")
            t0 = time.monotonic()
            ok, doc_url = polish_with_progress(
                text,
                title=meta["title"],
                url=meta["url"],
                task_id=task.id,
                open_browser=should_auto_open_feishu(),
            )
            phase_times["polish"] = time.monotonic() - t0

            if not ok:
                final = queue_service.handle_failure(task.id, "发布失败（已执行回退流程）")
                self._finalize_task(task, final, started_at=started_mono, audio_file=audio_file)
                return

            final = queue_service.complete(task.id, doc_url=doc_url or "", text_path=text_path)
            logger.info("处理完成 task_id=%s doc=%s", task.id, doc_url)

            progress_db.record_stats(
                task_id=task.id,
                duration_sec=task.duration_sec,
                download_sec=phase_times.get("download", 0.0),
                transcribe_sec=phase_times.get("transcribe", 0.0),
                polish_sec=phase_times.get("polish", 0.0),
                polish_chars=len(text),
                polish_tokens=estimate_input_tokens(len(text)),
            )
            self._finalize_task(task, final, started_at=started_mono, audio_file=audio_file)
        except Exception as exc:
            logger.exception("任务处理异常 task_id=%s", task.id)
            final = queue_service.handle_failure(task.id, str(exc))
            self._finalize_task(task, final, started_at=started_mono, audio_file=audio_file)
        finally:
            self._maybe_cleanup_audio(audio_file)

    def _run_polish_only(self, task: TaskRow, *, text_path: str) -> TaskRow:
        from server.history_db import get_history

        hist = get_history(task.history_source_id) if task.history_source_id else None
        path = (hist.output_text_path if hist else None) or task.output_text_path
        if not path or not os.path.isfile(path):
            return queue_service.handle_failure(task.id, "找不到已存转写文本")
        text = Path(path).read_text(encoding="utf-8")
        queue_service.transition(task.id, "polishing")
        ok, doc_url = polish_with_progress(
            text,
            title=task.title or (hist.title if hist else "未命名视频"),
            url=task.url,
            task_id=task.id,
            open_browser=should_auto_open_feishu(),
        )
        if not ok:
            return queue_service.handle_failure(task.id, "发布失败（已执行回退流程）")
        return queue_service.complete(task.id, doc_url=doc_url or "", text_path=path)


worker_service = WorkerService()
