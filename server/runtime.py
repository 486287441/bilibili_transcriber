"""Process-wide runtime state shared by HTTP routes and WebSocket handlers."""

from __future__ import annotations

import threading
import time

_start_time = time.monotonic()
_processing = False
_worker_state = "idle"
_lock = threading.Lock()


def uptime_seconds() -> float:
    return time.monotonic() - _start_time


def is_processing() -> bool:
    with _lock:
        return _processing


def set_processing(value: bool) -> None:
    with _lock:
        global _processing
        _processing = value


def get_worker_state() -> str:
    with _lock:
        return _worker_state


def set_worker_state(value: str) -> None:
    with _lock:
        global _worker_state
        _worker_state = value
