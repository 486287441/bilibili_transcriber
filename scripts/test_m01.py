"""M01 acceptance smoke tests (run while server is up)."""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx
import websockets

BASE = "http://127.0.0.1:8765"
WS_URL = "ws://127.0.0.1:8765/ws"


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, trust_env=False, timeout=5.0)


def test_a1_health() -> None:
    with client() as c:
        r = c.get("/api/health")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data
    print("A1 PASS")


def test_b1_ws_connected() -> None:
    async def run() -> None:
        async with websockets.connect(WS_URL) as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.0))
            assert msg["type"] == "connected", msg

    asyncio.run(run())
    print("B1 PASS")


def test_b2_broadcast() -> None:
    async def run() -> None:
        async with websockets.connect(WS_URL) as ws1, websockets.connect(WS_URL) as ws2:
            await asyncio.wait_for(ws1.recv(), timeout=1.0)
            await asyncio.wait_for(ws2.recv(), timeout=1.0)
            with client() as c:
                c.put("/api/settings", json={"clipboard_enabled": False})
            m1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=2.0))
            m2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=2.0))
            assert m1["type"] == "settings.changed", m1
            assert m2["type"] == "settings.changed", m2
            assert m1["payload"]["clipboard_enabled"] is False

    asyncio.run(run())
    print("B2 PASS")


def test_b3_disconnect_count() -> None:
    async def run() -> None:
        ws = await websockets.connect(WS_URL)
        await asyncio.wait_for(ws.recv(), timeout=1.0)
        with client() as c:
            before = c.get("/api/status").json()["websocket_connections"]
        await ws.close()
        await asyncio.sleep(0.3)
        with client() as c:
            after = c.get("/api/status").json()["websocket_connections"]
        assert after == before - 1, (before, after)

    asyncio.run(run())
    print("B3 PASS")


def test_c1_secrets_no_keys() -> None:
    with client() as c:
        r = c.get("/api/settings/secrets")
        body = r.text
        assert "sk-" not in body
        data = r.json()
        assert "deepseek_configured" in data
    print("C1 PASS")


def test_c2_settings_persist() -> None:
    with client() as c:
        c.put("/api/settings", json={"clipboard_enabled": False})
        assert c.get("/api/settings").json()["clipboard_enabled"] is False
    print("C2 PASS (in-memory; restart test manual)")


def test_c3_settings_changed_event() -> None:
    async def run() -> None:
        async with websockets.connect(WS_URL) as ws:
            await asyncio.wait_for(ws.recv(), timeout=1.0)
            with client() as c:
                c.put("/api/settings", json={"clipboard_enabled": True})
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert msg["type"] == "settings.changed", msg

    asyncio.run(run())
    print("C3 PASS")


def main() -> int:
    tests = [
        test_a1_health,
        test_b1_ws_connected,
        test_b2_broadcast,
        test_b3_disconnect_count,
        test_c1_secrets_no_keys,
        test_c2_settings_persist,
        test_c3_settings_changed_event,
    ]
    for fn in tests:
        fn()
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
