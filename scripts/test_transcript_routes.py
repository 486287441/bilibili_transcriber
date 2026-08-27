"""Dependency-free contract tests for OCR/ASR route helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server.transcript_routes import (
    InvalidTranscriptRoute,
    TranscriptSegment,
    normalize_requested_route,
    normalize_segments,
    transcript_text,
)


def test_normalize_segments_sorts_and_merges_rolling_captions() -> None:
    cues = [
        TranscriptSegment(12.0, 13.0, "最后一句", source="ocr"),
        TranscriptSegment(4.0, 5.0, "今天我们讨论", confidence=0.7, source="ocr"),
        TranscriptSegment(5.0, 6.5, "今天我们讨论 AI", confidence=0.9, source="ocr"),
        TranscriptSegment(8.0, 9.0, "中间一句", source="ocr"),
    ]
    assert normalize_segments(cues) == [
        TranscriptSegment(4.0, 6.5, "今天我们讨论 AI", confidence=0.9, source="ocr"),
        TranscriptSegment(8.0, 9.0, "中间一句", source="ocr"),
        TranscriptSegment(12.0, 13.0, "最后一句", source="ocr"),
    ]


def test_normalize_segments_deduplicates_ocr_jitter_by_confidence() -> None:
    lower_confidence = "这是一个关于人工智能产业发展的完整句子"
    higher_confidence = "这是一个关于人工智能产业发晨的完整句子"
    cues = [
        TranscriptSegment(1.0, 2.0, lower_confidence, confidence=0.61, source="ocr"),
        TranscriptSegment(2.0, 3.0, higher_confidence, confidence=0.96, source="ocr"),
    ]
    assert normalize_segments(cues) == [
        TranscriptSegment(1.0, 3.0, higher_confidence, confidence=0.96, source="ocr")
    ]


def test_normalize_segments_deduplicates_adjacent_equivalent_text() -> None:
    cues = [
        TranscriptSegment(1.0, 2.0, "你好，世界", confidence=0.7, source="ocr"),
        TranscriptSegment(2.0, 3.0, "你好世界!", confidence=0.9, source="ocr"),
    ]
    assert normalize_segments(cues) == [
        TranscriptSegment(1.0, 3.0, "你好世界!", confidence=0.9, source="ocr")
    ]


def test_normalize_segments_keeps_repeats_outside_time_window() -> None:
    cues = [
        TranscriptSegment(0.0, 1.0, "章节标题"),
        TranscriptSegment(20.0, 21.0, "章节标题"),
    ]
    assert normalize_segments(cues, repeat_window_sec=12.0) == cues
    assert transcript_text(cues) == "章节标题\n章节标题"


def test_route_validation_and_normalization() -> None:
    assert normalize_requested_route(None) == "auto"
    assert normalize_requested_route("") == "auto"
    assert normalize_requested_route("  OCR ") == "ocr"
    assert normalize_requested_route("asr") == "asr"

    for removed_or_unknown in ("subtitle", "visual"):
        try:
            normalize_requested_route(removed_or_unknown)
        except InvalidTranscriptRoute as exc:
            assert removed_or_unknown in str(exc)
            assert all(route in str(exc) for route in ("auto", "ocr", "asr"))
        else:
            raise AssertionError("removed or unknown transcript route must be rejected")


def main() -> int:
    tests = [
        test_normalize_segments_sorts_and_merges_rolling_captions,
        test_normalize_segments_deduplicates_ocr_jitter_by_confidence,
        test_normalize_segments_deduplicates_adjacent_equivalent_text,
        test_normalize_segments_keeps_repeats_outside_time_window,
        test_route_validation_and_normalization,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASS ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
