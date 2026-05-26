"""DeepSeek API client for transcript polish and summary."""

from __future__ import annotations

from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError

import config
from prompts import POLISH_AND_SUMMARY_SYSTEM, build_polish_user_message

_TIMEOUT_SECONDS = 120.0
_TEMPERATURE = 0.3


class DeepSeekError(Exception):
    """Readable failure for logging and M05 fallback."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


def _client() -> OpenAI:
    return OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=_TIMEOUT_SECONDS,
    )


def _wrap_api_error(exc: BaseException) -> DeepSeekError:
    if isinstance(exc, AuthenticationError):
        return DeepSeekError(
            "DeepSeek 鉴权失败：请检查 .env 中的 DEEPSEEK_API_KEY 是否正确或已失效。",
            cause=exc,
        )
    if isinstance(exc, APITimeoutError):
        return DeepSeekError(
            f"DeepSeek 请求超时（>{int(_TIMEOUT_SECONDS)} 秒），请稍后重试或缩短转写文本。",
            cause=exc,
        )
    if isinstance(exc, RateLimitError):
        return DeepSeekError("DeepSeek 请求过于频繁或额度不足，请稍后重试。", cause=exc)
    if isinstance(exc, APIConnectionError):
        return DeepSeekError("无法连接 DeepSeek API，请检查网络与 DEEPSEEK_BASE_URL。", cause=exc)
    if isinstance(exc, APIStatusError):
        return DeepSeekError(
            f"DeepSeek API 返回错误（HTTP {exc.status_code}）：{exc.message}",
            cause=exc,
        )
    return DeepSeekError(f"DeepSeek 调用失败：{exc}", cause=exc)


def polish_and_summarize(raw_text: str) -> str:
    """Polish transcript and append a summary section; returns Markdown."""
    text = (raw_text or "").strip()
    if not text:
        raise DeepSeekError("转写文本为空，无法调用 DeepSeek。")

    try:
        response = _client().chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            temperature=_TEMPERATURE,
            messages=[
                {"role": "system", "content": POLISH_AND_SUMMARY_SYSTEM},
                {"role": "user", "content": build_polish_user_message(text)},
            ],
        )
    except DeepSeekError:
        raise
    except Exception as exc:
        raise _wrap_api_error(exc) from exc

    choice = response.choices[0] if response.choices else None
    content = choice.message.content if choice and choice.message else None
    if not content or not content.strip():
        raise DeepSeekError("DeepSeek 返回内容为空，请重试。")

    return content.strip()
