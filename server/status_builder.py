"""Shared /api/status payload builder."""

from __future__ import annotations

from typing import Any

from server import model_manager
from server.idle_manager import idle_manager
from server.runtime import is_processing, uptime_seconds
from server.websocket_manager import ws_manager
from server.worker import worker_service


def build_status_payload() -> dict[str, Any]:
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
