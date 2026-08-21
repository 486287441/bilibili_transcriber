"""Offline checks for the persistent Chinese user activity timeline."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import user_activity_log


def main() -> int:
    original_path = user_activity_log._PATH
    try:
        with tempfile.TemporaryDirectory(prefix="activity-log-test-") as temp_dir:
            user_activity_log._PATH = Path(temp_dir) / "activity.jsonl"
            first = user_activity_log.record(
                "音频下载完成",
                level="success",
                task_id="task-1",
                title="测试视频",
            )
            second = user_activity_log.record(
                "正在加载语音识别模型",
                detail="首次加载需要读取本地模型。",
                task_id="task-1",
                timing={
                    "total_seconds": 12.5,
                    "phases": [{"key": "download", "label": "媒体下载", "seconds": 2.5}],
                },
            )
            items = user_activity_log.recent(limit=20)
            assert [item["id"] for item in items] == [second["id"], first["id"]]
            assert items[0]["message"] == "正在加载语音识别模型"
            assert items[0]["timing"]["total_seconds"] == 12.5
            assert items[1]["level"] == "success"
            assert "download models from model hub" not in user_activity_log._PATH.read_text(
                encoding="utf-8"
            )
    finally:
        user_activity_log._PATH = original_path
    print("user activity log tests PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
