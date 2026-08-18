"""Hard-subtitle detection and extraction with PaddleOCR PP-OCRv5."""

from __future__ import annotations

import gc
import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import config
from server.transcript_routes import TranscriptSegment, clean_segment_text, normalize_segments

logger = logging.getLogger("server.ocr")

ProgressCallback = Callable[[float, dict[str, Any]], None]
CancelCallback = Callable[[], bool]

_OCR_LOCK = threading.Lock()
_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".flv", ".m4v", ".ts"}
_TEXTISH_RE = re.compile(r"[\u3400-\u9fffA-Za-z]")
_ONLY_SYMBOLS_RE = re.compile(r"^[\W_]+$", re.UNICODE)


class PaddleOCRUnavailable(RuntimeError):
    pass


class OCRExtractionCancelled(RuntimeError):
    pass


@dataclass
class VideoInfo:
    width: int = 0
    height: int = 0
    duration_sec: float | None = None


@dataclass
class HardSubtitleDetection:
    found: bool
    confidence: float
    sampled_frames: int
    matched_frames: int
    distinct_texts: int
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hard_subtitle_found": self.found,
            "hard_subtitle_confidence": round(self.confidence, 3),
            "hard_subtitle_sampled_frames": self.sampled_frames,
            "hard_subtitle_matched_frames": self.matched_frames,
            "hard_subtitle_distinct_texts": self.distinct_texts,
            "hard_subtitle_examples": self.examples[:5],
            "ocr_model": "PaddleOCR PP-OCRv5",
        }


def _run_process(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=creationflags,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail[-1500:] or f"命令执行失败 ({result.returncode})")
    return result


def _run_process_cancellable(
    args: list[str],
    *,
    cancelled: CancelCallback | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run FFmpeg while still allowing queue cancellation and clean shutdown."""

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    started_at = time.monotonic()
    while process.poll() is None:
        if cancelled and cancelled():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.communicate()
            raise OCRExtractionCancelled("任务已取消")
        if timeout is not None and time.monotonic() - started_at > timeout:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            stdout, stderr = process.communicate()
            detail = (stderr or stdout or "").strip()
            raise RuntimeError(detail[-1500:] or "命令执行超时")
        time.sleep(0.2)

    stdout, stderr = process.communicate()
    if process.returncode != 0:
        detail = (stderr or stdout or "").strip()
        raise RuntimeError(detail[-1500:] or f"命令执行失败 ({process.returncode})")
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def probe_video(video_path: str) -> VideoInfo:
    from bilibili_transcriber import FFPROBE_EXE

    if not FFPROBE_EXE:
        raise RuntimeError("未检测到 ffprobe，无法分析 OCR 视频")
    result = _run_process(
        [
            FFPROBE_EXE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            video_path,
        ],
        timeout=60,
    )
    payload = json.loads(result.stdout or "{}")
    stream = next(iter(payload.get("streams") or []), {})
    duration = (payload.get("format") or {}).get("duration")
    try:
        duration_sec = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_sec = None
    return VideoInfo(
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        duration_sec=duration_sec,
    )


def _downloaded_video_path(info: Mapping[str, Any], task_dir: Path, ydl) -> Path | None:
    candidates: list[Path] = []
    for key in ("filepath", "_filename"):
        value = info.get(key)
        if value:
            candidates.append(Path(str(value)))
    for item in info.get("requested_downloads") or []:
        if isinstance(item, Mapping) and item.get("filepath"):
            candidates.append(Path(str(item["filepath"])))
    try:
        candidates.append(Path(ydl.prepare_filename(dict(info))))
    except Exception:
        pass
    candidates.extend(
        path for path in task_dir.iterdir() if path.is_file() and path.suffix.lower() in _VIDEO_EXTENSIONS
    )
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() in _VIDEO_EXTENSIONS:
            return candidate.resolve()
    return None


def download_video_for_ocr(
    url: str,
    task_id: str,
    *,
    progress_hook: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """Download one bandwidth-conscious video+audio file for OCR inspection."""

    from bilibili_transcriber import (
        _YTDLP_LOCK,
        _cleanup_download_artifacts,
        _task_download_dir,
        _ydl_opts_for_site,
        detect_site,
        format_ytdlp_error,
        yt_dlp,
    )

    task_dir = Path(_task_download_dir(task_id))
    _cleanup_download_artifacts(download_stem=task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    site = detect_site(url)
    opts = _ydl_opts_for_site(site, download_stem=task_id)
    opts.update(
        {
            "format": (
                "bestvideo[height<=720]+bestaudio/"
                "best[height<=720]/bestvideo+bestaudio/best"
            ),
            "outtmpl": str(task_dir / "source.%(ext)s"),
            "merge_output_format": "mp4",
            "postprocessors": [],
            "continuedl": False,
        }
    )
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]
    try:
        with _YTDLP_LOCK:
            with yt_dlp.YoutubeDL(opts) as ydl:
                raw_info = ydl.extract_info(url, download=True)
                info = raw_info if isinstance(raw_info, Mapping) else {}
                if info.get("_type") in {"playlist", "multi_video"}:
                    info = next(
                        (entry for entry in info.get("entries") or [] if isinstance(entry, Mapping)),
                        info,
                    )
                video_path = _downloaded_video_path(info, task_dir, ydl)
                if not video_path:
                    return None, None, "视频下载完成，但没有找到可供 OCR 的视频文件"
                meta = {
                    "title": str(info.get("title") or "未命名视频").strip(),
                    "url": str(info.get("webpage_url") or url).strip(),
                    "duration": info.get("duration"),
                }
                return str(video_path), meta, None
    except Exception as exc:
        return None, None, format_ytdlp_error(exc)


def extract_audio_from_video(
    video_path: str,
    task_id: str,
    *,
    cancelled: CancelCallback | None = None,
) -> str:
    """Extract WAV from the already downloaded inspection video for auto→ASR."""

    from bilibili_transcriber import FFMPEG_EXE, _task_download_dir

    if not FFMPEG_EXE:
        raise RuntimeError("未检测到 ffmpeg，无法从视频提取音频")
    output = Path(_task_download_dir(task_id)) / "audio.wav"
    _run_process_cancellable(
        [
            FFMPEG_EXE,
            "-loglevel",
            "error",
            "-y",
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output),
        ],
        cancelled=cancelled,
    )
    if not output.is_file():
        raise RuntimeError("从视频提取音频失败")
    return str(output)


def _result_mapping(result: Any) -> Mapping[str, Any]:
    payload = getattr(result, "json", result)
    if callable(payload):
        payload = payload()
    if isinstance(payload, Mapping) and isinstance(payload.get("res"), Mapping):
        payload = payload["res"]
    if isinstance(payload, Mapping):
        return payload
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value) if isinstance(value, (list, tuple)) else []


def _box_from_any(box: Any) -> tuple[float, float, float, float] | None:
    values = _as_list(box)
    if len(values) == 4 and all(isinstance(v, (int, float)) for v in values):
        x1, y1, x2, y2 = (float(v) for v in values)
        return x1, y1, x2, y2
    points = [_as_list(point) for point in values]
    coords = [point for point in points if len(point) >= 2]
    if not coords:
        return None
    xs = [float(point[0]) for point in coords]
    ys = [float(point[1]) for point in coords]
    return min(xs), min(ys), max(xs), max(ys)


@dataclass
class _OCRLine:
    text: str
    confidence: float
    box: tuple[float, float, float, float]


class PaddleOCRV5Processor:
    """One task-scoped PP-OCRv5 engine reused for detection and full OCR."""

    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise PaddleOCRUnavailable(
                "未安装 PaddleOCR。请安装 requirements.txt，并确保 PaddlePaddle 推理引擎可用"
            ) from exc

        kwargs: dict[str, Any] = {
            # Explicit v5 model names select the compact Chinese-capable pair;
            # PaddleOCR ignores ocr_version/lang when names are provided.
            "text_detection_model_name": getattr(
                config, "PADDLEOCR_DETECTION_MODEL", "PP-OCRv5_mobile_det"
            ),
            "text_recognition_model_name": getattr(
                config, "PADDLEOCR_RECOGNITION_MODEL", "PP-OCRv5_mobile_rec"
            ),
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            # PaddlePaddle 3.3.x on Windows can fail while converting oneDNN
            # attributes for PP-OCRv5. The regular CPU kernels are stable and
            # OCR is isolated from the existing FunASR GPU route anyway.
            "enable_mkldnn": False,
        }
        device = str(getattr(config, "PADDLEOCR_DEVICE", "auto") or "auto").strip()
        if device.lower() != "auto":
            kwargs["device"] = device
        try:
            self._engine = PaddleOCR(**kwargs)
        except Exception as exc:
            raise PaddleOCRUnavailable(f"PaddleOCR PP-OCRv5 加载失败: {exc}") from exc

    def close(self) -> None:
        self._engine = None
        gc.collect()
        try:
            import paddle

            if paddle.device.is_compiled_with_cuda():
                paddle.device.cuda.empty_cache()
        except Exception:
            pass

    def recognize_lines(self, image_path: Path) -> list[_OCRLine]:
        try:
            with _OCR_LOCK:
                results = list(self._engine.predict(str(image_path)))
        except Exception as exc:
            raise RuntimeError(f"PP-OCRv5 识别失败: {exc}") from exc
        lines: list[_OCRLine] = []
        threshold = float(getattr(config, "PADDLEOCR_MIN_SCORE", 0.62))
        for result in results:
            data = _result_mapping(result)
            texts = _as_list(data.get("rec_texts"))
            scores = _as_list(data.get("rec_scores"))
            boxes = _as_list(data.get("rec_boxes")) or _as_list(data.get("rec_polys"))
            for index, raw_text in enumerate(texts):
                text = clean_segment_text(raw_text)
                try:
                    score = float(scores[index]) if index < len(scores) else 0.0
                except (TypeError, ValueError):
                    score = 0.0
                box = _box_from_any(boxes[index]) if index < len(boxes) else None
                if (
                    not box
                    or score < threshold
                    or len(text) < 2
                    or _ONLY_SYMBOLS_RE.match(text)
                    or not _TEXTISH_RE.search(text)
                ):
                    continue
                lines.append(_OCRLine(text=text, confidence=score, box=box))
        return lines


def _subtitle_text_for_frame(
    lines: Iterable[_OCRLine],
    *,
    frame_width: int,
    frame_height: int,
) -> tuple[str, float] | None:
    width = max(1, frame_width)
    height = max(1, frame_height)
    eligible: list[_OCRLine] = []
    for line in lines:
        x1, y1, x2, y2 = line.box
        line_width = max(0.0, x2 - x1)
        center_x = (x1 + x2) / 2.0
        if not (0.18 * width <= center_x <= 0.82 * width):
            continue
        if line_width < 0.055 * width:
            continue
        # Extremely high text in the cropped region is usually a UI overlay.
        if (y1 + y2) / 2.0 < 0.05 * height:
            continue
        eligible.append(line)
    if not eligible:
        return None

    eligible.sort(key=lambda line: ((line.box[1] + line.box[3]) / 2.0, line.box[0]))
    groups: list[list[_OCRLine]] = []
    for line in eligible:
        cy = (line.box[1] + line.box[3]) / 2.0
        if groups:
            last_y = sum((item.box[1] + item.box[3]) / 2.0 for item in groups[-1]) / len(
                groups[-1]
            )
            if abs(cy - last_y) <= 0.075 * height:
                groups[-1].append(line)
                continue
        groups.append([line])

    ranked: list[tuple[float, float, str, float]] = []
    for group in groups:
        group.sort(key=lambda line: line.box[0])
        text = clean_segment_text(" ".join(line.text for line in group))
        x1 = min(line.box[0] for line in group)
        x2 = max(line.box[2] for line in group)
        cy = sum((line.box[1] + line.box[3]) / 2.0 for line in group) / len(group)
        confidence = sum(line.confidence for line in group) / len(group)
        width_ratio = min(1.0, max(0.0, x2 - x1) / width)
        center_bonus = 1.0 - min(1.0, abs(((x1 + x2) / 2.0) / width - 0.5) * 2)
        score = confidence + 0.45 * width_ratio + 0.15 * center_bonus
        if len(text) >= 2:
            ranked.append((score, cy, text, confidence))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    chosen = [ranked[0]]
    if len(ranked) > 1 and abs(ranked[1][1] - ranked[0][1]) <= 0.20 * height:
        chosen.append(ranked[1])
    chosen.sort(key=lambda item: item[1])
    return clean_segment_text(" ".join(item[2] for item in chosen)), sum(
        item[3] for item in chosen
    ) / len(chosen)


def _frame_filter() -> str:
    crop_ratio = min(0.65, max(0.25, float(getattr(config, "PADDLEOCR_CROP_RATIO", 0.45))))
    y_ratio = 1.0 - crop_ratio
    return (
        f"crop=iw:trunc(ih*{crop_ratio:.4f}/2)*2:0:trunc(ih*{y_ratio:.4f}/2)*2,"
        "scale=1280:-2"
    )


def _scaled_frame_height(info: VideoInfo) -> int:
    if info.width <= 0 or info.height <= 0:
        return 720
    crop_ratio = min(0.65, max(0.25, float(getattr(config, "PADDLEOCR_CROP_RATIO", 0.45))))
    return max(2, int(round(1280 * info.height * crop_ratio / info.width / 2) * 2))


def _extract_frame_at(video_path: str, timestamp: float, output: Path) -> None:
    from bilibili_transcriber import FFMPEG_EXE

    if not FFMPEG_EXE:
        raise RuntimeError("未检测到 ffmpeg，无法为 OCR 抽帧")
    _run_process(
        [
            FFMPEG_EXE,
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            video_path,
            "-vf",
            _frame_filter(),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(output),
        ],
        timeout=90,
    )


def _sample_timestamps(duration_sec: float | None, count: int) -> list[float]:
    count = max(4, count)
    if duration_sec and duration_sec > 2:
        return [duration_sec * (0.06 + 0.88 * index / (count - 1)) for index in range(count)]
    return [float(3 + index * 10) for index in range(count)]


def detect_hard_subtitles(
    video_path: str,
    processor: PaddleOCRV5Processor,
    *,
    duration_sec: float | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> HardSubtitleDetection:
    """Sample the lower frame area and require changing, centered OCR text."""

    info = probe_video(video_path)
    duration = duration_sec or info.duration_sec
    count = max(6, int(getattr(config, "PADDLEOCR_DETECTION_SAMPLES", 12)))
    timestamps = _sample_timestamps(duration, count)
    sample_dir = Path(video_path).parent / "ocr_detection"
    shutil.rmtree(sample_dir, ignore_errors=True)
    sample_dir.mkdir(parents=True, exist_ok=True)
    texts: list[str] = []
    try:
        for index, timestamp in enumerate(timestamps):
            if cancelled and cancelled():
                raise OCRExtractionCancelled("任务已取消")
            frame = sample_dir / f"sample_{index:03d}.jpg"
            _extract_frame_at(video_path, timestamp, frame)
            if not frame.is_file():
                continue
            candidate = _subtitle_text_for_frame(
                processor.recognize_lines(frame),
                frame_width=1280,
                frame_height=_scaled_frame_height(info),
            )
            if candidate and candidate[0]:
                texts.append(candidate[0])
            if progress:
                progress(
                    (index + 1) / len(timestamps) * 100.0,
                    {"message": "正在检测画面硬字幕", "sample": index + 1, "samples": len(timestamps)},
                )
    finally:
        shutil.rmtree(sample_dir, ignore_errors=True)

    keys = {re.sub(r"\W+", "", text).casefold() for text in texts if text}
    minimum_matches = max(2, math.ceil(len(timestamps) * 0.22))
    hit_ratio = len(texts) / max(1, len(timestamps))
    diversity = min(1.0, len(keys) / max(2, len(texts)))
    confidence = min(1.0, 0.6 * hit_ratio + 0.4 * diversity)
    found = len(texts) >= minimum_matches and len(keys) >= 2
    return HardSubtitleDetection(
        found=found,
        confidence=confidence,
        sampled_frames=len(timestamps),
        matched_frames=len(texts),
        distinct_texts=len(keys),
        examples=texts[:5],
    )


def _extract_frame_batch(
    video_path: str,
    output_dir: Path,
    *,
    start_sec: float,
    duration_sec: float,
    interval_sec: float,
    cancelled: CancelCallback | None = None,
) -> list[Path]:
    from bilibili_transcriber import FFMPEG_EXE

    if not FFMPEG_EXE:
        raise RuntimeError("未检测到 ffmpeg，无法为 OCR 抽帧")
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    fps = 1.0 / max(0.25, interval_sec)
    max_frames = max(1, math.ceil(duration_sec / max(0.25, interval_sec)))
    _run_process_cancellable(
        [
            FFMPEG_EXE,
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start_sec:.3f}",
            "-i",
            video_path,
            "-t",
            f"{duration_sec:.3f}",
            "-vf",
            f"fps={fps:.6f},{_frame_filter()}",
            "-frames:v",
            str(max_frames),
            "-q:v",
            "4",
            "-start_number",
            "0",
            str(output_dir / "frame_%08d.jpg"),
        ],
        cancelled=cancelled,
    )
    return sorted(output_dir.glob("frame_*.jpg"))


def extract_ocr_segments(
    video_path: str,
    processor: PaddleOCRV5Processor,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> tuple[list[TranscriptSegment], dict[str, Any]]:
    """OCR the subtitle region at a configurable cadence and merge repeats."""

    info = probe_video(video_path)
    interval = max(0.25, float(getattr(config, "PADDLEOCR_FRAME_INTERVAL_SEC", 1.0)))
    frames_dir = Path(video_path).parent / "ocr_frames"
    # Keep only a small window of frames on disk. This bounds storage for long
    # videos and gives cancellation a chance between (and during) FFmpeg batches.
    batch_frame_count = 60
    batch_duration = interval * batch_frame_count
    estimated_total = (
        max(1, math.ceil(info.duration_sec / interval))
        if info.duration_sec and info.duration_sec > 0
        else None
    )
    segments: list[TranscriptSegment] = []
    processed_frames = 0
    batch_index = 0
    try:
        while True:
            if cancelled and cancelled():
                raise OCRExtractionCancelled("任务已取消")
            start_sec = batch_index * batch_duration
            if info.duration_sec and start_sec >= info.duration_sec:
                break
            current_duration = batch_duration
            if info.duration_sec:
                current_duration = min(current_duration, max(0.01, info.duration_sec - start_sec))
            frames = _extract_frame_batch(
                video_path,
                frames_dir,
                start_sec=start_sec,
                duration_sec=current_duration,
                interval_sec=interval,
                cancelled=cancelled,
            )
            if not frames:
                break
            for frame_index, frame in enumerate(frames):
                if cancelled and cancelled():
                    raise OCRExtractionCancelled("任务已取消")
                candidate = _subtitle_text_for_frame(
                    processor.recognize_lines(frame),
                    frame_width=1280,
                    frame_height=_scaled_frame_height(info),
                )
                frame_start = start_sec + frame_index * interval
                if candidate and candidate[0]:
                    segments.append(
                        TranscriptSegment(
                            start_sec=frame_start,
                            end_sec=frame_start + interval,
                            text=candidate[0],
                            confidence=candidate[1],
                            source="ocr",
                        )
                    )
                processed_frames += 1
                try:
                    frame.unlink(missing_ok=True)
                except OSError:
                    pass
                if progress:
                    percent = (
                        processed_frames / estimated_total * 100.0
                        if estimated_total
                        else min(99.0, batch_index * 5.0 + (frame_index + 1) / len(frames) * 5.0)
                    )
                    progress(
                        min(100.0, percent),
                        {
                            "message": "PP-OCRv5 正在识别画面字幕",
                            "processed_frames": processed_frames,
                            "total_frames": estimated_total,
                        },
                    )
            batch_index += 1
            if not info.duration_sec and len(frames) < batch_frame_count:
                break
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)

    if not processed_frames:
        return [], {"ocr_model": "PaddleOCR PP-OCRv5", "ocr_frame_count": 0}

    normalized = normalize_segments(segments, repeat_window_sec=max(2.0, interval * 3))
    diagnostics = {
        "ocr_model": "PaddleOCR PP-OCRv5",
        "ocr_detection_model": getattr(
            config, "PADDLEOCR_DETECTION_MODEL", "PP-OCRv5_mobile_det"
        ),
        "ocr_recognition_model": getattr(
            config, "PADDLEOCR_RECOGNITION_MODEL", "PP-OCRv5_mobile_rec"
        ),
        "ocr_frame_interval_sec": interval,
        "ocr_frame_count": processed_frames,
        "ocr_segment_count": len(normalized),
    }
    return normalized, diagnostics
