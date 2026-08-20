"""History REST API (M07)."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.history_service import history_service
from server.queue_service import DuplicateTaskError, queue_service

router = APIRouter(prefix="/api")


class ReprocessBody(BaseModel):
    mode: str = Field(default="full", pattern="^(full|polish_only|transcribe_and_polish)$")
    requested_route: Literal["auto", "subtitle", "ocr", "asr"] = "auto"


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8000)


class ChatBody(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


@router.get("/history")
async def list_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> dict[str, Any]:
    return history_service.list(page=page, page_size=page_size, status=status, query=q)


@router.get("/history/{history_id}")
async def get_history_item(history_id: str) -> dict[str, Any]:
    try:
        return history_service.get(history_id).to_dict(include_text=True)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "历史记录不存在", "code": "NOT_FOUND"},
        ) from exc


@router.delete("/history/{history_id}")
async def delete_history_item(history_id: str) -> dict[str, str]:
    try:
        history_service.delete(history_id)
        return {"status": "deleted"}
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "历史记录不存在", "code": "NOT_FOUND"},
        ) from exc


@router.post("/history/{history_id}/retry-publish", status_code=202)
async def retry_history_publish(history_id: str) -> dict[str, str | None]:
    try:
        row = history_service.retry_publish(history_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "历史记录不存在", "code": "NOT_FOUND"},
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": str(exc), "code": "TEXT_UNAVAILABLE"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": str(exc), "code": "NOT_PUBLISHABLE"},
        ) from exc
    return {"status": row.publish_status, "task_id": row.task_id}


@router.post("/history/{history_id}/reprocess", status_code=201)
async def reprocess_history(history_id: str, body: ReprocessBody) -> dict[str, Any]:
    try:
        row = history_service.get(history_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "历史记录不存在", "code": "NOT_FOUND"},
        ) from exc

    try:
        task = queue_service.enqueue(
            row.url,
            source="api",
            reprocess_mode=body.mode,
            history_source_id=history_id,
            local_audio_path=(
                row.local_audio_path if body.mode == "transcribe_and_polish" else None
            ),
            title=row.title,
            duration_sec=row.duration_sec,
            requested_route=body.requested_route,
        )
    except DuplicateTaskError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "相同 URL 已在队列中",
                "code": "DUPLICATE_URL",
                "existing_id": exc.existing_id,
            },
        ) from exc
    return {
        "task_id": task.id,
        "mode": body.mode,
        "requested_route": task.requested_route,
        "status": task.status,
    }


def _chat_context(history_id: str, body: ChatBody) -> tuple[str, list[dict[str, str]]]:
    import config

    if not config.DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=503,
            detail={"error": "未配置 DeepSeek API Key", "code": "DEEPSEEK_NOT_CONFIGURED"},
        )

    try:
        history_service.get(history_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "历史记录不存在", "code": "NOT_FOUND"},
        ) from exc

    try:
        article_text = history_service.get_article_text(history_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": str(exc) or "整理后文稿不可用", "code": "TEXT_UNAVAILABLE"},
        ) from exc

    return article_text, [m.model_dump() for m in body.messages]


@router.post("/history/{history_id}/chat")
async def chat_about_history(history_id: str, body: ChatBody) -> dict[str, str]:
    from deepseek_client import DeepSeekError, chat_about_article

    article_text, messages = _chat_context(history_id, body)
    try:
        reply = chat_about_article(article_text, messages)
    except DeepSeekError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "code": "DEEPSEEK_ERROR"},
        ) from exc

    return {"reply": reply}


@router.post("/history/{history_id}/chat/stream")
async def chat_about_history_stream(history_id: str, body: ChatBody) -> StreamingResponse:
    from deepseek_client import DeepSeekError, stream_chat_about_article

    article_text, messages = _chat_context(history_id, body)

    def event_stream():
        try:
            for event in stream_chat_about_article(article_text, messages):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except DeepSeekError as exc:
            payload = {"type": "error", "error": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
