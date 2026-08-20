"""Offline contracts for the independent Feishu publisher."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

row = SimpleNamespace(
    task_id="task-1",
    status="completed",
    publish_status="pending",
    processed_at="2026-08-18T00:00:00+00:00",
    title="测试视频",
    url="https://www.bilibili.com/video/BV1xx411c7mD",
)
states: list[tuple[str, str, str | None]] = []
create_calls: list[dict] = []

history_db_stub = ModuleType("server.history_db")
history_db_stub.get_history_by_task_id = lambda task_id: row
history_db_stub.list_pending_publications = lambda: []
sys.modules["server.history_db"] = history_db_stub

article_store_stub = ModuleType("server.article_store")
article_store_stub.load_polished = lambda task_id: "# 视频总结\n内容\n\n# 原文\n正文"
sys.modules["server.article_store"] = article_store_stub

feishu_stub = ModuleType("feishu_client")


def create_video_document(**kwargs):
    create_calls.append(kwargs)
    return "https://example.feishu.cn/docx/test"


feishu_stub.create_video_document = create_video_document
sys.modules["feishu_client"] = feishu_stub


class FakeHistoryService:
    def update_publish_state(self, task_id, status, *, output_doc_url=None, error=None):
        states.append((task_id, status, output_doc_url or error))


history_service_stub = ModuleType("server.history_service")
history_service_stub.history_service = FakeHistoryService()
sys.modules["server.history_service"] = history_service_stub

settings_stub = ModuleType("server.settings_store")
settings_stub.should_auto_open_feishu = lambda: False
sys.modules["server.settings_store"] = settings_stub

pipeline_stub = ModuleType("pipeline")
pipeline_stub.open_feishu_in_browser = lambda _url: None
sys.modules["pipeline"] = pipeline_stub

import server.feishu_publish_queue as publish_module
from server.feishu_publish_queue import FeishuPublishQueue


def test_publish_backfills_history_without_main_worker() -> None:
    publisher = FeishuPublishQueue()
    publisher._publish("task-1")
    assert [state[1] for state in states] == ["publishing", "published"]
    assert states[-1][2] == "https://example.feishu.cn/docx/test"
    assert len(create_calls) == 1
    assert create_calls[0]["body_md"].startswith("# 视频总结")


def test_publish_failure_is_isolated_and_recorded_after_retries() -> None:
    states.clear()
    attempts = 0

    def fail_create(**_kwargs):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("飞书暂时不可用")

    original = publish_module.create_video_document
    publish_module.create_video_document = fail_create
    publisher = FeishuPublishQueue()
    publisher._stop_event = SimpleNamespace(wait=lambda _delay: False)
    try:
        publisher._publish("task-1")
    finally:
        publish_module.create_video_document = original

    assert attempts == 3
    assert [state[1] for state in states] == ["publishing", "failed"]
    assert states[-1][2] == "飞书暂时不可用"


if __name__ == "__main__":
    test_publish_backfills_history_without_main_worker()
    test_publish_failure_is_isolated_and_recorded_after_retries()
    print("background Feishu publish tests PASS")
