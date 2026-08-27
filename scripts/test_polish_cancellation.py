"""Offline cancellation contract for an in-flight DeepSeek polish call."""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline
from server import pipeline_runner


class NoOpProgress:
    def set_phase(self, *_args, **_kwargs) -> None:
        pass

    def update(self, *_args, **_kwargs) -> None:
        pass


def test_polish_waiter_cancels_and_background_cannot_commit() -> None:
    started = threading.Event()
    release = threading.Event()
    cancel = threading.Event()
    committed: list[bool] = []
    errors: list[BaseException] = []

    original_generate = pipeline.generate_local_article_result
    original_progress = pipeline_runner.progress_tracker

    def fake_generate(*_args, cancelled=None, **_kwargs) -> bool:
        started.set()
        assert release.wait(3.0)
        if cancelled is not None and cancelled():
            return False
        committed.append(True)
        return True

    pipeline.generate_local_article_result = fake_generate
    pipeline_runner.progress_tracker = NoOpProgress()
    try:
        def run() -> None:
            try:
                pipeline_runner.polish_with_progress(
                    "测试文本",
                    title="测试",
                    url="https://example.com",
                    task_id="polish-cancel-contract",
                    open_browser=False,
                    cancelled=cancel.is_set,
                )
            except BaseException as exc:
                errors.append(exc)

        waiter = threading.Thread(target=run)
        waiter.start()
        assert started.wait(1.0)
        cancel.set()
        waiter.join(1.0)
        assert not waiter.is_alive(), "queue worker remained blocked by DeepSeek"
        assert isinstance(errors[0], pipeline_runner.PolishCancelled)
        release.set()
        assert not committed
    finally:
        release.set()
        pipeline.generate_local_article_result = original_generate
        pipeline_runner.progress_tracker = original_progress


def test_cancelled_pipeline_removes_partial_transcript() -> None:
    cancel = threading.Event()
    organizing = threading.Event()
    release = threading.Event()
    original_root = pipeline._PROJECT_ROOT
    original_organize = pipeline.organize_transcript
    original_first_stage = pipeline.is_first_stage_enabled
    original_second_stage = pipeline.is_second_stage_enabled
    result: list[bool] = []
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline._PROJECT_ROOT = Path(temp_dir)
            pipeline.is_first_stage_enabled = lambda: True
            pipeline.is_second_stage_enabled = lambda: True

            def organize(_text: str) -> str:
                organizing.set()
                assert release.wait(3.0)
                return "# 不应落盘"

            pipeline.organize_transcript = organize
            worker = threading.Thread(
                target=lambda: result.append(
                    pipeline.generate_local_article_result(
                        "可信逐字稿",
                        task_id="cancel-partial-output",
                        input_is_trusted=True,
                        cancelled=cancel.is_set,
                    )
                )
            )
            worker.start()
            assert organizing.wait(1.0)
            partial = (
                Path(temp_dir)
                / "downloads"
                / "transcripts"
                / "cancel-partial-output.txt"
            )
            assert partial.is_file(), "test did not create the partial transcript"
            cancel.set()
            release.set()
            worker.join(1.0)
            assert result == [False]
            assert not partial.exists()
            assert not (
                Path(temp_dir) / "downloads" / "polished" / "cancel-partial-output.md"
            ).exists()
    finally:
        release.set()
        pipeline._PROJECT_ROOT = original_root
        pipeline.organize_transcript = original_organize
        pipeline.is_first_stage_enabled = original_first_stage
        pipeline.is_second_stage_enabled = original_second_stage


def test_disabled_second_stage_returns_corrected_text_without_organizing() -> None:
    original_correct = pipeline.correct_transcript
    original_organize = pipeline.organize_transcript
    original_first_stage = pipeline.is_first_stage_enabled
    original_second_stage = pipeline.is_second_stage_enabled
    organize_calls: list[str] = []
    try:
        pipeline.correct_transcript = lambda _text: "第一阶段校对后的完整文章。"
        pipeline.organize_transcript = lambda text: organize_calls.append(text) or "不应生成"
        pipeline.is_first_stage_enabled = lambda: True
        pipeline.is_second_stage_enabled = lambda: False

        body, trusted = pipeline.postprocess_article("原始无标点字幕")

        assert trusted == "第一阶段校对后的完整文章。"
        assert body == trusted
        assert organize_calls == []
    finally:
        pipeline.correct_transcript = original_correct
        pipeline.organize_transcript = original_organize
        pipeline.is_first_stage_enabled = original_first_stage
        pipeline.is_second_stage_enabled = original_second_stage


def test_disabled_first_stage_preserves_punctuation_and_skips_deepseek() -> None:
    original_correct = pipeline.correct_transcript
    original_organize = pipeline.organize_transcript
    original_first_stage = pipeline.is_first_stage_enabled
    original_second_stage = pipeline.is_second_stage_enabled
    try:
        pipeline.correct_transcript = lambda _text: (_ for _ in ()).throw(
            AssertionError("quick mode must not call stage 1")
        )
        pipeline.organize_transcript = lambda _text: (_ for _ in ()).throw(
            AssertionError("quick mode must not call stage 2")
        )
        pipeline.is_first_stage_enabled = lambda: False
        pipeline.is_second_stage_enabled = lambda: True

        body, trusted = pipeline.postprocess_article(
            "第一句，有原始标点。第二句也有！",
        )

        assert trusted == "第一句，有原始标点。第二句也有！"
        assert body == trusted
    finally:
        pipeline.correct_transcript = original_correct
        pipeline.organize_transcript = original_organize
        pipeline.is_first_stage_enabled = original_first_stage
        pipeline.is_second_stage_enabled = original_second_stage


if __name__ == "__main__":
    test_polish_waiter_cancels_and_background_cannot_commit()
    print("PASS test_polish_waiter_cancels_and_background_cannot_commit")
    test_cancelled_pipeline_removes_partial_transcript()
    print("PASS test_cancelled_pipeline_removes_partial_transcript")
    test_disabled_second_stage_returns_corrected_text_without_organizing()
    print("PASS test_disabled_second_stage_returns_corrected_text_without_organizing")
    test_disabled_first_stage_preserves_punctuation_and_skips_deepseek()
    print("PASS test_disabled_first_stage_preserves_punctuation_and_skips_deepseek")
    print("ALL PASS (4 tests)")
