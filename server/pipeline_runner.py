"""Pipeline stages with progress reporting (M05)."""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from server.progress_tracker import progress_tracker


class PolishCancelled(RuntimeError):
    """The queue task stopped waiting for an in-flight DeepSeek request."""


def _ytdlp_progress_hook(task_id: str, *, has_bytes: threading.Event | None = None):
    def hook(data: dict) -> None:
        # Raising from a yt-dlp progress hook aborts the active transfer. The
        # worker then observes the cancellation flag and performs normal cleanup.
        from server.queue_service import queue_service

        if queue_service.is_cancel_requested(task_id):
            raise RuntimeError("task cancellation requested")
        status = data.get("status")
        if status not in ("downloading", "extracting"):
            return
        downloaded = float(data.get("downloaded_bytes") or 0)
        total = float(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
        speed = float(data.get("speed") or 0)
        if downloaded > 0 and has_bytes is not None:
            has_bytes.set()
        if status == "extracting" and downloaded <= 0:
            return
        if total > 0:
            pct = min(99.0, downloaded / total * 100.0)
        else:
            pct = 0.0
        progress_tracker.update(
            task_id,
            phase_progress=pct,
            detail={
                "downloaded_bytes": int(downloaded),
                "total_bytes": int(total) if total else None,
                "speed_bps": int(speed) if speed else 0,
            },
        )

    return hook


def download_with_progress(url: str, task_id: str):
    from bilibili_transcriber import download_video_audio

    progress_tracker.set_phase(task_id, "download")
    done = threading.Event()
    has_bytes = threading.Event()
    start = time.monotonic()

    def ticker() -> None:
        from server import progress_db

        est = progress_db.estimate_phase_seconds(duration_sec=None, phase="download")
        while not done.wait(0.5):
            if has_bytes.is_set():
                continue
            elapsed = time.monotonic() - start
            pct = min(30.0, 100.0 * (1.0 - math.exp(-elapsed / max(est * 0.25, 4.0))))
            progress_tracker.update(task_id, phase_progress=pct)

    thread = threading.Thread(target=ticker, name=f"download-progress-{task_id[:8]}", daemon=True)
    thread.start()
    hook = _ytdlp_progress_hook(task_id, has_bytes=has_bytes)
    try:
        audio, meta, err = download_video_audio(url, progress_hook=hook, download_stem=task_id)
    finally:
        done.set()
        thread.join(timeout=1.0)
    if audio and meta:
        progress_tracker.update(task_id, phase_progress=100.0)
    return audio, meta, err


def download_video_with_progress(url: str, task_id: str):
    """Download a video rendition for hard-subtitle inspection/OCR."""

    from server.video_ocr import download_video_for_ocr

    progress_tracker.set_phase(task_id, "download")
    progress_tracker.update(
        task_id,
        phase_progress=1.0,
        detail={"message": "正在下载视频以检测画面字幕"},
    )
    done = threading.Event()
    has_bytes = threading.Event()
    start = time.monotonic()

    def ticker() -> None:
        from server import progress_db

        est = progress_db.estimate_phase_seconds(duration_sec=None, phase="download")
        while not done.wait(0.5):
            if has_bytes.is_set():
                continue
            elapsed = time.monotonic() - start
            pct = min(30.0, 100.0 * (1.0 - math.exp(-elapsed / max(est * 0.25, 4.0))))
            progress_tracker.update(task_id, phase_progress=pct)

    thread = threading.Thread(
        target=ticker,
        name=f"video-download-progress-{task_id[:8]}",
        daemon=True,
    )
    thread.start()
    hook = _ytdlp_progress_hook(task_id, has_bytes=has_bytes)
    try:
        video, meta, err = download_video_for_ocr(url, task_id, progress_hook=hook)
    finally:
        done.set()
        thread.join(timeout=1.0)
    if video and meta:
        progress_tracker.update(
            task_id,
            phase_progress=100.0,
            detail={"message": "视频下载完成"},
        )
    return video, meta, err


def transcribe_with_progress(
    audio_path: str,
    model,
    task_id: str,
    *,
    duration_sec: float | None,
) -> str | None:
    import time as _time

    from bilibili_transcriber import transcribe_offline

    progress_tracker.set_phase(task_id, "transcribe")
    start = _time.monotonic()
    done = threading.Event()
    asr_started_at: float | None = None

    def ticker() -> None:
        while not done.wait(0.5):
            # Recalculate the countdown between real batch completions without
            # advancing the work bar synthetically.
            progress_tracker.update(task_id)

    def on_model_progress(event: dict[str, Any]) -> None:
        nonlocal asr_started_at
        now = _time.monotonic()
        processed = float(event.get("processed_speech_sec") or 0.0)
        total = float(event.get("total_speech_sec") or 0.0)
        stage = event.get("stage")
        if stage == "vad_complete":
            asr_started_at = now
            progress_tracker.update(
                task_id,
                phase_progress=5.0,
                detail={
                    "progress_source": "funasr_vad_batches",
                    "processed_speech_sec": 0.0,
                    "total_speech_sec": total,
                    "phase_eta_phase": "transcribe",
                    "message": "语音片段分析完成，开始识别",
                },
            )
            return
        if stage != "asr_batch_complete" or total <= 0:
            return

        work_ratio = min(1.0, processed / total)
        phase_pct = min(98.0, 5.0 + work_ratio * 93.0)
        inference_elapsed = max(0.001, now - (asr_started_at or start))
        audio_per_wall_sec = processed / inference_elapsed if processed > 0 else 0.0
        remaining_sec = (
            max(0.0, total - processed) / audio_per_wall_sec
            if audio_per_wall_sec > 0
            else None
        )
        progress_tracker.update(
            task_id,
            phase_progress=phase_pct,
            detail={
                "progress_source": "funasr_vad_batches",
                "processed_speech_sec": processed,
                "total_speech_sec": total,
                "asr_audio_per_wall_sec": audio_per_wall_sec,
                "phase_eta_phase": "transcribe",
                "phase_eta_seconds": remaining_sec,
                "phase_eta_updated_elapsed_sec": now - start,
                "message": "正在识别语音片段",
            },
        )

    thread = threading.Thread(target=ticker, name=f"asr-progress-{task_id[:8]}", daemon=True)
    thread.start()
    try:
        text = transcribe_offline(audio_path, model, progress_callback=on_model_progress)
    finally:
        done.set()
        thread.join(timeout=1.0)
    if text:
        progress_tracker.update(
            task_id,
            phase_progress=100.0,
            detail={"phase_eta_seconds": 0.0},
        )
    return text


def polish_with_progress(
    text: str,
    *,
    title: str,
    url: str,
    task_id: str,
    open_browser: bool,
    input_is_trusted: bool = False,
    cancelled=None,
) -> tuple[bool, str | None]:
    from pipeline import generate_local_article_result
    progress_tracker.set_phase(task_id, "polish")
    polish_chars = len(text)

    done = threading.Event()
    start = time.monotonic()
    from server.settings_store import is_first_stage_enabled, is_second_stage_enabled

    first_stage = is_first_stage_enabled()
    second_stage = is_second_stage_enabled()
    uses_deepseek = first_stage and (not input_is_trusted or second_stage)
    progress_tracker.update(
        task_id,
        detail={
            "polish_chars": polish_chars,
            "progress_source": "deepseek_stream" if uses_deepseek else "local_format",
            "message": "正在进行本地规则排版" if not uses_deepseek else "准备文章校对与整理",
        },
    )
    expected_correct_chars = 0 if input_is_trusted or not first_stage else max(polish_chars, 1)
    expected_organize_chars = (
        max(int(polish_chars * 1.05) + 1200, 1) if first_stage and second_stage else 0
    )
    expected_by_stage = {
        "correct": expected_correct_chars,
        "organize": expected_organize_chars,
    }
    expected_total_chars = max(
        1,
        expected_correct_chars + expected_organize_chars,
    )
    completed_before = {"correct": 0, "organize": expected_correct_chars}

    def ticker() -> None:
        while not done.wait(0.5):
            # Before first token use the historical fallback; after that this
            # keeps the live ETA counting down without inventing bar progress.
            progress_tracker.update(task_id)

    def on_stream_progress(stage: str, event: dict[str, Any]) -> None:
        output_chars = max(0, int(event.get("output_chars") or 0))
        elapsed = max(0.001, float(event.get("elapsed_seconds") or 0.0))
        expected_stage = max(1, expected_by_stage.get(stage, 1))
        done_stage = bool(event.get("done"))
        stage_work = expected_stage if done_stage else min(output_chars, expected_stage)
        completed_units = completed_before.get(stage, 0) + stage_work
        phase_pct = min(95.0, completed_units / expected_total_chars * 95.0)

        chars_per_sec = output_chars / elapsed if output_chars > 0 else 0.0
        remaining_current = 0 if done_stage else max(0, expected_stage - output_chars)
        remaining_future = 0
        if stage == "correct" and expected_organize_chars:
            remaining_future = expected_organize_chars
        live_eta = (
            (remaining_current + remaining_future) / chars_per_sec
            if chars_per_sec > 0
            else None
        )
        progress_tracker.update(
            task_id,
            phase_progress=phase_pct,
            detail={
                "progress_source": "deepseek_stream",
                "polish_stage": stage,
                "stream_output_chars": output_chars,
                "stream_chars_per_sec": chars_per_sec,
                "phase_eta_phase": "polish",
                "phase_eta_seconds": live_eta,
                "phase_eta_updated_elapsed_sec": time.monotonic() - start,
                "message": "正在接收润色结果",
            },
        )

    thread = threading.Thread(target=ticker, name=f"polish-progress-{task_id[:8]}", daemon=True)
    thread.start()
    cancel_token = threading.Event()
    finished = threading.Event()
    result: list[bool] = []
    failure: list[BaseException] = []

    def generate() -> None:
        try:
            result.append(
                generate_local_article_result(
                    text,
                    task_id=task_id,
                    input_is_trusted=input_is_trusted,
                    cancelled=cancel_token.is_set,
                    progress_callback=on_stream_progress,
                )
            )
        except BaseException as exc:
            failure.append(exc)
        finally:
            finished.set()

    generator = threading.Thread(
        target=generate,
        name=f"polish-request-{task_id[:8]}",
        daemon=True,
    )
    generator.start()
    try:
        while not finished.wait(0.2):
            if cancelled is not None and cancelled():
                cancel_token.set()
                raise PolishCancelled("润色等待已取消")
        if cancelled is not None and cancelled():
            cancel_token.set()
            raise PolishCancelled("润色等待已取消")
        if failure:
            raise failure[0]
        ok = bool(result and result[0])
    finally:
        done.set()
        thread.join(timeout=1.0)
    progress_tracker.update(
        task_id,
        phase_progress=100.0,
        detail={
            "phase_eta_phase": "polish",
            "phase_eta_seconds": 0.0,
            "phase_eta_updated_elapsed_sec": time.monotonic() - start,
        },
    )
    return ok, None
