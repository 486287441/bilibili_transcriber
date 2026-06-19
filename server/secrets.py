"""Non-sensitive masks for whether .env secrets are configured."""

from __future__ import annotations

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
