"""Queue REST API routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from server.entry_points import submit_url
from server.progress_tracker import progress_tracker
from server.queue_service import (
    InvalidTransitionError,
    TaskInProgressError,
    TaskNotFoundError,
    queue_service,
)
from server.worker import worker_service
from video_urls import extract_video_url

router = APIRouter(prefix="/api")


class QueueAddBody(BaseModel):
    url: str = Field(min_length=1)
    requested_route: Literal["auto", "subtitle", "ocr", "asr"] = "auto"


class QueueReorderBody(BaseModel):
    ids: list[str] = Field(min_length=1)


@router.get("/queue")
async def list_queue(status: str | None = Query(default=None)) -> list[dict[str, Any]]:
    return worker_service.list_tasks(status=status)


@router.post("/queue", status_code=201)
async def add_queue_item(body: QueueAddBody) -> dict[str, Any]:
    url = extract_video_url(body.url.strip())
    if not url:
        raise HTTPException(
            status_code=400,
            detail={"error": "无效或不支持的视频链接", "code": "INVALID_URL"},
        )
    result = submit_url(
        url,
        source="api",
        silent_duplicate=False,
        requested_route=body.requested_route,
    )
    if result.skipped_history:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "该视频已在历史记录中，如需重新处理请从历史记录操作或先删除记录",
                "code": "ALREADY_IN_HISTORY",
                "existing_id": result.existing_id,
            },
        )
    if result.duplicate or result.task is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "相同 URL 已在队列中",
                "code": "DUPLICATE_URL",
                "existing_id": result.existing_id,
            },
        )
    return result.task.to_dict()


@router.get("/queue/{task_id}/progress")
async def get_task_progress(task_id: str) -> dict[str, Any]:
    snap = progress_tracker.get_snapshot(task_id)
    if not snap:
        try:
            queue_service.get(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"error": "任务不存在", "code": "NOT_FOUND"},
            ) from exc
        return {
            "task_id": task_id,
            "phase": "pending",
            "phase_progress": 0.0,
            "global_progress": 0.0,
            "eta_seconds": 0,
            "detail": {},
        }
    return snap


@router.get("/queue/{task_id}")
async def get_queue_item(task_id: str) -> dict[str, Any]:
    try:
        return queue_service.get(task_id).to_dict()
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "任务不存在", "code": "NOT_FOUND"},
        ) from exc


@router.delete("/queue/{task_id}")
async def delete_queue_item(task_id: str) -> dict[str, str]:
    try:
        task = queue_service.get(task_id)
        if task.status in {"pending", "downloading", "transcribing", "polishing"}:
            cancelled = queue_service.cancel(task_id)
            return {
                "status": (
                    "cancelled" if cancelled.status == "cancelled" else "cancel_requested"
                )
            }
        queue_service.delete(task_id)
        return {"status": "deleted"}
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "任务不存在", "code": "NOT_FOUND"},
        ) from exc
    except TaskInProgressError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": str(exc), "code": "IN_PROGRESS"},
        ) from exc


@router.post("/queue/{task_id}/retry")
async def retry_queue_item(task_id: str) -> dict[str, Any]:
    try:
        return queue_service.retry(task_id).to_dict()
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "任务不存在", "code": "NOT_FOUND"},
        ) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": str(exc), "code": "INVALID_RETRY"},
        ) from exc


@router.patch("/queue/reorder")
async def reorder_queue(body: QueueReorderBody) -> list[dict[str, Any]]:
    try:
        return [t.to_dict() for t in queue_service.reorder(body.ids)]
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": str(exc), "code": "NOT_FOUND"},
        ) from exc
