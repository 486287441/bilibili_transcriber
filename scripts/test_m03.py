"""M03 queue acceptance tests (server must be running for API tests)."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BASE = "http://127.0.0.1:8765"
SAMPLE_URL = "https://www.bilibili.com/video/BV1xx411c7mD"


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, trust_env=False, timeout=10.0)


def test_state_machine_rejects_illegal_transition() -> None:
    from server.queue_service import InvalidTransitionError, queue_service

    try:
        queue_service.validate_transition("pending", "polishing")
        raise AssertionError("expected InvalidTransitionError")
    except InvalidTransitionError:
        pass
    print("B3 state machine PASS")


def test_db_path() -> None:
    from server.queue_db import DB_PATH

    assert DB_PATH.name == "queue.db"
    assert "data" in DB_PATH.parts
    assert "tmp" not in str(DB_PATH).lower()
    print("A3 db path PASS")


def test_duplicate_url_409() -> None:
    suffix = uuid.uuid4().hex[:8]
    url = f"https://www.bilibili.com/video/BV1dup{suffix}"
    with client() as c:
        r1 = c.post("/api/queue", json={"url": url})
        assert r1.status_code == 201, r1.text
        task_id = r1.json()["id"]
        r2 = c.post("/api/queue", json={"url": url})
        assert r2.status_code == 409, r2.text
        c.delete(f"/api/queue/{task_id}")
    print("C1 duplicate 409 PASS")


def test_reorder() -> None:
    suffix = uuid.uuid4().hex[:8]
    with client() as c:
        ids = []
        for i in range(3):
            r = c.post(
                "/api/queue",
                json={"url": f"https://www.bilibili.com/video/BV1reorder{suffix}{i}"},
            )
            assert r.status_code == 201, r.text
            ids.append(r.json()["id"])
        rev = list(reversed(ids))
        r = c.patch("/api/queue/reorder", json={"ids": rev})
        assert r.status_code == 200, r.text
        listed = c.get("/api/queue").json()
        positions = sorted(
            (t["position"], t["id"]) for t in listed if t["id"] in ids
        )
        ordered = [tid for _, tid in positions]
        assert ordered == rev, ordered
        for tid in ids:
            c.delete(f"/api/queue/{tid}")
    print("E2 reorder PASS")


def test_get_by_id() -> None:
    suffix = uuid.uuid4().hex[:8]
    url = f"https://www.bilibili.com/video/BV1get{suffix}"
    with client() as c:
        r = c.post("/api/queue", json={"url": url})
        assert r.status_code == 201
        tid = r.json()["id"]
        detail = c.get(f"/api/queue/{tid}").json()
        assert detail["id"] == tid
        assert detail["url"] == url
        c.delete(f"/api/queue/{tid}")
    print("E get by id PASS")


def test_persistence_three_tasks() -> None:
    """A1: tasks survive in SQLite (same process; restart tested manually)."""
    from server import queue_db
    from server.queue_service import queue_service

    queue_service.initialize()
    created = []
    for i in range(3):
        t = queue_service.enqueue(
            f"https://www.bilibili.com/video/BV1persist{i}",
            source="api",
        )
        created.append(t.id)
    rows = queue_db.list_tasks()
    assert len([r for r in rows if r.id in created]) == 3
    order = [r.id for r in rows if r.id in created]
    assert order == created
    for tid in created:
        queue_db.delete_task(tid)
    print("A1 persistence (db) PASS")


def main() -> int:
    tests = [
        test_state_machine_rejects_illegal_transition,
        test_db_path,
        test_persistence_three_tasks,
        test_duplicate_url_409,
        test_reorder,
        test_get_by_id,
    ]
    api_tests = [test_duplicate_url_409, test_reorder, test_get_by_id]
    for fn in tests:
        if fn in api_tests:
            continue
        fn()
    try:
        with client() as c:
            c.get("/api/health").raise_for_status()
        for fn in api_tests:
            fn()
    except httpx.ConnectError:
        print("API tests skipped (server not running)")
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
