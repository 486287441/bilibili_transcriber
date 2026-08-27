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
    PolishCancelled,
    download_video_with_progress,
    download_with_progress,
    polish_with_progress,
    transcribe_with_progress,
)
from server.polish_estimate import estimate_input_tokens
from server.settings_store import (
    get_auto_fallback_route,
    is_first_stage_enabled,
    should_auto_open_feishu,
)
from server.progress_tracker import progress_tracker
from server.queue_db import TaskRow
from server.queue_service import TaskNotFoundError, queue_service
from server.runtime import set_processing, set_worker_state
from server.transcript_routes import (
    TranscriptRouteUnavailable,
    TranscriptSegment,
    normalize_requested_route,
    save_transcript_artifacts,
)
from server.websocket_manager import ws_manager
from server.user_activity_log import explain_error, record as record_user_activity

logger = logging.getLogger("server.worker")

_QUEUE_LOG_PATH = config.PROJECT_ROOT / "downloads" / "queue_events.log"


class _TaskCancelled(RuntimeError):
    pass


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
        # On Windows, load Torch's native runtime before a pending OCR task can
        # load Paddle.  Both frameworks work in this order; Paddle-first can
        # make Torch's shm.dll fail to resolve.  This imports no ASR weights.
        import torch  # noqa: F401

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
        try:
            from server.video_ocr import release_ocr_processor

            release_ocr_processor()
        except Exception:
            logger.exception("释放 PaddleOCR 常驻进程失败")
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

    @staticmethod
    def _user_log(
        task: TaskRow,
        message: str,
        *,
        level: str = "info",
        detail: str | None = None,
    ) -> None:
        try:
            record_user_activity(
                message,
                level=level,
                task_id=task.id,
                title=task.title,
                detail=detail,
            )
        except Exception:
            logger.exception("写入用户运行日志失败 task_id=%s", task.id)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                task = queue_service.claim_next()
            except Exception:
                logger.exception("Worker 领取队列任务失败；线程将继续运行")
                self._stop_event.wait(1.0)
                continue
            if not task:
                self._stop_event.wait(0.5)
                continue

            with self._processing_lock:
                claimed_at = time.monotonic()
                self._current_task_id = task.id
                try:
                    activity.touch()
                    set_processing(True)
                    set_worker_state("busy")
                    self._broadcast_state()
                    self._process_task(task)
                except Exception as exc:
                    # _process_task contains route-level handling, but setup,
                    # persistence, and finalization code can still fail.  One
                    # bad row must never terminate the sole queue worker.
                    logger.exception("Worker 顶层捕获未处理异常 task_id=%s", task.id)
                    self._recover_unhandled_task(task, exc, started_at=claimed_at)
                finally:
                    self._current_task_id = None
                    cleanup_steps = (
                        ("clear_cancel", lambda: queue_service.clear_cancel(task.id)),
                        ("clear_progress", lambda: progress_tracker.clear_task(task.id)),
                        ("processing_flag", lambda: set_processing(False)),
                        ("worker_state", lambda: set_worker_state("idle")),
                        ("activity", activity.touch),
                        ("broadcast", self._broadcast_state),
                    )
                    for label, cleanup in cleanup_steps:
                        try:
                            cleanup()
                        except Exception:
                            logger.exception(
                                "Worker 收尾步骤失败 task_id=%s step=%s",
                                task.id,
                                label,
                            )

    def _recover_unhandled_task(
        self,
        task: TaskRow,
        error: Exception,
        *,
        started_at: float,
    ) -> None:
        """Best-effort recovery for exceptions escaping the route pipeline."""

        try:
            current = queue_service.get(task.id)
        except TaskNotFoundError:
            return
        except Exception:
            logger.exception("读取异常任务状态失败 task_id=%s", task.id)
            return

        try:
            if current.status in {"downloading", "transcribing"} and self._check_cancelled(
                current
            ):
                return
            if current.status in {"completed", "failed"}:
                final = current
            elif current.status in {"pending", "downloading", "transcribing", "polishing"}:
                final = queue_service.handle_failure(task.id, str(error))
            else:
                return
            self._finalize_task(
                task,
                final,
                started_at=started_at,
                audio_file=None,
            )
        except Exception:
            logger.exception("恢复异常任务失败 task_id=%s", task.id)

    def _check_cancelled(self, task: TaskRow) -> bool:
        if not queue_service.is_cancel_requested(task.id):
            return False
        old_status = task.status
        current = task
        try:
            current = queue_service.get(task.id)
            old_status = current.status
            queue_service.transition(task.id, "cancelled")
            from server import queue_db

            queue_db.delete_task(task.id)
        except TaskNotFoundError:
            pass
        transcript_dir = config.PROJECT_ROOT / "downloads" / "transcripts"
        artifacts = {
            current.raw_text_path,
            current.source_segments_path,
            str(transcript_dir / f"{task.id}.txt"),
            str(transcript_dir / f"{task.id}.raw.txt"),
            str(transcript_dir / f"{task.id}.segments.json"),
            str(config.PROJECT_ROOT / "downloads" / "polished" / f"{task.id}.md"),
        }
        for artifact in artifacts:
            if artifact and os.path.isfile(artifact):
                try:
                    os.remove(artifact)
                except OSError:
                    logger.warning("取消任务时清理产物失败: %s", artifact)
        queue_service.finish_cancel(task.id, old_status)
        progress_tracker.clear_task(task.id)
        logger.info("任务已取消 task_id=%s", task.id)
        self._user_log(task, "任务已取消，临时文件正在清理", level="warning")
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
        archived = final.status not in {"completed", "failed"}
        if final.status in {"completed", "failed"}:
            try:
                history_service.archive_task(
                    final,
                    processing_duration_sec=round(elapsed, 2),
                    local_audio_path=None,
                )
                archived = True
            except Exception:
                # For a completed task, retain the queue row.  initialize()
                # will idempotently archive and remove it after a restart.
                archived = False
                logger.exception("任务历史归档失败 task_id=%s", task.id)
        if final.status == "completed":
            try:
                progress_tracker.complete_task(task.id)
            except Exception:
                logger.exception("完成进度收尾失败 task_id=%s", task.id)
            if archived:
                try:
                    queue_service.archive_completed(task.id)
                except TaskNotFoundError:
                    pass
                except Exception:
                    logger.exception("删除已归档队列任务失败 task_id=%s", task.id)
        try:
            self._append_queue_log("finished", final)
        except Exception:
            logger.exception("写入队列完成日志失败 task_id=%s", task.id)

    @staticmethod
    def _metadata_values(task: TaskRow, meta: dict | None) -> tuple[str, str, float | None]:
        meta = meta or {}
        title = str(meta.get("title") or task.title or "未命名视频").strip()
        url = str(meta.get("url") or meta.get("webpage_url") or task.url).strip()
        duration = meta.get("duration", meta.get("duration_sec", task.duration_sec))
        try:
            duration_sec = float(duration) if duration is not None else task.duration_sec
        except (TypeError, ValueError):
            duration_sec = task.duration_sec
        return title, url, duration_sec

    def _apply_metadata(self, task: TaskRow, meta: dict | None) -> tuple[TaskRow, dict]:
        title, url, duration_sec = self._metadata_values(task, meta)
        task = queue_service.update_metadata(
            task.id,
            title=title,
            duration_sec=duration_sec,
        )
        return task, {"title": title, "url": url, "duration": duration_sec}

    def _ensure_transcribing(self, task_id: str) -> TaskRow:
        current = queue_service.get(task_id)
        if current.status == "downloading":
            return queue_service.transition(task_id, "transcribing")
        return current

    @staticmethod
    def _progress_callback(task_id: str, *, start: float = 0.0, span: float = 100.0):
        def update(percent: float, detail: dict) -> None:
            progress_tracker.update(
                task_id,
                phase_progress=start + max(0.0, min(100.0, percent)) * span / 100.0,
                detail=detail,
            )

        return update

    def _run_asr_route(
        self,
        task: TaskRow,
        *,
        meta: dict,
        diagnostics: dict,
        phase_times: dict[str, float],
        audio_file: str | None = None,
    ) -> tuple[list[TranscriptSegment], TaskRow, dict, str | None]:
        """Run the existing Fun-ASR-Nano path without changing model behavior."""

        if not audio_file or not os.path.isfile(audio_file):
            self._user_log(task, "开始下载语音识别所需的音频")
            t0 = time.monotonic()
            audio_file, downloaded_meta, download_error = download_with_progress(task.url, task.id)
            phase_times["download"] = phase_times.get("download", 0.0) + (
                time.monotonic() - t0
            )
            if not (audio_file and os.path.exists(audio_file) and downloaded_meta):
                raise RuntimeError(download_error or "下载音频失败")
            task, meta = self._apply_metadata(task, downloaded_meta)
            self._user_log(
                task,
                "音频下载完成",
                level="success",
                detail=f"视频时长约 {int(task.duration_sec or meta.get('duration') or 0)} 秒，准备加载语音识别模型。",
            )

        diagnostics.update(
            {
                "resolved_route": "asr",
                "asr_model": "Fun-ASR-Nano-2512",
            }
        )
        task = queue_service.update_route_details(
            task.id,
            resolved_route="asr",
            route_diagnostics=diagnostics,
        )
        task = self._ensure_transcribing(task.id)
        idle_manager.set_transcribing(True)
        audio_existed = bool(audio_file and os.path.isfile(audio_file))
        try:
            if self._check_cancelled(task):
                raise _TaskCancelled("任务已取消")
            progress_tracker.set_phase(task.id, "transcribe")
            progress_tracker.update(
                task.id,
                phase_progress=1.0,
                detail={"message": "正在加载语音识别模型"},
            )
            self._user_log(
                task,
                "正在加载 Fun-ASR 语音识别模型",
                detail="首次加载或模型已被释放时，需要从本地磁盘读取模型并初始化显卡。",
            )
            model_load_started = time.monotonic()
            try:
                model = model_manager.get_model(
                    cancelled=lambda: (
                        queue_service.is_cancel_requested(task.id)
                        or self._stop_event.is_set()
                    )
                )
            except model_manager.ModelLoadCancelled as exc:
                raise _TaskCancelled(str(exc)) from exc
            phase_times["model_load"] = phase_times.get("model_load", 0.0) + (
                time.monotonic() - model_load_started
            )
            if self._check_cancelled(task):
                raise _TaskCancelled("任务已取消")
            self._user_log(task, "语音识别模型加载完成", level="success")
            self._user_log(task, "开始进行语音转文字")
            t0 = time.monotonic()
            text = transcribe_with_progress(
                audio_file,
                model,
                task.id,
                duration_sec=task.duration_sec or meta.get("duration"),
            )
            if text:
                self._user_log(task, "语音转文字完成", level="success")
            phase_times["transcribe"] = phase_times.get("transcribe", 0.0) + (
                time.monotonic() - t0
            )
        finally:
            idle_manager.set_transcribing(False)
            if audio_existed:
                self._maybe_cleanup_audio(audio_file)
                self._user_log(
                    task,
                    "临时音频已删除",
                    level="success",
                    detail="语音转写阶段已经结束，后续润色不再需要音频文件。",
                )
                audio_file = None
        if not text:
            raise RuntimeError("转写失败")
        duration = task.duration_sec or meta.get("duration") or 0.1
        return (
            [
                TranscriptSegment(
                    start_sec=0.0,
                    end_sec=max(0.1, float(duration)),
                    text=text,
                    source="asr",
                )
            ],
            task,
            meta,
            audio_file,
        )

    def _process_task(self, task: TaskRow) -> None:
        started_mono = time.monotonic()
        phase_times: dict[str, float] = {}
        audio_file: str | None = None
        media_file: str | None = None
        transcript_dir = config.PROJECT_ROOT / "downloads" / "transcripts"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        text_path = str(transcript_dir / f"{task.id}.txt")

        requested_route = normalize_requested_route(task.requested_route)
        auto_fallback_route = get_auto_fallback_route()
        effective_fallback_route = (
            auto_fallback_route if requested_route == "auto" else requested_route
        )
        diagnostics: dict = {
            "requested_route": requested_route,
            "decision_mode": "automatic" if requested_route == "auto" else "explicit",
            "auto_fallback_route": auto_fallback_route,
        }

        self._append_queue_log("started", task)
        self._user_log(task, "开始处理视频")
        logger.info(
            "开始处理 task_id=%s url=%s mode=%s requested_route=%s",
            task.id,
            task.url,
            task.reprocess_mode,
            requested_route,
        )
        progress_tracker.start_task(task.id, duration_sec=task.duration_sec)

        if self._check_cancelled(task):
            return

        try:
            if task.reprocess_mode == "polish_only":
                final = self._run_polish_only(task, text_path=text_path)
                self._finalize_task(task, final, started_at=started_mono, audio_file=None)
                return

            if task.retry_count > 0:
                delay = min(2 ** task.retry_count, 10)
                logger.info(
                    "任务重试退避 task_id=%s retry=%d delay=%ds",
                    task.id,
                    task.retry_count,
                    delay,
                )
                time.sleep(delay)

            meta = {"title": task.title or "未命名视频", "url": task.url}
            segments: list[TranscriptSegment] = []

            # Route 1: PaddleOCR PP-OCRv5. Automatic mode uses exactly the
            # route selected in settings; it never chains OCR then ASR.
            should_try_ocr = not segments and effective_fallback_route == "ocr"
            if should_try_ocr:
                self._user_log(task, "开始下载画面识别所需的视频")
                t0 = time.monotonic()
                video_file, video_meta, video_error = download_video_with_progress(
                    task.url, task.id
                )
                phase_times["download"] = phase_times.get("download", 0.0) + (
                    time.monotonic() - t0
                )
                if not (video_file and os.path.isfile(video_file) and video_meta):
                    raise RuntimeError(video_error or "下载 OCR 视频失败")
                else:
                    media_file = video_file
                    task, meta = self._apply_metadata(task, video_meta)
                    self._user_log(task, "OCR 视频下载完成", level="success")
                    task = self._ensure_transcribing(task.id)
                    progress_tracker.set_phase(task.id, "transcribe")
                    progress_tracker.update(
                        task.id,
                        phase_progress=1.0,
                        detail={"message": "正在加载 PaddleOCR PP-OCRv5"},
                    )

                    from server.video_ocr import (
                        OCRExtractionCancelled,
                        PaddleOCRUnavailable,
                        extract_ocr_segments,
                        get_ocr_processor,
                        ocr_uses_gpu_runtime,
                    )

                    processor = None
                    t0 = time.monotonic()
                    try:
                        paddle_uses_gpu = ocr_uses_gpu_runtime()
                        if paddle_uses_gpu:
                            model_manager.unload_model(
                                emit_event=True,
                                unload_source="ocr_route",
                            )
                        processor = get_ocr_processor()
                        self._user_log(task, "PaddleOCR 模型加载完成", level="success")
                        use_ocr = True
                        diagnostics["route_reason"] = (
                            "configured_ocr_fallback"
                            if requested_route == "auto"
                            else "explicit_ocr_route"
                        )

                        if use_ocr:
                            diagnostics["resolved_route"] = "ocr"
                            task = queue_service.update_route_details(
                                task.id,
                                resolved_route="ocr",
                                route_diagnostics=diagnostics,
                            )
                            ocr_start = 1.0
                            ocr_span = 99.0
                            segments, ocr_diagnostics = extract_ocr_segments(
                                video_file,
                                processor,
                                progress=self._progress_callback(
                                    task.id, start=ocr_start, span=ocr_span
                                ),
                                cancelled=lambda: self._stop_event.is_set()
                                or queue_service.is_cancel_requested(task.id),
                            )
                            diagnostics.update(ocr_diagnostics)
                            if not segments:
                                raise TranscriptRouteUnavailable(
                                    "PP-OCRv5 未从画面底部识别到可用字幕；自动模式不会再回落语音识别"
                                )
                            self._user_log(task, "画面字幕识别完成", level="success")
                    except OCRExtractionCancelled as exc:
                        raise _TaskCancelled(str(exc)) from exc
                    except PaddleOCRUnavailable as exc:
                        raise TranscriptRouteUnavailable(str(exc)) from exc
                    except TranscriptRouteUnavailable:
                        raise
                    except Exception as exc:
                        raise RuntimeError(f"PP-OCRv5 处理失败: {exc}") from exc
                    finally:
                        phase_times["transcribe"] = phase_times.get("transcribe", 0.0) + (
                            time.monotonic() - t0
                        )

            # Route 2: audio download + Fun-ASR-Nano. In automatic mode this
            # runs only when ASR is the configured route.
            if not segments:
                if effective_fallback_route == "ocr":
                    raise TranscriptRouteUnavailable("所选路线没有生成可用文本")
                if (
                    task.reprocess_mode == "transcribe_and_polish"
                    and task.local_audio_path
                    and os.path.isfile(task.local_audio_path)
                ):
                    audio_file = task.local_audio_path
                segments, task, meta, audio_file = self._run_asr_route(
                    task,
                    meta=meta,
                    diagnostics=diagnostics,
                    phase_times=phase_times,
                    audio_file=audio_file,
                )

            if self._check_cancelled(task):
                return

            resolved_route = queue_service.get(task.id).resolved_route
            if not resolved_route:
                raise RuntimeError("文本路线没有完成解析")
            diagnostics["resolved_route"] = resolved_route
            diagnostics["source_segment_count"] = len(segments)
            raw_text_path, source_segments_path, normalized_segments = (
                save_transcript_artifacts(
                    task.id,
                    segments,
                    diagnostics=diagnostics,
                )
            )
            text = "\n".join(segment.text for segment in normalized_segments).strip()
            if not text:
                raise TranscriptRouteUnavailable("所选路线没有生成可用文本")
            task = queue_service.update_route_details(
                task.id,
                resolved_route=resolved_route,
                route_diagnostics=diagnostics,
                raw_text_path=raw_text_path,
                source_segments_path=source_segments_path,
            )

            if self._check_cancelled(task):
                return

            task = queue_service.transition(task.id, "polishing")
            # Close the transcribe->article-processing cancellation race.
            if self._check_cancelled(task):
                return
            quick_mode = not is_first_stage_enabled()
            self._user_log(
                task,
                "开始进行本地规则排版"
                if quick_mode
                else "开始进行第一阶段校对和第二阶段内容整理",
            )
            t0 = time.monotonic()
            try:
                ok, doc_url = polish_with_progress(
                    text,
                    title=meta["title"],
                    url=meta["url"],
                    task_id=task.id,
                    open_browser=should_auto_open_feishu(),
                    cancelled=lambda: (
                        queue_service.is_cancel_requested(task.id)
                        or self._stop_event.is_set()
                    ),
                )
            except PolishCancelled as exc:
                raise _TaskCancelled(str(exc)) from exc
            phase_times["polish"] = time.monotonic() - t0

            if self._check_cancelled(task):
                return

            if not ok:
                final = queue_service.handle_failure(task.id, "文章处理失败（已执行回退流程）")
                self._finalize_task(task, final, started_at=started_mono, audio_file=audio_file)
                return

            self._user_log(
                task,
                "本地规则排版完成，Markdown 已生成"
                if quick_mode
                else "文章润色完成，本地 Markdown 已生成",
                level="success",
            )

            final = queue_service.complete(task.id, doc_url=doc_url or "", text_path=text_path)
            logger.info(
                "本地处理完成 task_id=%s route=%s，飞书将在后台发布",
                task.id,
                resolved_route,
            )
            self._user_log(task, "本地处理全部完成，飞书将在后台发布", level="success")

            try:
                progress_db.record_stats(
                    task_id=task.id,
                    duration_sec=task.duration_sec,
                    download_sec=phase_times.get("download", 0.0),
                    model_load_sec=phase_times.get("model_load", 0.0),
                    transcribe_sec=phase_times.get("transcribe", 0.0),
                    polish_sec=phase_times.get("polish", 0.0),
                    polish_chars=len(text),
                    polish_tokens=0 if quick_mode else estimate_input_tokens(len(text)),
                )
            except Exception:
                # Metrics are observational.  Never turn a successfully
                # generated local article back into a retryable task.
                logger.exception("记录处理统计失败 task_id=%s", task.id)
            self._finalize_task(task, final, started_at=started_mono, audio_file=audio_file)
        except _TaskCancelled:
            self._check_cancelled(task)
            return
        except TranscriptRouteUnavailable as exc:
            logger.warning("文本路线不可用 task_id=%s: %s", task.id, exc)
            self._user_log(task, "文本获取路线失败", level="error", detail=str(exc))
            if self._check_cancelled(task):
                return
            final = queue_service.fail_permanently(task.id, str(exc))
            self._finalize_task(
                task,
                final,
                started_at=started_mono,
                audio_file=media_file or audio_file,
            )
        except Exception as exc:
            logger.exception("任务处理异常 task_id=%s", task.id)
            self._user_log(
                task,
                "任务处理发生异常",
                level="error",
                detail=explain_error(exc),
            )
            if self._check_cancelled(task):
                return
            final = queue_service.handle_failure(task.id, str(exc))
            self._finalize_task(
                task,
                final,
                started_at=started_mono,
                audio_file=media_file or audio_file,
            )
        finally:
            self._maybe_cleanup_audio(media_file or audio_file)

    def _run_polish_only(self, task: TaskRow, *, text_path: str) -> TaskRow:
        from server.history_db import get_history

        hist = get_history(task.history_source_id) if task.history_source_id else None
        path = (hist.output_text_path if hist else None) or task.output_text_path
        if not path or not os.path.isfile(path):
            return queue_service.handle_failure(task.id, "找不到已存转写文本")
        text = Path(path).read_text(encoding="utf-8")
        inherited_route = (hist.resolved_route if hist else None) or "asr"
        task = queue_service.update_route_details(
            task.id,
            resolved_route=inherited_route,
            route_diagnostics={
                "requested_route": task.requested_route,
                "resolved_route": inherited_route,
                "route_reason": "polish_only_reused_history_text",
                "parent_history_id": task.history_source_id,
            },
        )
        task = queue_service.transition(task.id, "polishing")
        if self._check_cancelled(task):
            raise _TaskCancelled("任务已取消")
        ok, doc_url = polish_with_progress(
            text,
            title=task.title or (hist.title if hist else "未命名视频"),
            url=task.url,
            task_id=task.id,
            open_browser=should_auto_open_feishu(),
            input_is_trusted=True,
        )
        if not ok:
            return queue_service.handle_failure(task.id, "润色失败（已执行回退流程）")
        return queue_service.complete(task.id, doc_url=doc_url or "", text_path=text_path)


worker_service = WorkerService()
