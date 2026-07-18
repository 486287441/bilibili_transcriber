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


def test_autostart_absolute_paths() -> None:
    from server.autostart import (
        _build_launch_command,
        _expected_startup_bat_content,
        _project_root,
        _silent_launcher_vbs,
    )

    cmd = _build_launch_command()
    vbs = str(_silent_launcher_vbs())
    root = str(_project_root())
    bat = _expected_startup_bat_content()
    assert vbs in cmd, cmd
    assert root in cmd, cmd
    assert "wscript.exe" in cmd.lower(), cmd
    assert "launch_silent.vbs" in cmd, cmd
    assert "cmd /c" not in cmd.lower(), cmd
    assert cmd in bat, bat
    assert "start.bat" not in bat.lower(), bat
    print("D4 absolute paths PASS")


def test_model_load_failure_is_recoverable() -> None:
    import bilibili_transcriber as transcriber

    original = transcriber.AutoModel
    try:
        transcriber.AutoModel = lambda **_kwargs: (_ for _ in ()).throw(ValueError("test failure"))
        try:
            transcriber.load_sensevoice_model()
        except RuntimeError as exc:
            assert "SenseVoice" in str(exc), exc
        else:
            raise AssertionError("model-load failure should raise RuntimeError")
    finally:
        transcriber.AutoModel = original
    print("model-load failure recovery PASS")


def main() -> int:
    tests = [
        test_b1_model_not_loaded_at_idle,
        test_status_fields,
        test_queue_post_invalid,
        test_autostart_absolute_paths,
        test_model_load_failure_is_recoverable,
    ]
    for fn in tests:
        fn()
    print("ALL PASS (A1/A2/C2 long-running tests skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
