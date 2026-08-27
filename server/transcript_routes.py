"""Shared transcript-route types and timeline cleanup.

Every text source (video OCR or ASR) is normalized into
``TranscriptSegment`` objects before it enters the existing DeepSeek publish
pipeline.  Keeping this module dependency-light also makes the route decision
logic testable without loading either FunASR or PaddleOCR.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


REQUESTED_ROUTES = frozenset({"auto", "ocr", "asr"})
RESOLVED_ROUTES = frozenset({"ocr", "asr"})

ROUTE_LABELS = {
    "auto": "自动判断",
    "ocr": "画面 OCR",
    "asr": "语音识别",
}


class InvalidTranscriptRoute(ValueError):
    """Raised when an API or persisted task contains an unknown route."""


class TranscriptRouteUnavailable(RuntimeError):
    """Raised when an explicitly requested route cannot process the video."""


def normalize_requested_route(value: str | None) -> str:
    route = (value or "auto").strip().lower()
    if route not in REQUESTED_ROUTES:
        choices = ", ".join(sorted(REQUESTED_ROUTES))
        raise InvalidTranscriptRoute(f"不支持的文本路线 {route!r}；可选值：{choices}")
    return route


@dataclass(frozen=True)
class TranscriptSegment:
    start_sec: float
    end_sec: float
    text: str
    confidence: float | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["start_sec"] = round(max(0.0, float(self.start_sec)), 3)
        data["end_sec"] = round(max(data["start_sec"], float(self.end_sec)), 3)
        if data["confidence"] is not None:
            data["confidence"] = round(float(data["confidence"]), 4)
        return data


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[\t\r\f\v ]+")
_COMPARE_RE = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)


def clean_segment_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG_RE.sub("", text)
    lines = [_SPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    return " ".join(line for line in lines if line).strip()


def _comparison_key(text: str) -> str:
    return _COMPARE_RE.sub("", text).casefold()


def _segments_similar(left: str, right: str) -> bool:
    a, b = _comparison_key(left), _comparison_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 3 and shorter in longer and len(shorter) / len(longer) >= 0.55:
        return True
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.92


def normalize_segments(
    segments: Iterable[TranscriptSegment],
    *,
    repeat_window_sec: float = 12.0,
) -> list[TranscriptSegment]:
    """Sort, clean, and merge adjacent repeated/incremental timeline cues."""

    cleaned = [
        TranscriptSegment(
            start_sec=max(0.0, float(segment.start_sec)),
            end_sec=max(float(segment.start_sec) + 0.05, float(segment.end_sec)),
            text=clean_segment_text(segment.text),
            confidence=segment.confidence,
            source=segment.source,
        )
        for segment in segments
        if clean_segment_text(segment.text)
    ]
    cleaned.sort(key=lambda cue: (cue.start_sec, cue.end_sec))

    result: list[TranscriptSegment] = []
    for cue in cleaned:
        if not result:
            result.append(cue)
            continue
        previous = result[-1]
        close_in_time = cue.start_sec <= previous.end_sec + repeat_window_sec
        if not close_in_time or not _segments_similar(previous.text, cue.text):
            result.append(cue)
            continue

        prev_key = _comparison_key(previous.text)
        cue_key = _comparison_key(cue.text)
        # Rolling captions often grow word by word.  Keep the most complete
        # version while extending its time span.  For OCR jitter, confidence is
        # the tie-breaker.
        previous_score = previous.confidence if previous.confidence is not None else -1.0
        cue_score = cue.confidence if cue.confidence is not None else -1.0
        use_cue_text = len(cue_key) > len(prev_key) or (
            len(cue_key) == len(prev_key) and cue_score > previous_score
        )
        result[-1] = TranscriptSegment(
            start_sec=previous.start_sec,
            end_sec=max(previous.end_sec, cue.end_sec),
            text=cue.text if use_cue_text else previous.text,
            confidence=max(previous_score, cue_score) if max(previous_score, cue_score) >= 0 else None,
            source=previous.source or cue.source,
        )
    return result


def transcript_text(segments: Iterable[TranscriptSegment]) -> str:
    return "\n".join(segment.text for segment in normalize_segments(segments)).strip()


def save_transcript_artifacts(
    task_id: str,
    segments: Iterable[TranscriptSegment],
    *,
    diagnostics: Mapping[str, Any] | None = None,
) -> tuple[str, str, list[TranscriptSegment]]:
    """Persist source-level raw text and structured timeline for comparison."""

    import config

    normalized = normalize_segments(segments)
    text = "\n".join(segment.text for segment in normalized).strip()
    directory = config.PROJECT_ROOT / "downloads" / "transcripts"
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = directory / f"{task_id}.raw.txt"
    segments_path = directory / f"{task_id}.segments.json"
    raw_path.write_text(text + ("\n" if text else ""), encoding="utf-8")
    payload = {
        "task_id": task_id,
        "segments": [segment.to_dict() for segment in normalized],
        "diagnostics": dict(diagnostics or {}),
    }
    segments_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return str(raw_path), str(segments_path), normalized
