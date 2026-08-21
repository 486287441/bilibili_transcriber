"""Offline contracts for queue deletion and clipboard event consumption."""

from __future__ import annotations

import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The repository's target environment provides pyperclip.  Keep this contract
# runnable in the lightweight offline interpreter used by CI as well.
if "pyperclip" not in sys.modules:
    pyperclip_stub = types.ModuleType("pyperclip")
    pyperclip_stub.paste = lambda: ""
    sys.modules["pyperclip"] = pyperclip_stub
if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *_args, **_kwargs: False
    sys.modules["dotenv"] = dotenv_stub
if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")
    fastapi_stub.WebSocket = object
    fastapi_stub.WebSocketDisconnect = RuntimeError
    sys.modules["fastapi"] = fastapi_stub
entry_points_stub = types.ModuleType("server.entry_points")
entry_points_stub.pending_count = lambda: 0
entry_points_stub.submit_url = lambda *_args, **_kwargs: None
sys.modules["server.entry_points"] = entry_points_stub
runtime_stub = types.ModuleType("server.runtime")
runtime_stub.is_processing = lambda: False
sys.modules["server.runtime"] = runtime_stub
settings_stub = types.ModuleType("server.settings_store")
settings_stub.load_settings = lambda: types.SimpleNamespace(clipboard_enabled=True)
sys.modules["server.settings_store"] = settings_stub

from server import bootstrap_cache, listeners, queue_db
from server.pipeline_runner import _ytdlp_progress_hook
from server.queue_service import (
    QueueService,
    TaskInProgressError,
    TaskNotFoundError,
    queue_service,
)


def test_deleted_clipboard_event_is_consumed_only_once() -> None:
    manager = listeners.ListenerManager()
    original_sequence = listeners._clipboard_sequence_number
    original_paste = listeners.pyperclip.paste
    try:
        listeners._clipboard_sequence_number = lambda: 101
        listeners.pyperclip.paste = lambda: "https://www.bilibili.com/video/BV1xx411c7mD"
        assert manager.ignore_current_clipboard_once(
            "https://www.bilibili.com/video/BV1xx411c7mD"
        )
        assert manager._is_ignored_clipboard_sequence(101)
        assert not manager._is_ignored_clipboard_sequence(101)
        # A new Ctrl+C produces a different sequence and must remain eligible.
        assert not manager._is_ignored_clipboard_sequence(102)
    finally:
        listeners._clipboard_sequence_number = original_sequence
        listeners.pyperclip.paste = original_paste


def test_active_download_hook_aborts_after_cancel_request() -> None:
    task_id = "clipboard-delete-contract"
    queue_service.request_cancel(task_id)
    try:
        hook = _ytdlp_progress_hook(task_id)
        try:
            hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 10})
        except RuntimeError as exc:
            assert str(exc) == "task cancellation requested"
        else:
            raise AssertionError("cancelled yt-dlp hook did not abort")
    finally:
        queue_service.clear_cancel(task_id)


def _quiet_service() -> QueueService:
    service = QueueService()
    service._emit_state_changed = lambda *_args, **_kwargs: None
    service._emit_queue_updated = lambda *_args, **_kwargs: None
    service._record_deleted = lambda *_args, **_kwargs: None
    return service


def _new_task(*, url: str = "https://www.bilibili.com/video/BV1xx411c7mD"):
    return queue_db.create_pending_task(
        url=url,
        source="test",
        telegram_chat_id=None,
        site="bilibili",
    )


def test_common_delete_states_are_durable() -> None:
    original_db_path = queue_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_db.DB_PATH = Path(temp_dir) / "queue.db"
            queue_db.init_db()
            service = _quiet_service()

            pending = _new_task()
            assert service.cancel(pending.id).status == "cancelled"
            assert queue_db.get_task(pending.id) is None

            for index, status in enumerate(("downloading", "transcribing"), start=1):
                task = _new_task(url=f"https://example.com/video/{index}")
                assert queue_db.update_task_fields(task.id, status=status) is not None
                deleted = service.cancel(task.id)
                assert deleted.status == "cancelled"
                assert service.is_cancel_requested(task.id)
                assert queue_db.get_task(task.id) is None
                try:
                    service.get(task.id)
                except TaskNotFoundError:
                    pass
                else:
                    raise AssertionError("deleted active task became visible again")
                service.clear_cancel(task.id)

            polishing = _new_task(url="https://example.com/video/polishing")
            assert queue_db.update_task_fields(polishing.id, status="polishing") is not None
            assert service.cancel(polishing.id).status == "cancelled"
            assert queue_db.get_task(polishing.id) is None
            service.clear_cancel(polishing.id)

            failed = _new_task(url="https://example.com/video/failed")
            assert queue_db.update_task_fields(failed.id, status="failed") is not None
            service.delete(failed.id)
            assert queue_db.get_task(failed.id) is None
    finally:
        queue_db.DB_PATH = original_db_path


def test_deleted_active_task_does_not_block_next_claim() -> None:
    original_db_path = queue_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_db.DB_PATH = Path(temp_dir) / "queue.db"
            queue_db.init_db()
            active = _new_task(url="https://example.com/video/active")
            waiting = _new_task(url="https://example.com/video/waiting")
            assert queue_db.update_task_fields(active.id, status="transcribing") is not None
            service = _quiet_service()
            service.cancel(active.id)
            claimed = queue_db.claim_next_pending()
            assert claimed is not None
            assert claimed.id == waiting.id
            assert claimed.status == "downloading"
    finally:
        queue_db.DB_PATH = original_db_path


def test_claim_delete_race_100_rounds() -> None:
    original_db_path = queue_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_db.DB_PATH = Path(temp_dir) / "queue.db"
            queue_db.init_db()
            service = _quiet_service()
            for index in range(100):
                task = _new_task(url=f"https://example.com/race/{index}")
                gate = threading.Barrier(2)
                errors: list[BaseException] = []

                def claim() -> None:
                    try:
                        gate.wait()
                        queue_db.claim_next_pending()
                    except BaseException as exc:
                        errors.append(exc)

                def cancel() -> None:
                    try:
                        gate.wait()
                        service.cancel(task.id)
                    except BaseException as exc:
                        errors.append(exc)

                threads = [threading.Thread(target=claim), threading.Thread(target=cancel)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(2.0)
                assert all(not thread.is_alive() for thread in threads)
                assert errors == []
                assert queue_db.get_task(task.id) is None
                service.clear_cancel(task.id)
    finally:
        queue_db.DB_PATH = original_db_path


def test_deleted_task_is_removed_from_bootstrap_immediately() -> None:
    original_ready = bootstrap_cache._ready
    original_snapshot = bootstrap_cache._snapshot
    try:
        bootstrap_cache._ready = True
        bootstrap_cache._snapshot = {
            "queue": [{"id": "keep"}, {"id": "delete-me"}],
            "history": {"items": []},
        }
        bootstrap_cache.remove_queue_task("delete-me")
        assert bootstrap_cache._snapshot["queue"] == [{"id": "keep"}]
    finally:
        bootstrap_cache._ready = original_ready
        bootstrap_cache._snapshot = original_snapshot


def test_archived_completion_is_not_reported_as_user_deletion() -> None:
    original_db_path = queue_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_db.DB_PATH = Path(temp_dir) / "queue.db"
            queue_db.init_db()
            task = _new_task(url="https://example.com/video/completed")
            assert queue_db.update_task_fields(task.id, status="completed") is not None

            service = QueueService()
            events: list[tuple[str, str]] = []
            service._evict_deleted_task = lambda task_id: None
            service._emit_queue_updated = lambda action, task_id: events.append(
                ("queue", action)
            )
            service._record_deleted = lambda *_args, **_kwargs: events.append(
                ("activity", "deleted")
            )
            service.archive_completed(task.id)

            assert queue_db.get_task(task.id) is None
            assert events == [("queue", "archive")]
    finally:
        queue_db.DB_PATH = original_db_path


if __name__ == "__main__":
    test_deleted_clipboard_event_is_consumed_only_once()
    print("PASS test_deleted_clipboard_event_is_consumed_only_once")
    test_active_download_hook_aborts_after_cancel_request()
    print("PASS test_active_download_hook_aborts_after_cancel_request")
    test_common_delete_states_are_durable()
    print("PASS test_common_delete_states_are_durable")
    test_deleted_active_task_does_not_block_next_claim()
    print("PASS test_deleted_active_task_does_not_block_next_claim")
    test_claim_delete_race_100_rounds()
    print("PASS test_claim_delete_race_100_rounds")
    test_deleted_task_is_removed_from_bootstrap_immediately()
    print("PASS test_deleted_task_is_removed_from_bootstrap_immediately")
    test_archived_completion_is_not_reported_as_user_deletion()
    print("PASS test_archived_completion_is_not_reported_as_user_deletion")
    print("ALL PASS (7 tests)")
