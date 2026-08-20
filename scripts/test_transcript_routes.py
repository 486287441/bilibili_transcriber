"""Dependency-free contract tests for transcript source routing helpers.

Run directly from the project root::

    python scripts/test_transcript_routes.py

The fixtures are deliberately local strings so this suite never needs a
Bilibili login, network access, FFmpeg, FunASR, or an OCR runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server.transcript_routes import (
    InvalidTranscriptRoute,
    TranscriptSegment,
    choose_subtitle_track,
    normalize_requested_route,
    normalize_segments,
    parse_srt_or_vtt,
    parse_subtitle_payload,
    transcript_text,
)


def test_parse_srt_cues() -> None:
    payload = """\
1
00:00:01,250 --> 00:00:03,500
<font color=\"white\">你好 &amp; world</font>
下一行

2
00:01:02,000 --> 00:01:04,125
第二条字幕
"""

    cues = parse_srt_or_vtt(payload, source="bilibili_subtitle")

    assert cues == [
        TranscriptSegment(1.25, 3.5, "你好 & world 下一行", source="bilibili_subtitle"),
        TranscriptSegment(62.0, 64.125, "第二条字幕", source="bilibili_subtitle"),
    ]


def test_parse_webvtt_cues_and_ignore_metadata_blocks() -> None:
    payload = """\
\ufeffWEBVTT - generated captions

NOTE this block is metadata
it must not become transcript text

cue-one
00:01.000 --> 00:02.250 align:start position:10%
<c.green>第一行</c>

STYLE
::cue { color: white; }

00:02.250 --> 00:04.000
第二行
"""

    cues = parse_subtitle_payload(payload.encode("utf-8"), ext="vtt")

    assert [(cue.start_sec, cue.end_sec, cue.text) for cue in cues] == [
        (1.0, 2.25, "第一行"),
        (2.25, 4.0, "第二行"),
    ]


def test_parse_bilibili_json_cues() -> None:
    payload = {
        "body": [
            {"from": 2.5, "to": 4.0, "content": " 第二条 ", "confidence": "0.91"},
            {"from": 0, "to": 1.25, "content": "<b>第一条</b>"},
            {"from": 4.0, "to": 5.0, "content": "   "},
        ]
    }

    cues = parse_subtitle_payload(payload, ext="json", source="bilibili_subtitle")

    assert cues == [
        TranscriptSegment(2.5, 4.0, "第二条", confidence=0.91, source="bilibili_subtitle"),
        TranscriptSegment(0.0, 1.25, "第一条", source="bilibili_subtitle"),
    ]


def test_parse_json3_and_generic_millisecond_cues() -> None:
    json3 = """{
      "events": [
        {"tStartMs": 1500, "dDurationMs": 750,
         "segs": [{"utf8": "你"}, {"utf8": "好"}]},
        {"tStartMs": 3000, "dDurationMs": 0,
         "segs": [{"utf8": "下一句"}]}
      ]
    }"""
    generic = {
        "segments": [
            {"start_ms": 1250, "end_ms": 2750, "text": "毫秒字幕", "score": 0.8}
        ]
    }

    json3_cues = parse_subtitle_payload(json3, ext="json3")
    generic_cues = parse_subtitle_payload(generic)

    assert json3_cues == [
        TranscriptSegment(1.5, 2.25, "你好", source="subtitle"),
        TranscriptSegment(3.0, 3.1, "下一句", source="subtitle"),
    ]
    assert generic_cues == [
        TranscriptSegment(1.25, 2.75, "毫秒字幕", confidence=0.8, source="subtitle")
    ]


def test_choose_subtitle_track_filters_danmaku_and_prefers_chinese() -> None:
    english_track = {"ext": "vtt", "data": "english"}
    automatic_chinese = {"ext": "srt", "data": "机器字幕"}
    manual_chinese = {"ext": "srt", "data": "人工字幕"}
    tracks = {
        "danmaku": [{"ext": "xml", "url": "https://comment.example/1.xml"}],
        "en": [english_track],
        "ai-zh": [automatic_chinese],
        "zh-Hans": [manual_chinese],
    }

    selected = choose_subtitle_track(tracks)

    assert selected == ("zh-Hans", manual_chinese)


def test_choose_subtitle_track_prefers_ai_zh_over_other_ai_languages() -> None:
    tracks = {
        language: [{"ext": "srt", "data": language}]
        for language in ("ai-ar", "ai-en", "ai-es", "ai-ja", "ai-pt", "ai-zh")
    }

    selected = choose_subtitle_track(tracks)

    assert selected == ("ai-zh", {"ext": "srt", "data": "ai-zh"})


def test_choose_subtitle_track_prefers_ai_zh_over_ai_en_when_both_present() -> None:
    chinese = {"ext": "srt", "data": "中文"}
    english = {"ext": "srt", "data": "english"}

    selected = choose_subtitle_track({"ai-en": [english], "ai-zh": [chinese]})

    assert selected == ("ai-zh", chinese)


def test_choose_subtitle_track_prefers_embedded_data_and_rejects_xml() -> None:
    remote = {"ext": "srt", "url": "https://subtitle.example/remote.srt"}
    embedded = {"ext": "srt", "data": "embedded subtitle"}

    assert choose_subtitle_track({"zh-CN": [remote, embedded]}) == ("zh-CN", embedded)
    assert choose_subtitle_track(
        {
            "danmaku": [{"ext": "xml", "data": "<i>not a subtitle</i>"}],
            "zh-CN": [{"ext": "xml", "url": "https://example.invalid/comments.xml"}],
        }
    ) is None
    assert choose_subtitle_track(None) is None


def test_normalize_segments_sorts_and_merges_rolling_captions() -> None:
    cues = [
        TranscriptSegment(12.0, 13.0, "最后一句", source="ocr"),
        TranscriptSegment(4.0, 5.0, "今天我们讨论", confidence=0.7, source="ocr"),
        TranscriptSegment(5.0, 6.5, "今天我们讨论 AI", confidence=0.9, source="ocr"),
        TranscriptSegment(8.0, 9.0, "中间一句", source="ocr"),
    ]

    normalized = normalize_segments(cues)

    assert normalized == [
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

    normalized = normalize_segments(cues)

    assert normalized == [
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
    assert normalize_requested_route("SUBTITLE") == "subtitle"
    assert normalize_requested_route("asr") == "asr"

    try:
        normalize_requested_route("visual")
    except InvalidTranscriptRoute as exc:
        assert "visual" in str(exc)
        assert all(route in str(exc) for route in ("auto", "subtitle", "ocr", "asr"))
    else:
        raise AssertionError("unknown transcript route must be rejected")


def main() -> int:
    tests = [
        test_parse_srt_cues,
        test_parse_webvtt_cues_and_ignore_metadata_blocks,
        test_parse_bilibili_json_cues,
        test_parse_json3_and_generic_millisecond_cues,
        test_choose_subtitle_track_filters_danmaku_and_prefers_chinese,
        test_choose_subtitle_track_prefers_ai_zh_over_other_ai_languages,
        test_choose_subtitle_track_prefers_ai_zh_over_ai_en_when_both_present,
        test_choose_subtitle_track_prefers_embedded_data_and_rejects_xml,
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
