"""Load .env settings and validate required keys before the main pipeline runs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env", encoding="utf-8")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()

FEISHU_WIKI_SPACE_ID = os.getenv("FEISHU_WIKI_SPACE_ID", "").strip()
FEISHU_WIKI_PARENT_NODE_TOKEN = os.getenv("FEISHU_WIKI_PARENT_NODE_TOKEN", "").strip()

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
