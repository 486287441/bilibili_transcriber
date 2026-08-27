"""M04 clipboard entry tests."""

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


def test_url_extraction_rejects_non_video() -> None:
    from video_urls import extract_video_url

    assert extract_video_url("hello") is None
    assert extract_video_url("https://google.com") is None
    assert extract_video_url("https://www.bilibili.com/video/BV1test") is not None
    print("A3 non-video rejected PASS")


def test_bilibili_part_dedup_keys() -> None:
    from video_urls import canonical_video_key

    base = "https://www.bilibili.com/video/BV1g94y1Q76G"
    p1 = f"{base}?p=1&vd_source=test"
    p6 = f"{base}/?p=6&spm_id_from=333"
    assert canonical_video_key(base) == canonical_video_key(p1)
    assert canonical_video_key(p1) != canonical_video_key(p6)
    assert canonical_video_key(p6) == "bilibili:bv1g94y1q76g:p6"
    print("bilibili part dedup keys PASS")


def test_bilibili_download_is_limited_to_selected_part() -> None:
    from bilibili_transcriber import _ydl_opts_for_site

    bilibili_opts = _ydl_opts_for_site("bilibili")
    youtube_opts = _ydl_opts_for_site("youtube")

    assert bilibili_opts["noplaylist"] is True
    assert "noplaylist" not in youtube_opts
    print("bilibili selected-part download PASS")


def test_history_dedup() -> None:
    import uuid

    from server import history_db, queue_db
    from server.entry_points import submit_url
    from server.queue_service import queue_service
    from video_urls import canonical_video_key

    queue_service.initialize()
    history_db.init_history()
    suffix = uuid.uuid4().hex[:8]
    url = f"https://www.bilibili.com/video/BV1hist{suffix}"
    alt = f"{url}?vd_source=test"

    row = history_db.upsert_from_task(
        task_id=f"task-{suffix}",
        url=url,
        title="test",
        duration_sec=60,
        site="bilibili",
        source="api",
        status="completed",
        processing_duration_sec=30,
        output_doc_url="https://example.com/doc",
        output_text_path=None,
        local_audio_path=None,
        error_message=None,
    )
    assert history_db.find_by_url(alt) is not None
    assert canonical_video_key(url) == canonical_video_key(alt)

    blocked = submit_url(alt, source="api")
    assert blocked.skipped_history is True
    assert blocked.existing_id == row.id
    assert blocked.task is None

    history_db.delete_history(row.id)
    allowed = submit_url(alt, source="api")
    assert allowed.task is not None
    queue_db.delete_task(allowed.task.id)
    print("history dedup PASS")


def test_clipboard_silent_dedup() -> None:
    from server.entry_points import submit_url
    from server.queue_service import queue_service

    queue_service.initialize()

    suffix = uuid.uuid4().hex[:8]
    url = f"https://www.bilibili.com/video/BV1clip{suffix}"
    r1 = submit_url(url, source="clipboard", silent_duplicate=True)
    assert r1.task is not None
    r2 = submit_url(url, source="clipboard", silent_duplicate=True)
    assert r2.duplicate is True and r2.task is None
    from server import queue_db

    queue_db.delete_task(r1.task.id)
    print("B1/B2 silent dedup PASS")


def test_settings_clipboard_toggle() -> None:
    with client() as c:
        r = c.put("/api/settings", json={"clipboard_enabled": False})
        assert r.status_code == 200, r.text
        assert r.json()["clipboard_enabled"] is False
        r = c.put("/api/settings", json={"clipboard_enabled": True})
        assert r.json()["clipboard_enabled"] is True
    print("C1/C2 clipboard toggle PASS")


def test_api_manual_enqueue_structure() -> None:
    suffix = uuid.uuid4().hex[:8]
    url = f"https://www.bilibili.com/video/BV1api{suffix}"
    with client() as c:
        r = c.post("/api/queue", json={"url": url})
        assert r.status_code == 201, r.text
        data = r.json()
        for key in ("id", "url", "source", "status", "site", "position"):
            assert key in data, data
        assert data["source"] == "api"
        assert data["status"] == "pending"
        c.delete(f"/api/queue/{data['id']}")
    print("D1 manual enqueue PASS")


def main() -> int:
    test_url_extraction_rejects_non_video()
    test_bilibili_part_dedup_keys()
    test_bilibili_download_is_limited_to_selected_part()
    test_history_dedup()
    test_clipboard_silent_dedup()
    try:
        with client() as c:
            c.get("/api/health").raise_for_status()
        test_settings_clipboard_toggle()
        test_api_manual_enqueue_structure()
    except httpx.ConnectError:
        print("API tests skipped (server not running)")
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
