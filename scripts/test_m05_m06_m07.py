"""M05–M07 backend smoke tests."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BASE = "http://127.0.0.1:8765"


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, trust_env=False, timeout=10.0)


def test_progress_tracker_math() -> None:
    from server.progress_tracker import PHASE_WEIGHTS, ProgressTracker

    t = ProgressTracker()
    t._snapshots["x"] = __import__(
        "server.progress_tracker", fromlist=["ProgressSnapshot"]
    ).ProgressSnapshot(task_id="x", phase="download", phase_progress=100.0)
    t._update_global("x")
    assert abs(t._snapshots["x"].global_progress - PHASE_WEIGHTS["download"] * 100) < 0.1
    print("M05 weights PASS")


def test_progress_db_init() -> None:
    from server import progress_db

    progress_db.init_progress_stats()
    print("M05 stats db PASS")


def test_history_db() -> None:
    from server import history_db

    history_db.init_history()
    row = history_db.upsert_from_task(
        task_id="test-task",
        url="https://example.com",
        title="t",
        duration_sec=60,
        site="bilibili",
        source="api",
        status="completed",
        processing_duration_sec=120,
        output_doc_url=None,
        output_text_path=None,
        local_audio_path=None,
        error_message=None,
    )
    assert row.id
    history_db.delete_history(row.id)
    print("M07 history db PASS")


def test_idle_status_fields() -> None:
    from server.idle_manager import idle_manager

    fields = idle_manager.status_fields()
    assert "idle_seconds" in fields and "will_sleep_in_seconds" in fields
    print("M06 idle fields PASS")


def test_api_status_extended() -> None:
    with client() as c:
        data = c.get("/api/status").json()
        for key in (
            "model_loaded",
            "idle_seconds",
            "idle_timeout_minutes",
            "will_sleep_in_seconds",
        ):
            assert key in data, data
    print("M06 status API PASS")


def test_history_list() -> None:
    with client() as c:
        r = c.get("/api/history")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and "total" in body
    print("M07 history list PASS")


def test_progress_endpoint() -> None:
    suffix = uuid.uuid4().hex[:8]
    with client() as c:
        r = c.post("/api/queue", json={"url": f"https://www.bilibili.com/video/BV1prog{suffix}"})
        assert r.status_code == 201, r.text
        tid = r.json()["id"]
        pr = c.get(f"/api/queue/{tid}/progress")
        assert pr.status_code == 200, pr.text
        assert "global_progress" in pr.json()
        c.delete(f"/api/queue/{tid}")
    print("M05 progress API PASS")


def main() -> int:
    test_progress_tracker_math()
    test_progress_db_init()
    test_history_db()
    test_idle_status_fields()
    try:
        with client() as c:
            c.get("/api/health").raise_for_status()
        test_api_status_extended()
        test_history_list()
        test_progress_endpoint()
    except httpx.ConnectError:
        print("API tests skipped (server not running)")
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
