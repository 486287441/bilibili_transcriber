"""Load .env settings and validate required keys before the main pipeline runs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent
COOKIES_DIR = _PROJECT_ROOT / "cookies"
load_dotenv(_PROJECT_ROOT / ".env", encoding="utf-8")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro").strip()

FEISHU_WIKI_SPACE_ID = os.getenv("FEISHU_WIKI_SPACE_ID", "").strip()
FEISHU_WIKI_PARENT_NODE_TOKEN = os.getenv("FEISHU_WIKI_PARENT_NODE_TOKEN", "").strip()

# yt-dlp Netscape cookie files (optional; only used when the file exists).
# Export from browser extensions such as "Get cookies.txt LOCALLY".
YTDLP_COOKIE_FILE_BILIBILI = os.getenv("YTDLP_COOKIE_FILE_BILIBILI", "").strip()
YTDLP_COOKIE_FILE_YOUTUBE = os.getenv("YTDLP_COOKIE_FILE_YOUTUBE", "").strip()
YTDLP_COOKIE_FILE_DOUYIN = os.getenv("YTDLP_COOKIE_FILE_DOUYIN", "").strip()
YTDLP_COOKIE_FILE = os.getenv("YTDLP_COOKIE_FILE", "").strip()

YTDLP_COOKIES_FROM_BROWSER = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()
YTDLP_COOKIES_FROM_BROWSER_BILIBILI = os.getenv(
    "YTDLP_COOKIES_FROM_BROWSER_BILIBILI", ""
).strip()
YTDLP_COOKIES_FROM_BROWSER_YOUTUBE = os.getenv(
    "YTDLP_COOKIES_FROM_BROWSER_YOUTUBE", ""
).strip()
YTDLP_COOKIES_FROM_BROWSER_DOUYIN = os.getenv(
    "YTDLP_COOKIES_FROM_BROWSER_DOUYIN", ""
).strip()

YTDLP_SOCKET_TIMEOUT = int(os.getenv("YTDLP_SOCKET_TIMEOUT", "120") or "120")
YTDLP_RETRIES = int(os.getenv("YTDLP_RETRIES", "10") or "10")
YTDLP_FRAGMENT_RETRIES = int(os.getenv("YTDLP_FRAGMENT_RETRIES", "10") or "10")
YTDLP_NETWORK_RETRIES = int(os.getenv("YTDLP_NETWORK_RETRIES", "3") or "3")

# YouTube: refresh cookies from running Chrome via CDP (no need to close the browser).
# Modes: on_failure (default) | always | off
YTDLP_CDP_REFRESH_YOUTUBE = os.getenv("YTDLP_CDP_REFRESH_YOUTUBE", "on_failure").strip().lower()


def youtube_cdp_refresh_on_failure() -> bool:
    mode = YTDLP_CDP_REFRESH_YOUTUBE
    return mode not in ("0", "false", "off", "no", "disabled")


def youtube_cdp_refresh_before_download() -> bool:
    return YTDLP_CDP_REFRESH_YOUTUBE in ("always", "1", "true", "yes", "on")


def _parse_browser_spec(spec: str) -> tuple[str, ...] | None:
    """Parse 'chrome' or 'chrome:Default' into yt-dlp cookiesfrombrowser tuple."""
    text = (spec or "").strip()
    if not text:
        return None
    browser, _, profile = text.partition(":")
    browser = browser.strip().lower()
    if not browser:
        return None
    profile = profile.strip()
    return (browser, profile) if profile else (browser,)


def resolve_cookies_from_browser(site: str) -> tuple[str, ...] | None:
    """Return yt-dlp cookiesfrombrowser tuple for *site*, with global fallback."""
    site_specs = {
        "bilibili": YTDLP_COOKIES_FROM_BROWSER_BILIBILI,
        "youtube": YTDLP_COOKIES_FROM_BROWSER_YOUTUBE,
        "douyin": YTDLP_COOKIES_FROM_BROWSER_DOUYIN,
    }
    parsed = _parse_browser_spec(site_specs.get(site, ""))
    if parsed:
        return parsed
    return _parse_browser_spec(YTDLP_COOKIES_FROM_BROWSER)


def has_ytdlp_auth(site: str) -> bool:
    """True when a cookie file or cookies-from-browser source is configured."""
    return bool(resolve_ytdlp_cookie_file(site) or resolve_cookies_from_browser(site))


def resolve_ytdlp_cookie_file(site: str) -> str | None:
    """Return an existing cookie file path for *site*, with generic fallback."""
    site_defaults: dict[str, tuple[str, str]] = {
        "bilibili": ("YTDLP_COOKIE_FILE_BILIBILI", "www.bilibili.com_cookies.txt"),
        "youtube": ("YTDLP_COOKIE_FILE_YOUTUBE", "www.youtube.com_cookies.txt"),
        "douyin": ("YTDLP_COOKIE_FILE_DOUYIN", "www.douyin.com_cookies.txt"),
    }
    env_name, default_name = site_defaults.get(site, ("", ""))
    explicit = (os.getenv(env_name, "") if env_name else "").strip()
    if not explicit and env_name:
        explicit = globals().get(env_name, "") or ""

    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if default_name:
        candidates.append(COOKIES_DIR / default_name)
        candidates.append(_PROJECT_ROOT / default_name)
    if YTDLP_COOKIE_FILE:
        candidates.append(Path(YTDLP_COOKIE_FILE))
        if not Path(YTDLP_COOKIE_FILE).is_absolute():
            candidates.append(COOKIES_DIR / YTDLP_COOKIE_FILE)

    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else _PROJECT_ROOT / candidate
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        if path.is_file():
            return str(path)
    return None

_REQUIRED: tuple[tuple[str, str], ...] = (
    ("DEEPSEEK_API_KEY", DEEPSEEK_API_KEY),
    ("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
    ("DEEPSEEK_MODEL", DEEPSEEK_MODEL),
    ("FEISHU_WIKI_SPACE_ID", FEISHU_WIKI_SPACE_ID),
    ("FEISHU_WIKI_PARENT_NODE_TOKEN", FEISHU_WIKI_PARENT_NODE_TOKEN),
)

_LABELS: dict[str, str] = {
    "DEEPSEEK_API_KEY": "DeepSeek API 密钥",
    "DEEPSEEK_BASE_URL": "DeepSeek API 地址",
    "DEEPSEEK_MODEL": "DeepSeek 模型名",
    "FEISHU_WIKI_SPACE_ID": "飞书知识库 space_id",
    "FEISHU_WIKI_PARENT_NODE_TOKEN": "飞书知识库父节点 parent_node_token",
}


def validate() -> None:
    """Exit with a Chinese error message when required configuration is missing."""
    missing = [name for name, value in _REQUIRED if not value]
    if not missing:
        return

    lines = [
        "配置不完整，无法启动。请在项目根目录 .env 中补全以下项：",
        "",
    ]
    for name in missing:
        label = _LABELS.get(name, name)
        lines.append(f"  - {name}（{label}）")
    lines.extend(
        [
            "",
            "可参考 .env.example；飞书 wiki 参数可在目标知识库 URL 或通过",
            "  lark-cli wiki +space-list / +node-list 查询。",
        ]
    )
    print("\n".join(lines), file=sys.stderr)
    sys.exit(1)
