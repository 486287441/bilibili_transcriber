"""Idle model sleep: auto-unload after inactivity (M06)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time

from server import activity, model_manager
from server.queue_service import queue_service
from server.settings_store import load_settings
from server.websocket_manager import ws_manager

logger = logging.getLogger("server.idle")

CHECK_INTERVAL_SEC = 60.0


class IdleManager:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._transcribing = False

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        model_manager.set_event_loop(loop)

    def set_transcribing(self, value: bool) -> None:
        self._transcribing = value
        if value:
            activity.touch()

    def start(self) -> None:
        activity.touch()
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="idle-manager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def status_fields(self) -> dict:
        settings = load_settings()
        timeout_sec = settings.model_idle_timeout_minutes * 60
        idle = activity.idle_seconds()
        will_sleep = max(0, int(timeout_sec - idle)) if model_manager.is_model_loaded() else 0
        return {
            "idle_seconds": round(idle, 1),
            "idle_timeout_minutes": settings.model_idle_timeout_minutes,
            "will_sleep_in_seconds": will_sleep if not self._transcribing else None,
        }

    def try_unload(self) -> bool:
        if self._transcribing:
            return False
        if queue_service.list(status="transcribing"):
            return False
        if not model_manager.is_model_loaded():
            return True
        model_manager.unload_model(emit_event=True)
        return True

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(CHECK_INTERVAL_SEC)
            if self._stop_event.is_set():
                break
            settings = load_settings()
            timeout = settings.model_idle_timeout_minutes * 60
            if activity.idle_seconds() < timeout:
                continue
            if self._transcribing:
                continue
            if queue_service.list(status="transcribing"):
                continue
            if model_manager.is_model_loaded():
                logger.info("空闲超时，自动卸载模型")
                model_manager.unload_model(emit_event=True)


idle_manager = IdleManager()
