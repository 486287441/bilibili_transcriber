"""DeepSeek API client for transcript polish and summary."""

from __future__ import annotations

import time
from typing import Any, Callable

from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError

import config
from prompts import (
    FOLLOWUP_SYSTEM,
    build_followup_article_message,
    build_polish_user_message,
    render_polish_system,
)
from transcript_processing import format_transcript_locally, remove_asr_punctuation
from server.settings_store import (
    get_deepseek_model,
    get_polish_prompt_template,
    get_transcript_correction_prompt,
    is_first_stage_enabled,
    is_second_stage_enabled,
)

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


def _completion(
    system_prompt: str,
    user_message: str,
    *,
    temperature: float = _TEMPERATURE,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Run one DeepSeek completion, streaming only when progress is observed."""
    request = {
        "model": get_deepseek_model(),
        "temperature": temperature,
        "extra_body": {"thinking": {"type": "disabled"}},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    try:
        if progress_callback is None:
            response = _client().chat.completions.create(**request)
        else:
            response = _client().chat.completions.create(
                **request,
                stream=True,
                stream_options={"include_usage": True},
            )
    except DeepSeekError:
        raise
    except Exception as exc:
        raise _wrap_api_error(exc) from exc

    if progress_callback is not None:
        parts: list[str] = []
        output_chars = 0
        completion_tokens: int | None = None
        started = time.monotonic()
        last_emit = 0.0
        try:
            for chunk in response:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    completion_tokens = getattr(usage, "completion_tokens", None)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None) if delta else None
                if not piece:
                    continue
                parts.append(piece)
                output_chars += len(piece)
                now = time.monotonic()
                if now - last_emit >= 0.5:
                    last_emit = now
                    try:
                        progress_callback(
                            {
                                "output_chars": output_chars,
                                "elapsed_seconds": now - started,
                                "done": False,
                            }
                        )
                    except Exception:
                        pass
        except Exception as exc:
            raise _wrap_api_error(exc) from exc
        content = "".join(parts)
        try:
            progress_callback(
                {
                    "output_chars": output_chars,
                    "completion_tokens": completion_tokens,
                    "elapsed_seconds": time.monotonic() - started,
                    "done": True,
                }
            )
        except Exception:
            pass
    else:
        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice and choice.message else None
    if not content or not content.strip():
        raise DeepSeekError("DeepSeek 返回内容为空，请重试。")
    return content.strip()


def correct_transcript(raw_text: str, *, progress_callback=None) -> str:
    """Stage 1: strip ASR punctuation, then conservatively correct the transcript."""
    text = remove_asr_punctuation(raw_text).strip()
    if not text:
        raise DeepSeekError("转写文本为空，无法调用 DeepSeek。")
    return _completion(
        get_transcript_correction_prompt(),
        text,
        progress_callback=progress_callback,
    )


def organize_transcript(trusted_text: str, *, progress_callback=None) -> str:
    """Stage 2: build the summary, TOC, and chapter structure."""
    text = (trusted_text or "").strip()
    if not text:
        raise DeepSeekError("可信逐字稿为空，无法调用 DeepSeek。")

    system_prompt = render_polish_system(get_polish_prompt_template())
    return _completion(
        system_prompt,
        build_polish_user_message(text),
        progress_callback=progress_callback,
    )


def process_transcript(
    raw_text: str,
    *,
    input_is_trusted: bool = False,
) -> tuple[str, str]:
    """Run the strict two-stage flow; return trusted text and article Markdown."""
    first_stage_enabled = is_first_stage_enabled()
    if input_is_trusted:
        trusted_text = (raw_text or "").strip()
    elif first_stage_enabled:
        trusted_text = correct_transcript(raw_text)
    else:
        trusted_text = format_transcript_locally(raw_text)
    article = (
        organize_transcript(trusted_text)
        if first_stage_enabled and is_second_stage_enabled()
        else trusted_text
    )
    return trusted_text, article


def polish_and_summarize(
    raw_text: str,
    *,
    input_is_trusted: bool = False,
) -> str:
    """Backward-compatible article-only facade for the strict polish flow."""
    _trusted_text, article = process_transcript(
        raw_text,
        input_is_trusted=input_is_trusted,
    )
    return article


def _build_chat_turns(article_text: str, messages: list[dict[str, str]]) -> list[dict[str, str]]:
    text = (article_text or "").strip()
    if not text:
        raise DeepSeekError("原文为空，无法追问。")

    turns: list[dict[str, str]] = [
        {"role": "system", "content": FOLLOWUP_SYSTEM},
        {"role": "user", "content": build_followup_article_message(text)},
    ]
    for msg in messages:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        turns.append({"role": role, "content": content})

    if not any(m["role"] == "user" for m in turns[2:]):
        raise DeepSeekError("请提供至少一条追问。")
    return turns


def _extract_reasoning_delta(delta: object) -> str:
    rc = getattr(delta, "reasoning_content", None)
    if rc:
        return rc
    extra = getattr(delta, "model_extra", None) or {}
    if isinstance(extra, dict):
        rc = extra.get("reasoning_content")
        if rc:
            return rc
    return ""


def stream_chat_about_article(article_text: str, messages: list[dict[str, str]]):
    """Stream follow-up chat; yields dict events: thinking, content, done, error."""
    turns = _build_chat_turns(article_text, messages)
    reasoning_parts: list[str] = []
    content_parts: list[str] = []

    try:
        stream = _client().chat.completions.create(
            model=get_deepseek_model(),
            temperature=_TEMPERATURE,
            messages=turns,
            stream=True,
            extra_body={"thinking": {"type": "disabled"}},
        )
    except DeepSeekError:
        raise
    except Exception as exc:
        raise _wrap_api_error(exc) from exc

    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if not delta:
                continue

            rc = _extract_reasoning_delta(delta)
            if rc:
                reasoning_parts.append(rc)
                yield {"type": "thinking", "delta": rc}

            piece = getattr(delta, "content", None) or ""
            if piece:
                content_parts.append(piece)
                yield {"type": "content", "delta": piece}
    except Exception as exc:
        raise _wrap_api_error(exc) from exc

    reply = "".join(content_parts).strip()
    thinking = "".join(reasoning_parts).strip()
    if not reply:
        raise DeepSeekError("DeepSeek 返回内容为空，请重试。")

    yield {"type": "done", "thinking": thinking, "reply": reply}


def chat_about_article(article_text: str, messages: list[dict[str, str]]) -> str:
    """Answer questions about an article; article is injected server-side only."""
    reply = ""
    for event in stream_chat_about_article(article_text, messages):
        if event.get("type") == "done":
            reply = event.get("reply") or ""
    return reply
