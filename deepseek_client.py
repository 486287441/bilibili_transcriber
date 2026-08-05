"""DeepSeek API client for transcript polish and summary."""

from __future__ import annotations

from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError

import config
from prompts import (
    FOLLOWUP_SYSTEM,
    build_followup_article_message,
    build_polish_user_message,
    render_polish_system,
)
from server.settings_store import (
    get_deepseek_model,
    get_polish_prompt_template,
    get_recommendation_criteria,
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


def polish_and_summarize(raw_text: str) -> str:
    """Polish transcript and append a summary section; returns Markdown."""
    text = (raw_text or "").strip()
    if not text:
        raise DeepSeekError("转写文本为空，无法调用 DeepSeek。")

    system_prompt = render_polish_system(
        get_polish_prompt_template(),
        get_recommendation_criteria(),
    )
    try:
        response = _client().chat.completions.create(
            model=get_deepseek_model(),
            temperature=_TEMPERATURE,
            messages=[
                {"role": "system", "content": system_prompt},
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

    from server.recommendation import normalize_recommendation

    return normalize_recommendation(content)


def evaluate_recommendation(article_text: str) -> str:
    """Evaluate an existing polished article without re-running the full polish flow."""
    text = (article_text or "").strip()
    if not text:
        raise DeepSeekError("整理后文稿为空，无法评估。")

    recommendation_criteria = get_recommendation_criteria()
    system = f"""你是视频注意力守门助手。请根据整理后的视频文稿，分别评估内容本身是否值得了解，以及用户读完总结后原片还有多少增量价值。

{recommendation_criteria}

只输出一个完整的「# 推荐指数」Markdown 章节，不要复述文章，不要输出思考过程。"""
    try:
        from server.recommendation import remove_recommendation

        response = _client().chat.completions.create(
            model=get_deepseek_model(),
            temperature=0.2,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": build_followup_article_message(remove_recommendation(text)),
                },
            ],
        )
    except DeepSeekError:
        raise
    except Exception as exc:
        raise _wrap_api_error(exc) from exc

    choice = response.choices[0] if response.choices else None
    content = choice.message.content if choice and choice.message else None
    if not content or not content.strip():
        raise DeepSeekError("DeepSeek 返回的推荐评估为空，请重试。")

    from server.recommendation import normalize_recommendation, parse_recommendation

    result = content.strip()
    if not result.startswith("# 推荐指数"):
        result = f"# 推荐指数\n{result}"
    if not parse_recommendation(result):
        raise DeepSeekError("DeepSeek 返回的推荐评估格式不完整，请重试。")
    return normalize_recommendation(result)


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
            extra_body={"thinking": {"type": "enabled"}},
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
