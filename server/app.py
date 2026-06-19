"""FastAPI application factory and route registration."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

import config
from server import __version__
from server import autostart as autostart_service
from server.errors import register_exception_handlers
from server.logging_config import configure_logging, new_request_id, request_id_var
from server import model_manager
from server.runtime import is_processing, uptime_seconds
from server.secrets import get_secrets_mask
from server.settings_store import AppSettings, load_settings, update_settings
from server.websocket_manager import ws_manager
from server.idle_manager import idle_manager
from server.listeners import listener_manager
from server.routes_history import router as history_router
from server.routes_logs import router as logs_router
from server.routes_queue import router as queue_router
from server.worker import worker_service

logger = logging.getLogger("server.app")

_SPA_DIST = config.PROJECT_ROOT / "web" / "dist"


def _mount_spa(app: FastAPI) -> None:
    if not _SPA_DIST.is_dir():
        logger.warning("前端未构建，访问 / 无 UI（在 web/ 目录执行 npm install && npm run build）")
        return
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_SPA_DIST, html=True), name="spa")
    logger.info("已挂载前端静态资源: %s", _SPA_DIST)


_LOCAL_ORIGINS = (
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clipboard_enabled: bool | None = None
    autostart_enabled: bool | None = None
    auto_open_feishu: bool | None = None
    model_load_policy: str | None = Field(default=None, pattern="^(lazy|eager)$")
    model_idle_timeout_minutes: int | None = Field(default=None, ge=1, le=1440)
    deepseek_model: str | None = Field(
        default=None,
        pattern="^(deepseek-v4-pro|deepseek-v4-flash)$",
    )
    recent_completed_dedup_minutes: int | None = Field(default=None, ge=0, le=10080)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    logger.info(
        "服务启动 version=%s host=%s port=%d",
        __version__,
        config.SERVER_HOST,
        config.SERVER_PORT,
    )

    loop = asyncio.get_running_loop()
    worker_service.set_event_loop(loop)

    settings = load_settings()
    if settings.model_load_policy == "eager":
        logger.info("MODEL_LOAD_POLICY=eager，后台预加载模型")
        model_manager.preload_model_async()
    else:
        logger.info("MODEL_LOAD_POLICY=lazy，首次任务时再加载模型")

    worker_service.start()
    listener_manager.start()
    idle_manager.set_event_loop(loop)
    idle_manager.start()

    yield

    idle_manager.stop()
    listener_manager.stop()
    worker_service.stop(timeout=30.0)
    logger.info("服务正在关闭")


def create_app() -> FastAPI:
    app = FastAPI(title="Bilibili Transcriber API", version=__version__, lifespan=lifespan)
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_LOCAL_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request_id = new_request_id()
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            request_id_var.reset(token)

    api = APIRouter(prefix="/api")

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @api.get("/status")
    async def status() -> dict[str, Any]:
        base = {
            "uptime_seconds": round(uptime_seconds(), 2),
            "is_processing": is_processing(),
            "worker_state": worker_service.worker_state,
            "model_loaded": model_manager.is_model_loaded(),
            "model_loading": model_manager.is_loading(),
            "websocket_connections": ws_manager.connection_count,
        }
        base.update(idle_manager.status_fields())
        base.update(model_manager.status_fields())
        return base

    @api.get("/settings")
    async def get_settings() -> AppSettings:
        return load_settings()

    @api.get("/settings/secrets")
    async def get_settings_secrets() -> dict:
        return get_secrets_mask()

    @api.put("/settings")
    async def put_settings(body: SettingsUpdate) -> AppSettings:
        partial = body.model_dump(exclude_none=True)
        if not partial:
            raise HTTPException(
                status_code=400,
                detail={"error": "未提供可更新字段", "code": "EMPTY_UPDATE"},
            )
        updated = update_settings(partial)
        from server import activity

        activity.touch()
        await ws_manager.broadcast("settings.changed", updated.model_dump())
        return updated

    @api.get("/storage/polished")
    async def get_polished_storage() -> dict[str, int]:
        from server.article_store import polished_storage_stats

        return polished_storage_stats()

    @api.post("/storage/polished/clear")
    async def clear_polished_storage() -> dict[str, int]:
        from server.article_store import clear_all_polished

        return clear_all_polished()

    @api.post("/model/unload")
    async def model_unload() -> dict[str, Any]:
        from server.queue_service import queue_service

        if queue_service.list(status="transcribing"):
            raise HTTPException(
                status_code=409,
                detail={"error": "转录进行中，无法卸载模型", "code": "TRANSCRIBING"},
            )
        unloaded = idle_manager.try_unload()
        return {"model_loaded": model_manager.is_model_loaded(), "unloaded": unloaded}

    @api.post("/model/load")
    async def model_load() -> dict[str, Any]:
        from server import activity

        activity.touch()
        model_manager.get_model(emit_event=True)
        return {"model_loaded": model_manager.is_model_loaded()}

    app.include_router(queue_router)
    app.include_router(history_router)
    app.include_router(logs_router)

    @api.get("/autostart")
    async def get_autostart() -> dict:
        return autostart_service.get_autostart_status()

    @api.post("/autostart/enable")
    async def enable_autostart() -> dict:
        try:
            result = autostart_service.enable_autostart()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=500,
                detail={"error": str(exc), "code": "AUTOSTART_ENABLE_FAILED"},
            ) from exc
        settings = load_settings()
        await ws_manager.broadcast("settings.changed", settings.model_dump())
        return result

    @api.post("/autostart/disable")
    async def disable_autostart() -> dict:
        try:
            result = autostart_service.disable_autostart()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=500,
                detail={"error": str(exc), "code": "AUTOSTART_DISABLE_FAILED"},
            ) from exc
        settings = load_settings()
        await ws_manager.broadcast("settings.changed", settings.model_dump())
        return result

    app.include_router(api)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await ws_manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("WebSocket 连接异常")
        finally:
            await ws_manager.disconnect(websocket)

    _mount_spa(app)
    return app


app = create_app()
