"""Article length, DeepSeek token count, API cost hint, and reading time."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from tokenizers import Tokenizer

# Silent reading speed for polished Chinese prose (chars/min, excluding whitespace).
_READING_CHARS_PER_MIN = 350

_TOKENIZER_DIR = Path(__file__).resolve().parent / "deepseek_v3_tokenizer"
_TOKENIZER_JSON = _TOKENIZER_DIR / "tokenizer.json"

# DeepSeek 官方标价：元 / 百万 tokens（输入·缓存未命中 / 输出）。
_FLASH_INPUT_YUAN_PER_M = 1.0
_PRO_INPUT_YUAN_PER_M = 3.0
_FLASH_OUTPUT_YUAN_PER_M = 2.0
_PRO_OUTPUT_YUAN_PER_M = 6.0

# Claude 3 Opus 官方标价：美元 / 百万 tokens（Base Input / Output）。
_CLAUDE_OPUS_INPUT_USD_PER_M = 15.0
_CLAUDE_OPUS_OUTPUT_USD_PER_M = 75.0

# 简短回复：约为输入 5%，不少于 200、不超过 512 tokens。
_BRIEF_REPLY_MIN_TOKENS = 200
_BRIEF_REPLY_MAX_TOKENS = 512
_BRIEF_REPLY_INPUT_RATIO = 0.05


@lru_cache(maxsize=1)
def _get_tokenizer() -> Tokenizer:
    if not _TOKENIZER_JSON.is_file():
        raise FileNotFoundError(
            f"未找到 DeepSeek 词表文件：{_TOKENIZER_JSON}。"
            "请确认 deepseek_v3_tokenizer 目录完整。"
        )
    return Tokenizer.from_file(str(_TOKENIZER_JSON))


def article_char_count(text: str) -> int:
    """Count non-whitespace characters (中文「字数」常用口径)."""
    return sum(1 for ch in text if not ch.isspace())


def count_copy_tokens(text: str) -> int:
    """Token count via deepseek_v3_tokenizer (same vocab as DeepSeek API)."""
    if not text.strip():
        return 0
    return len(_get_tokenizer().encode(text).ids)


def token_cost(tokens: int, price_per_million: float) -> float:
    return tokens / 1_000_000 * price_per_million


def estimate_brief_reply_tokens(input_tokens: int) -> int:
    """Heuristic output size for one short assistant reply."""
    if input_tokens <= 0:
        return 0
    scaled = round(input_tokens * _BRIEF_REPLY_INPUT_RATIO)
    return min(_BRIEF_REPLY_MAX_TOKENS, max(_BRIEF_REPLY_MIN_TOKENS, scaled))


def round_trip_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    input_per_m: float,
    output_per_m: float,
) -> float:
    return token_cost(input_tokens, input_per_m) + token_cost(output_tokens, output_per_m)


def format_yuan(yuan: float) -> str:
    if yuan <= 0:
        return "0 元"
    if yuan >= 1:
        return f"约 {yuan:.2f} 元"
    if yuan >= 0.01:
        return f"约 {yuan:.3f} 元"
    return f"约 {yuan:.4f} 元"


def format_usd(usd: float) -> str:
    if usd <= 0:
        return "$0"
    if usd >= 1:
        return f"约 ${usd:.2f}"
    if usd >= 0.01:
        return f"约 ${usd:.3f}"
    return f"约 ${usd:.4f}"


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
    tokens = count_copy_tokens(text)
    reply_tokens = estimate_brief_reply_tokens(tokens)
    reading = format_reading_duration(chars)
    flash_input = format_yuan(token_cost(tokens, _FLASH_INPUT_YUAN_PER_M))
    pro_input = format_yuan(token_cost(tokens, _PRO_INPUT_YUAN_PER_M))
    claude_input = format_usd(token_cost(tokens, _CLAUDE_OPUS_INPUT_USD_PER_M))
    flash_total = format_yuan(
        round_trip_cost(
            tokens,
            reply_tokens,
            input_per_m=_FLASH_INPUT_YUAN_PER_M,
            output_per_m=_FLASH_OUTPUT_YUAN_PER_M,
        )
    )
    pro_total = format_yuan(
        round_trip_cost(
            tokens,
            reply_tokens,
            input_per_m=_PRO_INPUT_YUAN_PER_M,
            output_per_m=_PRO_OUTPUT_YUAN_PER_M,
        )
    )
    claude_total = format_usd(
        round_trip_cost(
            tokens,
            reply_tokens,
            input_per_m=_CLAUDE_OPUS_INPUT_USD_PER_M,
            output_per_m=_CLAUDE_OPUS_OUTPUT_USD_PER_M,
        )
    )
    return (
        "## 阅读与 Token 参考\n\n"
        f"- **全文字数：** {chars:,} 字（不计空白）\n"
        f"- **复制给 AI 约消耗：** {tokens:,} tokens"
        "（DeepSeek V3 词表计数；Claude 实际 token 数可能略有差异）\n"
        f"- **预计 API 费用（仅输入，缓存未命中）：** "
        f"deepseek-v4-flash {flash_input}；"
        f"deepseek-v4-pro {pro_input}；"
        f"Claude 3 Opus {claude_input}"
        "（DeepSeek 输入 Flash 1 元 / Pro 3 元每百万 tokens；"
        f"Claude 输入 ${_CLAUDE_OPUS_INPUT_USD_PER_M:g}/MTok）\n"
        f"- **预计总价（输入 + 约 {reply_tokens:,} tokens 简短回复）：** "
        f"deepseek-v4-flash {flash_total}；"
        f"deepseek-v4-pro {pro_total}；"
        f"Claude 3 Opus {claude_total}"
        "（DeepSeek 输出 Flash 2 元 / Pro 6 元每百万 tokens；"
        f"Claude 输出 ${_CLAUDE_OPUS_OUTPUT_USD_PER_M:g}/MTok；"
        f"回复按输入 {_BRIEF_REPLY_INPUT_RATIO:.0%} 估算，"
        f"{_BRIEF_REPLY_MIN_TOKENS}～{_BRIEF_REPLY_MAX_TOKENS} tokens）\n"
        f"- **阅读耗时：** {reading}（按每分钟约 {_READING_CHARS_PER_MIN} 字估算）\n"
    )
