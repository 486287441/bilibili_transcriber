"""Last-activity tracking for idle model sleep (M06)."""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_last_activity = time.monotonic()


def touch() -> None:
    global _last_activity
    with _lock:
        _last_activity = time.monotonic()


def idle_seconds() -> float:
    with _lock:
        return time.monotonic() - _last_activity
