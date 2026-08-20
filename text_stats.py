"""Article length and reading-time helpers."""

from __future__ import annotations

# Silent reading speed for polished Chinese prose (chars/min, excluding whitespace).
_READING_CHARS_PER_MIN = 350


def article_char_count(text: str) -> int:
    """Count non-whitespace characters (中文「字数」常用口径)."""
    return sum(1 for ch in text if not ch.isspace())


def format_reading_duration(char_count: int) -> str:
    """Human-readable reading time from character count."""
    if char_count <= 0:
        return "—"
    total_seconds = max(1, round(char_count / _READING_CHARS_PER_MIN * 60))
    if total_seconds < 60:
        return f"约 {total_seconds} 秒"
    minutes, seconds = divmod(total_seconds, 60)
    if seconds == 0:
        return f"约 {minutes} 分钟"
    if minutes < 10:
        return f"约 {minutes} 分 {seconds} 秒"
    return f"约 {minutes} 分钟"


def format_article_stats_block(text: str) -> str:
    """Markdown section appended to Feishu video documents."""
    chars = article_char_count(text)
    reading = format_reading_duration(chars)
    return (
        "## 阅读参考\n\n"
        f"- **全文字数：** {chars:,} 字（不计空白）\n"
        f"- **阅读耗时：** {reading}（按每分钟约 {_READING_CHARS_PER_MIN} 字估算）\n"
    )
