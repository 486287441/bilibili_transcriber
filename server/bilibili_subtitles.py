"""Bilibili CC subtitle discovery and download through the existing yt-dlp auth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from server.transcript_routes import (
    TranscriptSegment,
    choose_subtitle_track,
    normalize_segments,
    parse_subtitle_payload,
)


@dataclass
class BilibiliSubtitleResult:
    segments: list[TranscriptSegment] = field(default_factory=list)
    title: str | None = None
    webpage_url: str | None = None
    duration_sec: float | None = None
    language: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return bool(self.segments)


def _unwrap_video_info(info: Mapping[str, Any] | None) -> Mapping[str, Any]:
    current: Mapping[str, Any] = info or {}
    seen = 0
    while current.get("_type") in {"playlist", "multi_video"} and seen < 4:
        entries = current.get("entries") or []
        first = next((entry for entry in entries if isinstance(entry, Mapping)), None)
        if not first:
            break
        current = first
        seen += 1
    return current


def _meta_from_info(info: Mapping[str, Any], original_url: str) -> dict[str, Any]:
    duration = info.get("duration")
    try:
        duration_sec = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_sec = None
    return {
        "title": str(info.get("title") or "未命名视频").strip(),
        "webpage_url": str(info.get("webpage_url") or original_url).strip(),
        "duration_sec": duration_sec,
    }


def fetch_bilibili_subtitles(url: str) -> BilibiliSubtitleResult:
    """Return the preferred Bilibili CC track, or an empty successful probe.

    yt-dlp's Bilibili extractor only populates ``subtitles`` when
    ``writesubtitles``/``listsubtitles`` is enabled.  The extractor also always
    exposes danmaku XML, which ``choose_subtitle_track`` deliberately ignores.
    """

    from bilibili_transcriber import _YTDLP_LOCK, _ydl_opts_for_site, yt_dlp

    opts = _ydl_opts_for_site("bilibili")
    opts.update(
        {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "noplaylist": True,
        }
    )
    with _YTDLP_LOCK:
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw_info = ydl.extract_info(url, download=False)
            info = _unwrap_video_info(raw_info if isinstance(raw_info, Mapping) else {})
            meta = _meta_from_info(info, url)
            subtitles = info.get("subtitles")
            selected = choose_subtitle_track(
                subtitles if isinstance(subtitles, Mapping) else None
            )
            available = sorted(
                str(language)
                for language in (subtitles or {})
                if str(language).lower() != "danmaku"
            )
            if not selected:
                return BilibiliSubtitleResult(
                    **meta,
                    diagnostics={
                        "platform_subtitle_found": False,
                        "available_subtitle_languages": available,
                    },
                )

            language, track = selected
            payload = track.get("data")
            if payload is None and track.get("url"):
                with ydl.urlopen(str(track["url"])) as response:
                    payload = response.read()
            segments = normalize_segments(
                parse_subtitle_payload(
                    payload or "",
                    ext=str(track.get("ext") or ""),
                    source="subtitle",
                )
            )
            return BilibiliSubtitleResult(
                segments=segments,
                language=language,
                **meta,
                diagnostics={
                    "platform_subtitle_found": bool(segments),
                    "subtitle_language": language,
                    "subtitle_format": str(track.get("ext") or "unknown"),
                    "subtitle_segment_count": len(segments),
                    "available_subtitle_languages": available,
                },
            )
