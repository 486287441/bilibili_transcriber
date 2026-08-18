"""Offline contracts for bounded OCR frame batches and cancellation.

Run from the project root with any dependency-free Python interpreter::

    python scripts/test_video_ocr_batches.py

FFmpeg extraction and PaddleOCR inference are replaced with local stubs.  The
tests exercise the real batching, timestamp, cleanup, and cancellation loops.
"""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ``server.video_ocr`` only needs these settings during the tests.  Supplying a
# tiny config module keeps this suite independent from python-dotenv.
config = ModuleType("config")
config.PADDLEOCR_FRAME_INTERVAL_SEC = 1.0
config.PADDLEOCR_CROP_RATIO = 0.45
config.PADDLEOCR_DETECTION_MODEL = "test-det"
config.PADDLEOCR_RECOGNITION_MODEL = "test-rec"
sys.modules["config"] = config

from server import video_ocr  # noqa: E402


class StubProcessor:
    def __init__(self) -> None:
        self.calls = 0

    def recognize_lines(self, _frame: Path) -> list[Any]:
        self.calls += 1
        return []


def _create_stub_batch(
    output_dir: Path,
    *,
    duration_sec: float,
    interval_sec: float,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, int(math.ceil(duration_sec / interval_sec - 1e-9)))
    frames: list[Path] = []
    for index in range(frame_count):
        frame = output_dir / f"frame_{index:08d}.jpg"
        frame.write_bytes(b"stub frame")
        frames.append(frame)
    return frames


def test_ocr_uses_60_frame_batches_and_continuous_cross_batch_timeline() -> None:
    with tempfile.TemporaryDirectory(prefix="ocr-batch-contract-") as temp_dir:
        root = Path(temp_dir)
        video = root / "video.mp4"
        video.touch()
        processor = StubProcessor()
        extraction_calls: list[tuple[float, float, float]] = []
        max_frames_on_disk = 0
        candidate_index = 0
        progress_events: list[tuple[float, dict[str, Any]]] = []

        def fake_extract_batch(
            _video_path: str,
            output_dir: Path,
            *,
            start_sec: float,
            duration_sec: float,
            interval_sec: float,
            cancelled=None,
        ) -> list[Path]:
            del cancelled
            nonlocal max_frames_on_disk
            # The real loop must unlink every prior batch before requesting the
            # next one.  Otherwise a long video would accumulate on disk.
            assert not list(output_dir.glob("frame_*.jpg"))
            frames = _create_stub_batch(
                output_dir,
                duration_sec=duration_sec,
                interval_sec=interval_sec,
            )
            max_frames_on_disk = max(
                max_frames_on_disk,
                len(list(output_dir.glob("frame_*.jpg"))),
            )
            extraction_calls.append((start_sec, duration_sec, interval_sec))
            return frames

        def fake_subtitle_text(*_args: Any, **_kwargs: Any) -> tuple[str, float]:
            nonlocal candidate_index
            text = f"contract-cue-{candidate_index}"
            candidate_index += 1
            return text, 0.99

        def keep_raw_segments(segments, **_kwargs):
            return list(segments)

        with (
            patch.object(
                video_ocr,
                "probe_video",
                return_value=video_ocr.VideoInfo(width=1920, height=1080, duration_sec=125.0),
            ),
            patch.object(video_ocr, "_extract_frame_batch", side_effect=fake_extract_batch),
            patch.object(video_ocr, "_subtitle_text_for_frame", side_effect=fake_subtitle_text),
            patch.object(video_ocr, "normalize_segments", side_effect=keep_raw_segments),
        ):
            segments, diagnostics = video_ocr.extract_ocr_segments(
                str(video),
                processor,
                progress=lambda percent, detail: progress_events.append((percent, detail)),
            )

        assert extraction_calls == [
            (0.0, 60.0, 1.0),
            (60.0, 60.0, 1.0),
            (120.0, 5.0, 1.0),
        ]
        assert max_frames_on_disk == 60
        assert processor.calls == 125
        assert len(segments) == 125
        assert diagnostics["ocr_frame_count"] == 125
        assert diagnostics["ocr_segment_count"] == 125

        # The frame filename resets to zero in each FFmpeg batch, so the
        # timeline must use batch start + local frame index.
        assert segments[0].start_sec == 0.0
        assert segments[59].start_sec == 59.0
        assert segments[60].start_sec == 60.0
        assert segments[119].start_sec == 119.0
        assert segments[120].start_sec == 120.0
        assert segments[-1].start_sec == 124.0
        assert segments[-1].end_sec == 125.0
        assert progress_events[-1][0] == 100.0
        assert not (root / "ocr_frames").exists()


def test_cancellable_process_terminates_ffmpeg_and_raises() -> None:
    processes: list[Any] = []

    class StubProcess:
        def __init__(self, args: list[str], **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs
            self.returncode = None
            self.terminated = False
            self.killed = False
            self.communicated = False
            processes.append(self)

        def poll(self):
            return None

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        def wait(self, *, timeout: float):
            assert timeout == 5
            return self.returncode

        def communicate(self):
            self.communicated = True
            return "", ""

    with patch.object(video_ocr.subprocess, "Popen", StubProcess):
        try:
            video_ocr._run_process_cancellable(
                ["ffmpeg", "-i", "video.mp4"],
                cancelled=lambda: True,
            )
        except video_ocr.OCRExtractionCancelled as exc:
            assert "取消" in str(exc)
        else:
            raise AssertionError("cancellation must raise OCRExtractionCancelled")

    assert len(processes) == 1
    assert processes[0].terminated is True
    assert processes[0].killed is False
    assert processes[0].communicated is True


def test_ocr_cancellation_propagates_and_removes_current_batch() -> None:
    with tempfile.TemporaryDirectory(prefix="ocr-cancel-contract-") as temp_dir:
        root = Path(temp_dir)
        video = root / "video.mp4"
        video.touch()
        processor = StubProcessor()
        cancel_checks = 0
        extraction_calls = 0

        def cancelled() -> bool:
            nonlocal cancel_checks
            cancel_checks += 1
            # First check enters the batch; the next check occurs immediately
            # before OCR of its first frame.
            return cancel_checks >= 2

        def fake_extract_batch(
            _video_path: str,
            output_dir: Path,
            *,
            duration_sec: float,
            interval_sec: float,
            **_kwargs: Any,
        ) -> list[Path]:
            nonlocal extraction_calls
            extraction_calls += 1
            return _create_stub_batch(
                output_dir,
                duration_sec=duration_sec,
                interval_sec=interval_sec,
            )

        with (
            patch.object(
                video_ocr,
                "probe_video",
                return_value=video_ocr.VideoInfo(width=1920, height=1080, duration_sec=120.0),
            ),
            patch.object(video_ocr, "_extract_frame_batch", side_effect=fake_extract_batch),
        ):
            try:
                video_ocr.extract_ocr_segments(
                    str(video),
                    processor,
                    cancelled=cancelled,
                )
            except video_ocr.OCRExtractionCancelled as exc:
                assert "取消" in str(exc)
            else:
                raise AssertionError("OCR loop cancellation must propagate")

        assert extraction_calls == 1
        assert processor.calls == 0
        assert not (root / "ocr_frames").exists()


def main() -> int:
    tests = [
        test_ocr_uses_60_frame_batches_and_continuous_cross_batch_timeline,
        test_cancellable_process_terminates_ffmpeg_and_raises,
        test_ocr_cancellation_propagates_and_removes_current_batch,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASS ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
