"""Offline contracts for cancellable shared ASR model loading."""

from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import model_lifecycle, model_manager, progress_db


def test_cancelled_waiter_releases_without_restarting_shared_load() -> None:
    load_started = threading.Event()
    release_load = threading.Event()
    cancel_first = threading.Event()
    load_calls: list[int] = []
    sentinel = object()

    fake_transcriber = types.ModuleType("bilibili_transcriber")
    fake_transcriber.DEVICE = "cuda"

    def load_asr_model():
        load_calls.append(1)
        load_started.set()
        assert release_load.wait(3.0), "test model load was never released"
        return sentinel

    fake_transcriber.load_asr_model = load_asr_model
    original_transcriber = sys.modules.get("bilibili_transcriber")
    original_estimate = progress_db.estimate_model_load_seconds
    original_record = progress_db.record_model_load
    original_loaded = model_lifecycle.record_loaded
    sys.modules["bilibili_transcriber"] = fake_transcriber
    progress_db.estimate_model_load_seconds = lambda **_kwargs: 1.0
    progress_db.record_model_load = lambda **_kwargs: None
    model_lifecycle.record_loaded = lambda: None

    first_result: list[BaseException] = []
    second_result: list[object] = []
    try:
        def first_waiter() -> None:
            try:
                model_manager.get_model(cancelled=cancel_first.is_set)
            except BaseException as exc:
                first_result.append(exc)

        first = threading.Thread(target=first_waiter)
        first.start()
        assert load_started.wait(1.0)
        cancel_first.set()
        first.join(1.0)
        assert not first.is_alive(), "cancelled queue worker stayed blocked"
        assert isinstance(first_result[0], model_manager.ModelLoadCancelled)
        assert model_manager.is_loading()

        second = threading.Thread(
            target=lambda: second_result.append(model_manager.get_model())
        )
        second.start()
        assert second.is_alive(), "second task did not attach to the shared load"
        assert len(load_calls) == 1, "second task started a duplicate model load"
        release_load.set()
        second.join(1.0)
        assert not second.is_alive()
        assert second_result == [sentinel]
        assert len(load_calls) == 1
    finally:
        release_load.set()
        progress_db.estimate_model_load_seconds = original_estimate
        progress_db.record_model_load = original_record
        model_lifecycle.record_loaded = original_loaded
        if original_transcriber is None:
            sys.modules.pop("bilibili_transcriber", None)
        else:
            sys.modules["bilibili_transcriber"] = original_transcriber


if __name__ == "__main__":
    test_cancelled_waiter_releases_without_restarting_shared_load()
    print("PASS test_cancelled_waiter_releases_without_restarting_shared_load")
    print("ALL PASS (1 test)")
