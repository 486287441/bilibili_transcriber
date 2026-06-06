"""Detect and extract supported video URLs (Bilibili, YouTube, Douyin, …)."""

from __future__ import annotations

import re

# Order matters: earlier patterns win when multiple could match.
_VIDEO_URL_PATTERNS: tuple[str, ...] = (
    # Bilibili
    r"https?://(?:www\.)?bilibili\.com/video/[a-zA-Z0-9][^\s]*",
    r"https?://b23\.tv/[a-zA-Z0-9][^\s]*",
    # YouTube
    r"https?://(?:www\.|m\.)?youtube\.com/watch\?[^\s]+",
    r"https?://(?:www\.|m\.)?youtube\.com/shorts/[a-zA-Z0-9_-]+[^\s]*",
    r"https?://youtu\.be/[a-zA-Z0-9_-]+[^\s]*",
    # Douyin
    r"https?://(?:www\.)?douyin\.com/(?:video|note)/[0-9]+[^\s]*",
    r"https?://v\.douyin\.com/[a-zA-Z0-9/_-]+[^\s]*",
    r"https?://(?:www\.)?iesdouyin\.com/share/(?:video|note)/[0-9]+[^\s]*",
)

_VIDEO_URL_RE = re.compile(
    "|".join(f"({pattern})" for pattern in _VIDEO_URL_PATTERNS),
    re.IGNORECASE,
)

_SITE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bilibili", ("bilibili.com", "b23.tv")),
    ("youtube", ("youtube.com", "youtu.be")),
    ("douyin", ("douyin.com", "iesdouyin.com")),
)

SUPPORTED_SITES_LABEL = "B站 / YouTube / 抖音"


def extract_video_url(text: str) -> str | None:
    """Return the first supported video URL found in *text*, or None."""
    match = _VIDEO_URL_RE.search((text or "").strip())
    if not match:
        return None
    return next((group for group in match.groups() if group), None)


def detect_site(url: str) -> str:
    """Return site key: bilibili | youtube | douyin | generic."""
    lowered = (url or "").lower()
    for site, hints in _SITE_HINTS:
        if any(hint in lowered for hint in hints):
            return site
    return "generic"


def is_supported_video_url(text: str) -> bool:
    return extract_video_url(text) is not None


def is_bilibili_url(text: str) -> bool:
    """Backward-compatible check; True only for Bilibili URLs."""
    url = extract_video_url(text)
    return url is not None and detect_site(url) == "bilibili"


# Backward-compatible alias used by telegram_bot / dual_entry_service.
def extract_bilibili_url(text: str) -> str | None:
    return extract_video_url(text)
