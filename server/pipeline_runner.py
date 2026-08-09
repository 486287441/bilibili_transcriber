"""Pipeline stages with progress reporting (M05)."""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from server.progress_tracker import progress_tracker


def _ytdlp_progress_hook(task_id: str, *, has_bytes: threading.Event | None = None):
    def hook(data: dict) -> None:
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
    done = threading.Event()
    start = _time.monotonic()

    def ticker() -> None:
        from server import progress_db

        total = duration_sec or 600.0
        est = progress_db.estimate_phase_seconds(duration_sec=duration_sec, phase="transcribe")
        while not done.wait(0.5):
            elapsed = _time.monotonic() - start
            pct = 100.0 * (1.0 - math.exp(-elapsed / max(est, 1.0)))
            pct = min(pct, 95.0)
            progress_tracker.update(
                task_id,
                phase_progress=pct,
                detail={
                    "processed_sec": min(total, elapsed),
                    "total_sec": total,
                },
            )

    thread = threading.Thread(target=ticker, name=f"asr-progress-{task_id[:8]}", daemon=True)
    thread.start()
    try:
        text = transcribe_offline(audio_path, model)
    finally:
        done.set()
        thread.join(timeout=1.0)
    if text:
        progress_tracker.update(task_id, phase_progress=100.0, detail={"processed_sec": duration_sec})
    return text


def polish_with_progress(
    text: str,
    *,
    title: str,
    url: str,
    task_id: str,
    open_browser: bool,
    input_is_trusted: bool = False,
) -> tuple[bool, str | None]:
    from pipeline import publish_or_fallback_result

    progress_tracker.set_phase(task_id, "polish")
    polish_chars = len(text)
    progress_tracker.update(task_id, detail={"polish_chars": polish_chars})

    done = threading.Event()
    start = time.monotonic()

    def ticker() -> None:
        from server.polish_estimate import (
            estimate_polish_seconds,
            estimate_polish_time,
            polish_progress_percent,
        )

        api_estimate = estimate_polish_time(polish_chars)
        total_est = estimate_polish_seconds(polish_chars, use_mean_api=True)
        while not done.wait(0.5):
            elapsed = time.monotonic() - start
            pct = polish_progress_percent(elapsed, api_estimate, total_sec=total_est)
            progress_tracker.update(task_id, phase_progress=pct)

    thread = threading.Thread(target=ticker, name=f"polish-progress-{task_id[:8]}", daemon=True)
    thread.start()
    try:
        ok, doc_url = publish_or_fallback_result(
            text,
            title=title,
            url=url,
            open_browser=open_browser,
            task_id=task_id,
            input_is_trusted=input_is_trusted,
        )
    finally:
        done.set()
        thread.join(timeout=1.0)
    progress_tracker.update(task_id, phase_progress=100.0)
    return ok, doc_url
