"""Focused tests for the compact article reading statistics block."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from text_stats import format_article_stats_block


def test_stats_only_show_length_and_reading_time() -> None:
    block = format_article_stats_block("你好 世界")
    assert block.startswith("## 阅读参考\n")
    assert "**全文字数：** 4 字" in block
    assert "**阅读耗时：**" in block
    assert "token" not in block.lower()
    assert "费用" not in block
    assert "模型" not in block


if __name__ == "__main__":
    test_stats_only_show_length_and_reading_time()
    print("text stats tests PASS")
