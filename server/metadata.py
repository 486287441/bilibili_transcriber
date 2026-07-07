"""Async metadata prefetch via yt-dlp (skip download)."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger("server.metadata")


def fetch_video_metadata(url: str) -> tuple[str | None, float | None]:
    """Return (title, duration_sec) or (None, None) on failure."""
    try:
        from bilibili_transcriber import _YTDLP_LOCK, _ydl_opts_for_site
        from video_urls import detect_site
    except ImportError:
        logger.warning("yt-dlp 未安装，跳过 metadata 预拉取")
        return None, None

    site = detect_site(url)
    opts = _ydl_opts_for_site(site)
    opts.update(
        {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 30,
        }
    )
    try:
        import yt_dlp

        with _YTDLP_LOCK:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        if not info:
            return None, None
        title = info.get("title")
        duration = info.get("duration")
        duration_sec = float(duration) if duration is not None else None
        return title, duration_sec
    except Exception:
        logger.exception("metadata 预拉取失败 url=%s", url)
        return None, None


def schedule_metadata_fetch(task_id: str, url: str, on_done) -> None:
    """Run metadata fetch in a daemon thread and call *on_done(task_id, title, duration)*."""

    def _run() -> None:
        title, duration = fetch_video_metadata(url)
        if title or duration is not None:
            on_done(task_id, title, duration)

    threading.Thread(target=_run, name=f"metadata-{task_id[:8]}", daemon=True).start()
