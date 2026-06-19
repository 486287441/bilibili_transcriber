"""Enqueue a URL and poll until the pipeline finishes."""

from __future__ import annotations

import sys
import time

import httpx

BASE = "http://127.0.0.1:8765"
URL = (
    "https://www.bilibili.com/video/BV1KLGE6FEoJ/"
    "?vd_source=810f7fb819d8f715ab1b2c502ca88f6a"
)
BV = "BV1KLGE6FEoJ"
TIMEOUT_SEC = 900


def main() -> int:
    client = httpx.Client(base_url=BASE, trust_env=False, timeout=30.0)

    for task in client.get("/api/queue").json():
        if BV in task.get("url", ""):
            print(f"remove existing {task['id']} status={task.get('status')}")
            client.delete(f"/api/queue/{task['id']}")
            time.sleep(0.5)

    resp = client.post("/api/queue", json={"url": URL})
    if resp.status_code == 409:
        detail = resp.json().get("detail", resp.json())
        code = detail.get("code")
        if code == "ALREADY_IN_HISTORY":
            print("already in history:", detail)
            return 0
        existing_id = detail.get("existing_id")
        if existing_id:
            print("duplicate active task, monitoring", existing_id)
            task_id = existing_id
        else:
            resp.raise_for_status()
    else:
        resp.raise_for_status()
        task_id = resp.json()["id"]
    print("task_id", task_id)

    last_key = None
    deadline = time.time() + TIMEOUT_SEC
    while time.time() < deadline:
        task = client.get(f"/api/queue/{task_id}").json()
        status = task.get("status")
        prog = client.get(f"/api/queue/{task_id}/progress").json()
        phase = prog.get("phase")
        gp = float(prog.get("global_progress") or 0)
        key = (status, phase, int(gp))
        if key != last_key:
            err = task.get("error_message")
            print(f"status={status} phase={phase} global={gp:.1f}% err={err}")
            last_key = key
        if status in {"completed", "failed", "cancelled"}:
            print("FINAL", task)
            return 0 if status == "completed" else 1
        time.sleep(3)

    print("TIMEOUT", client.get(f"/api/queue/{task_id}").json())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
