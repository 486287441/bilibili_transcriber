"""Shared transcript-route types, subtitle parsing, and timeline cleanup.

Every text source (platform subtitles, video OCR, or ASR) is normalized into
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
from typing import Any, Iterable, Mapping, Sequence


REQUESTED_ROUTES = frozenset({"auto", "subtitle", "ocr", "asr"})
RESOLVED_ROUTES = frozenset({"subtitle", "ocr", "asr"})

ROUTE_LABELS = {
    "auto": "自动判断",
    "subtitle": "B站字幕",
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
_CUE_NUMBER_RE = re.compile(r"^\s*\d+\s*$")
_TIMING_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3})"
)
_COMPARE_RE = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)


def clean_segment_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG_RE.sub("", text)
    lines = [_SPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    return " ".join(line for line in lines if line).strip()


def _timestamp_seconds(value: str) -> float:
    fields = value.strip().replace(",", ".").split(":")
    if len(fields) == 2:
        minutes, seconds = fields
        return int(minutes) * 60 + float(seconds)
    if len(fields) == 3:
        hours, minutes, seconds = fields
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise ValueError(f"invalid subtitle timestamp: {value}")


def parse_srt_or_vtt(text: str, *, source: str = "subtitle") -> list[TranscriptSegment]:
    """Parse common SRT/WebVTT cues, ignoring style/header blocks."""

    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized)
    segments: list[TranscriptSegment] = []
    for block in blocks:
        lines = [line.strip("\ufeff ") for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if lines[0].upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing_idx = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_idx < 0:
            continue
        match = _TIMING_RE.search(lines[timing_idx])
        if not match:
            continue
        cue_text = clean_segment_text("\n".join(lines[timing_idx + 1 :]))
        if not cue_text:
            continue
        segments.append(
            TranscriptSegment(
                start_sec=_timestamp_seconds(match.group("start")),
                end_sec=_timestamp_seconds(match.group("end")),
                text=cue_text,
                source=source,
            )
        )
    return segments


def _coerce_seconds(value: Any, *, milliseconds: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number / 1000.0 if milliseconds else number


def _segments_from_json(data: Any, *, source: str) -> list[TranscriptSegment]:
    if isinstance(data, Mapping) and isinstance(data.get("body"), list):
        return [
            TranscriptSegment(
                start_sec=_coerce_seconds(item.get("from")),
                end_sec=_coerce_seconds(item.get("to")),
                text=clean_segment_text(item.get("content")),
                confidence=_optional_float(item.get("confidence")),
                source=source,
            )
            for item in data["body"]
            if isinstance(item, Mapping) and clean_segment_text(item.get("content"))
        ]

    # YouTube json3 and other yt-dlp JSON subtitle formats.
    if isinstance(data, Mapping) and isinstance(data.get("events"), list):
        result: list[TranscriptSegment] = []
        for event in data["events"]:
            if not isinstance(event, Mapping):
                continue
            cue_text = clean_segment_text(
                "".join(
                    str(seg.get("utf8") or "")
                    for seg in event.get("segs") or []
                    if isinstance(seg, Mapping)
                )
            )
            if not cue_text:
                continue
            start = _coerce_seconds(event.get("tStartMs"), milliseconds=True)
            duration = _coerce_seconds(event.get("dDurationMs"), milliseconds=True)
            result.append(
                TranscriptSegment(start, start + max(duration, 0.1), cue_text, source=source)
            )
        return result

    items: Any = data
    if isinstance(data, Mapping):
        for key in ("subtitles", "captions", "segments", "items"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    if not isinstance(items, list):
        return []

    result = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        cue_text = clean_segment_text(
            item.get("content") or item.get("text") or item.get("caption")
        )
        if not cue_text:
            continue
        uses_ms = "start_ms" in item or "end_ms" in item
        start = _coerce_seconds(
            item.get("start_ms", item.get("start", item.get("from", 0))),
            milliseconds=uses_ms,
        )
        end = _coerce_seconds(
            item.get("end_ms", item.get("end", item.get("to", start + 1))),
            milliseconds=uses_ms,
        )
        result.append(
            TranscriptSegment(
                start_sec=start,
                end_sec=max(start + 0.1, end),
                text=cue_text,
                confidence=_optional_float(item.get("confidence") or item.get("score")),
                source=source,
            )
        )
    return result


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_subtitle_payload(
    payload: str | bytes | Mapping[str, Any] | Sequence[Any],
    *,
    ext: str | None = None,
    source: str = "subtitle",
) -> list[TranscriptSegment]:
    """Parse a subtitle payload returned by yt-dlp or Bilibili's subtitle API."""

    if isinstance(payload, bytes):
        payload = payload.decode("utf-8-sig", errors="replace")
    if isinstance(payload, (Mapping, list, tuple)):
        return _segments_from_json(payload, source=source)

    text = str(payload or "").lstrip("\ufeff")
    suffix = (ext or "").lower().lstrip(".")
    if suffix in {"json", "json3"} or text.lstrip().startswith(("{", "[")):
        try:
            return _segments_from_json(json.loads(text), source=source)
        except json.JSONDecodeError:
            if suffix in {"json", "json3"}:
                return []
    return parse_srt_or_vtt(text, source=source)


def choose_subtitle_track(
    subtitles: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> tuple[str, Mapping[str, Any]] | None:
    """Choose a real subtitle track, explicitly excluding Bilibili danmaku XML."""

    if not subtitles:
        return None

    def language_rank(language: str) -> tuple[int, str]:
        lang = language.lower().replace("_", "-")
        if lang == "danmaku":
            return (10_000, lang)
        automated = any(marker in lang for marker in ("ai", "auto", "machine"))
        if lang in {"zh-hans", "zh-cn", "zh-sg"}:
            base = 0
        elif lang == "zh" or lang.startswith("zh-"):
            base = 2
        elif lang in {"zho", "chi"}:
            base = 4
        else:
            base = 20
        return (base + (10 if automated else 0), lang)

    candidates: list[tuple[tuple[int, str], int, str, Mapping[str, Any]]] = []
    for language, tracks in subtitles.items():
        if language.lower() == "danmaku":
            continue
        for track in tracks or []:
            if not isinstance(track, Mapping):
                continue
            ext = str(track.get("ext") or "").lower()
            if ext == "xml" or not (track.get("data") is not None or track.get("url")):
                continue
            # Embedded data avoids a second network request and is what yt-dlp's
            # Bilibili extractor currently exposes for CC subtitles.
            track_rank = 0 if track.get("data") is not None else 1
            candidates.append((language_rank(language), track_rank, language, track))
    if not candidates:
        return None
    _, _, language, track = min(candidates, key=lambda item: (item[0], item[1]))
    return language, track


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
