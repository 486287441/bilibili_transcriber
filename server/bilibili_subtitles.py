"""Bilibili CC subtitle discovery and download through the existing yt-dlp auth."""

from __future__ import annotations

import json
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


class BilibiliSubtitleAuthError(RuntimeError):
    """The configured Bilibili session is missing or no longer logged in."""


def _bilibili_login_state(ydl) -> bool | None:
    """Ask Bilibili whether yt-dlp's current cookie jar is authenticated."""

    try:
        with ydl.urlopen("https://api.bilibili.com/x/web-interface/nav") as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping) or "isLogin" not in data:
        return None
    return bool(data.get("isLogin"))


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
                login_state = _bilibili_login_state(ydl)
                if login_state is False:
                    raise BilibiliSubtitleAuthError(
                        "B站字幕鉴权失败：Cookie 未配置、已过期或登录会话已失效"
                    )
                return BilibiliSubtitleResult(
                    **meta,
                    diagnostics={
                        "platform_subtitle_found": False,
                        "subtitle_auth_status": (
                            "authenticated" if login_state is True else "unknown"
                        ),
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
                    "subtitle_auth_status": "usable",
                    "subtitle_language": language,
                    "subtitle_format": str(track.get("ext") or "unknown"),
                    "subtitle_segment_count": len(segments),
                    "available_subtitle_languages": available,
                },
            )
