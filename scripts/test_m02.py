"""M02 acceptance smoke tests (run while server is up)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BASE = "http://127.0.0.1:8765"


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, trust_env=False, timeout=10.0)


def test_b1_model_not_loaded_at_idle() -> None:
    with client() as c:
        data = c.get("/api/status").json()
        assert data["model_loaded"] is False, data
        assert data["worker_state"] == "idle", data
    print("B1 PASS")


def test_status_fields() -> None:
    with client() as c:
        data = c.get("/api/status").json()
        for key in ("worker_state", "model_loaded", "uptime_seconds", "websocket_connections"):
            assert key in data, data
    print("status fields PASS")


def test_queue_post_invalid() -> None:
    with client() as c:
        r = c.post("/api/queue", json={"url": "not-a-url"})
        assert r.status_code == 400, r.text
    print("queue invalid URL PASS")


def test_autostart_get() -> None:
    with client() as c:
        r = c.get("/api/autostart")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "enabled" in data
        assert data.get("method") in (None, "task_scheduler", "registry")
    print("autostart GET PASS")


def test_autostart_enable_disable() -> None:
    with client() as c:
        r = c.post("/api/autostart/enable")
        assert r.status_code == 200, r.text
        assert c.get("/api/autostart").json()["enabled"] is True
        r = c.post("/api/autostart/disable")
        assert r.status_code == 200, r.text
        assert c.get("/api/autostart").json()["enabled"] is False
    print("D1/D3 autostart enable/disable PASS")


def test_autostart_absolute_paths() -> None:
    from server.autostart import _build_launch_command, _project_root, _silent_launcher_vbs

    cmd = _build_launch_command()
    vbs = str(_silent_launcher_vbs())
    root = str(_project_root())
    assert vbs in cmd, cmd
    assert root in cmd, cmd
    assert "wscript.exe" in cmd.lower(), cmd
    assert "launch_silent.vbs" in cmd, cmd
    assert "cmd /c" not in cmd.lower(), cmd
    print("D4 absolute paths PASS")


def main() -> int:
    tests = [
        test_b1_model_not_loaded_at_idle,
        test_status_fields,
        test_queue_post_invalid,
        test_autostart_get,
        test_autostart_enable_disable,
        test_autostart_absolute_paths,
    ]
    for fn in tests:
        fn()
    print("ALL PASS (A1/A2/C2 long-running tests skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
