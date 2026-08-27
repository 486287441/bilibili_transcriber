"""Per-task progress tracking with throttled WebSocket push (M05)."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from server import progress_db
from server.websocket_manager import ws_manager

PHASE_WEIGHTS = {
    "download": 0.15,
    "transcribe": 0.60,
    "polish": 0.25,
}

MIN_PUSH_INTERVAL = 0.5


@dataclass
class ProgressSnapshot:
    task_id: str
    phase: str = "download"
    phase_progress: float = 0.0
    global_progress: float = 0.0
    eta_seconds: int = 0
    detail: dict[str, Any] = field(default_factory=dict)
    duration_sec: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "phase": self.phase,
            "phase_progress": round(self.phase_progress, 2),
            "global_progress": round(self.global_progress, 2),
            "eta_seconds": max(0, int(self.eta_seconds)),
            "detail": self.detail,
        }


class ProgressTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshots: dict[str, ProgressSnapshot] = {}
        self._last_push: dict[str, float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._phase_started: dict[str, float] = {}

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def start_task(self, task_id: str, *, duration_sec: float | None) -> None:
        with self._lock:
            self._snapshots[task_id] = ProgressSnapshot(
                task_id=task_id,
                duration_sec=duration_sec,
            )
            self._phase_started[task_id] = time.monotonic()
        self._update_global(task_id)
        self._push(task_id, force=True)

    def set_phase(self, task_id: str, phase: str) -> None:
        with self._lock:
            snap = self._snapshots.get(task_id)
            if not snap:
                return
            snap.phase = phase
            snap.phase_progress = 0.0
            self._phase_started[task_id] = time.monotonic()
        self._update_global(task_id)
        self._push(task_id, force=True)

    def update(
        self,
        task_id: str,
        *,
        phase_progress: float | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            snap = self._snapshots.get(task_id)
            if not snap:
                return
            if phase_progress is not None:
                snap.phase_progress = max(0.0, min(100.0, phase_progress))
            if detail:
                snap.detail.update(detail)
        self._update_global(task_id)
        self._push(task_id)

    def complete_task(self, task_id: str) -> None:
        with self._lock:
            snap = self._snapshots.get(task_id)
            if snap:
                snap.phase = "polish"
                snap.phase_progress = 100.0
                snap.global_progress = 100.0
                snap.eta_seconds = 0
        self._push(task_id, force=True)
        with self._lock:
            self._snapshots.pop(task_id, None)
            self._last_push.pop(task_id, None)
            self._phase_started.pop(task_id, None)

    def clear_task(self, task_id: str) -> None:
        with self._lock:
            self._snapshots.pop(task_id, None)
            self._last_push.pop(task_id, None)
            self._phase_started.pop(task_id, None)

    def get_snapshot(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            snap = self._snapshots.get(task_id)
            return snap.to_dict() if snap else None

    def _update_global(self, task_id: str) -> None:
        snap = self._snapshots.get(task_id)
        if not snap:
            return
        completed_weight = 0.0
        for phase, weight in PHASE_WEIGHTS.items():
            if phase == snap.phase:
                completed_weight += weight * (snap.phase_progress / 100.0)
                break
            completed_weight += weight
        snap.global_progress = min(100.0, completed_weight * 100.0)

        remaining = self._estimate_remaining(task_id, snap)
        snap.eta_seconds = int(remaining)

    def _estimate_remaining(self, task_id: str, snap: ProgressSnapshot) -> float:
        """Wall-clock ETA: elapsed-based for current phase, no PHASE_WEIGHTS."""
        from server.settings_store import get_deepseek_model

        elapsed = time.monotonic() - self._phase_started.get(task_id, time.monotonic())
        polish_chars = int(snap.detail.get("polish_chars", 0))
        deepseek_model = get_deepseek_model()
        remaining = 0.0
        seen_current = False
        for phase in PHASE_WEIGHTS:
            est = progress_db.estimate_phase_seconds(
                duration_sec=snap.duration_sec,
                phase=phase,
                polish_chars=polish_chars,
                deepseek_model=deepseek_model,
            )
            if phase == snap.phase:
                seen_current = True
                explicit_eta = snap.detail.get("phase_eta_seconds")
                explicit_phase = snap.detail.get("phase_eta_phase")
                if explicit_phase == phase and explicit_eta is not None:
                    updated_at = float(
                        snap.detail.get("phase_eta_updated_elapsed_sec") or elapsed
                    )
                    phase_remaining = max(
                        float(explicit_eta) - max(0.0, elapsed - updated_at),
                        0.0,
                    )
                elif phase == "download":
                    downloaded = int(snap.detail.get("downloaded_bytes") or 0)
                    total = int(snap.detail.get("total_bytes") or 0)
                    speed = float(snap.detail.get("speed_bps") or 0)
                    if total > 0 and downloaded / total > 0.05 and speed > 0:
                        phase_remaining = max((total - downloaded) / speed, 1.0)
                    else:
                        phase_remaining = max(est - elapsed, 1.0)
                else:
                    phase_remaining = max(est - elapsed, 1.0)
                remaining += phase_remaining
            elif seen_current:
                remaining += est
        return remaining

    def _push(self, task_id: str, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_push.get(task_id, 0) < MIN_PUSH_INTERVAL:
            return
        self._last_push[task_id] = now
        payload = self.get_snapshot(task_id)
        if not payload or not self._loop:
            return
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast("task.progress", payload),
            self._loop,
        )


progress_tracker = ProgressTracker()
