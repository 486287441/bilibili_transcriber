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

# Claude Opus 4.8：定价表 Base Input / Output（美元每百万 tokens），折算人民币用参考汇率。
_USD_TO_CNY = 7.25
_CLAUDE_OPUS_48_INPUT_USD_PER_M = 5.0  # Base Input Tokens
_CLAUDE_OPUS_48_OUTPUT_USD_PER_M = 25.0  # Output Tokens
_CLAUDE_OPUS_48_INPUT_YUAN_PER_M = _CLAUDE_OPUS_48_INPUT_USD_PER_M * _USD_TO_CNY
_CLAUDE_OPUS_48_OUTPUT_YUAN_PER_M = _CLAUDE_OPUS_48_OUTPUT_USD_PER_M * _USD_TO_CNY

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


def _pricing_table_row(
    model: str,
    input_tokens: int,
    reply_tokens: int,
    *,
    input_yuan_per_m: float,
    output_yuan_per_m: float,
) -> str:
    input_cost = format_yuan(token_cost(input_tokens, input_yuan_per_m))
    total_cost = format_yuan(
        round_trip_cost(
            input_tokens,
            reply_tokens,
            input_per_m=input_yuan_per_m,
            output_per_m=output_yuan_per_m,
        )
    )
    return f"| {model} | {input_cost} | {total_cost} |"


def format_article_stats_block(text: str) -> str:
    """Markdown section appended to Feishu video documents."""
    chars = article_char_count(text)
    tokens = count_copy_tokens(text)
    reply_tokens = estimate_brief_reply_tokens(tokens)
    reading = format_reading_duration(chars)
    rows = [
        _pricing_table_row(
            "deepseek-v4-flash",
            tokens,
            reply_tokens,
            input_yuan_per_m=_FLASH_INPUT_YUAN_PER_M,
            output_yuan_per_m=_FLASH_OUTPUT_YUAN_PER_M,
        ),
        _pricing_table_row(
            "deepseek-v4-pro",
            tokens,
            reply_tokens,
            input_yuan_per_m=_PRO_INPUT_YUAN_PER_M,
            output_yuan_per_m=_PRO_OUTPUT_YUAN_PER_M,
        ),
        _pricing_table_row(
            "Claude Opus 4.8",
            tokens,
            reply_tokens,
            input_yuan_per_m=_CLAUDE_OPUS_48_INPUT_YUAN_PER_M,
            output_yuan_per_m=_CLAUDE_OPUS_48_OUTPUT_YUAN_PER_M,
        ),
    ]
    table = "\n".join(
        [
            "| 模型 | 仅输入 | 输入 + 简短回复 |",
            "| --- | --- | --- |",
            *rows,
        ]
    )
    return (
        "## 阅读与 Token 参考\n\n"
        f"- **全文字数：** {chars:,} 字（不计空白）\n"
        f"- **复制给 AI 约消耗：** {tokens:,} tokens"
        "（DeepSeek V3 词表计数；Claude 实际 token 数可能略有差异）\n"
        f"- **阅读耗时：** {reading}（按每分钟约 {_READING_CHARS_PER_MIN} 字估算）\n\n"
        "### 预计 API 费用（人民币）\n\n"
        f"{table}\n\n"
        "说明：价格为估算值；DeepSeek 按人民币标价（输入按缓存未命中）。"
        "Claude Opus 4.8 按定价表 Base Input / Output "
        f"（${_CLAUDE_OPUS_48_INPUT_USD_PER_M:g} / ${_CLAUDE_OPUS_48_OUTPUT_USD_PER_M:g} "
        f"每百万 tokens，汇率 {_USD_TO_CNY} 折算人民币）。"
        f"「简短回复」按约 {reply_tokens:,} tokens 计"
        f"（约为输入 {_BRIEF_REPLY_INPUT_RATIO:.0%}，"
        f"{_BRIEF_REPLY_MIN_TOKENS}～{_BRIEF_REPLY_MAX_TOKENS} tokens）。\n"
    )
