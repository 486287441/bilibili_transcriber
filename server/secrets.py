"""Non-sensitive masks for whether .env secrets are configured."""

from __future__ import annotations

import os

from dotenv import set_key

import config


def get_secrets_mask() -> dict:
    return {
        "deepseek_configured": bool(config.DEEPSEEK_API_KEY),
        "feishu_configured": bool(
            config.FEISHU_WIKI_SPACE_ID and config.FEISHU_WIKI_PARENT_NODE_TOKEN
        ),
        "yt_dlp_cookies": {
            "bilibili": config.has_ytdlp_auth("bilibili"),
            "youtube": config.has_ytdlp_auth("youtube"),
            "douyin": config.has_ytdlp_auth("douyin"),
        },
    }


def save_deepseek_api_key(api_key: str) -> None:
    """Persist the key locally without ever returning or logging its value."""
    value = (api_key or "").strip()
    if not value:
        raise ValueError("DeepSeek API Key 不能为空")
    env_path = config.PROJECT_ROOT / ".env"
    set_key(str(env_path), "DEEPSEEK_API_KEY", value, quote_mode="always")
    os.environ["DEEPSEEK_API_KEY"] = value
    config.DEEPSEEK_API_KEY = value
