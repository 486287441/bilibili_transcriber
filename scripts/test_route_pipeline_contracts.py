"""Offline integration contracts for the worker transcript-route matrix.

These tests exercise ``WorkerService._process_task`` with in-memory queue and
model/media stubs.  They intentionally do not import FastAPI, FunASR,
PaddleOCR, yt-dlp, or make network requests.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@dataclass
class FakeTask:
    id: str
    url: str
    site: str
    requested_route: str
    source: str = "test"
    telegram_chat_id: int | None = None
    title: str | None = "测试视频"
    duration_sec: float | None = 60.0
    status: str = "downloading"
    position: int = 1
    retry_count: int = 0
    max_retries: int = 3
    error_message: str | None = None
    created_at: str = "2026-08-18T00:00:00+00:00"
    updated_at: str = "2026-08-18T00:00:00+00:00"
    started_at: str | None = None
    completed_at: str | None = None
    output_doc_url: str | None = None
    output_text_path: str | None = None
    reprocess_mode: str | None = None
    history_source_id: str | None = None
    local_audio_path: str | None = None
    resolved_route: str | None = None
    route_diagnostics: dict[str, Any] | None = None
    raw_text_path: str | None = None
    source_segments_path: str | None = None


class FakeQueueService:
    def __init__(self, task: FakeTask) -> None:
        self.task = task

    def get(self, task_id: str) -> FakeTask:
        assert task_id == self.task.id
        return self.task

    def is_cancel_requested(self, _task_id: str) -> bool:
        return False

    def update_metadata(
        self,
        task_id: str,
        *,
        title: str | None,
        duration_sec: float | None,
    ) -> FakeTask:
        task = self.get(task_id)
        task.title = title
        task.duration_sec = duration_sec
        return task

    def update_route_details(self, task_id: str, **fields: Any) -> FakeTask:
        task = self.get(task_id)
        for key, value in fields.items():
            setattr(task, key, value)
        return task

    def transition(self, task_id: str, status: str, **_extra: Any) -> FakeTask:
        task = self.get(task_id)
        task.status = status
        return task

    def complete(self, task_id: str, *, doc_url: str, text_path: str) -> FakeTask:
        task = self.get(task_id)
        task.status = "completed"
        task.output_doc_url = doc_url
        task.output_text_path = text_path
        return task

    def fail_permanently(self, task_id: str, message: str) -> FakeTask:
        task = self.get(task_id)
        task.status = "failed"
        task.error_message = message
        return task

    def handle_failure(self, task_id: str, message: str) -> FakeTask:
        task = self.get(task_id)
        task.status = "failed"
        task.error_message = message
        return task

    def delete(self, _task_id: str) -> None:
        return None

    def finish_cancel(self, _task_id: str, _old_status: str) -> None:
        return None


class NoOpProgressTracker:
    def start_task(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_phase(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def update(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def complete_task(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def clear_task(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_event_loop(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _install_module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    parent_name, _, child_name = name.rpartition(".")
    if parent_name and parent_name in sys.modules:
        setattr(sys.modules[parent_name], child_name, module)
    return module


def _unexpected(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("unconfigured worker dependency was called")


def _install_worker_import_stubs() -> None:
    import server

    config_module = ModuleType("config")
    config_module.PROJECT_ROOT = Path(tempfile.gettempdir()) / "route-pipeline-contracts"
    config_module.PADDLEOCR_DEVICE = "cpu"
    sys.modules["config"] = config_module

    no_op = lambda *_args, **_kwargs: None
    progress = NoOpProgressTracker()
    idle = SimpleNamespace(set_event_loop=no_op, set_transcribing=no_op)
    history = SimpleNamespace(set_event_loop=no_op, archive_task=no_op)
    ws = SimpleNamespace(broadcast=no_op)

    class PolishCancelled(RuntimeError):
        pass

    _install_module("server.activity", touch=no_op)
    _install_module(
        "server.model_manager",
        get_model=_unexpected,
        unload_model=no_op,
        is_model_loaded=lambda: False,
    )
    _install_module("server.progress_db", record_stats=no_op)
    _install_module("server.history_service", history_service=history)
    _install_module("server.idle_manager", idle_manager=idle)
    _install_module("server.metadata", schedule_metadata_fetch=no_op)
    _install_module(
        "server.pipeline_runner",
        PolishCancelled=PolishCancelled,
        download_video_with_progress=_unexpected,
        download_with_progress=_unexpected,
        polish_with_progress=_unexpected,
        transcribe_with_progress=_unexpected,
    )
    _install_module("server.polish_estimate", estimate_input_tokens=lambda value: value)
    _install_module(
        "server.settings_store",
        get_auto_fallback_route=lambda: "asr",
        should_auto_open_feishu=lambda: False,
    )
    _install_module("server.progress_tracker", progress_tracker=progress)
    _install_module("server.queue_db", TaskRow=FakeTask)

    class TaskNotFoundError(KeyError):
        pass

    _install_module(
        "server.queue_service",
        TaskNotFoundError=TaskNotFoundError,
        queue_service=SimpleNamespace(),
    )
    _install_module("server.runtime", set_processing=no_op, set_worker_state=no_op)
    _install_module("server.websocket_manager", ws_manager=ws)
    setattr(server, "__version__", getattr(server, "__version__", "test"))


_install_worker_import_stubs()

from server import worker as worker_module  # noqa: E402
from server.transcript_routes import TranscriptSegment, normalize_segments  # noqa: E402


class RouteHarness:
    def __init__(
        self,
        *,
        site: str,
        requested_route: str,
        subtitle_segments: list[TranscriptSegment] | None = None,
        subtitle_auth_error: bool = False,
        hard_subtitle_found: bool = False,
        ocr_segments: list[TranscriptSegment] | None = None,
        auto_fallback_route: str = "asr",
    ) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="route-contract-")
        self.root = Path(self._temp_dir.name)
        self.video_path = self.root / "video.mp4"
        self.audio_path = self.root / "audio.wav"
        self.video_path.touch()
        self.audio_path.touch()
        self.task = FakeTask(
            id=f"task-{site}-{requested_route}",
            url=(
                "https://www.bilibili.com/video/BV1contract"
                if site == "bilibili"
                else "https://www.youtube.com/watch?v=contract"
            ),
            site=site,
            requested_route=requested_route,
        )
        self.queue = FakeQueueService(self.task)
        self.subtitle_segments = list(subtitle_segments or [])
        self.subtitle_auth_error = subtitle_auth_error
        self.hard_subtitle_found = hard_subtitle_found
        self.ocr_segments = list(ocr_segments or [])
        self.auto_fallback_route = auto_fallback_route
        self.calls: dict[str, int] = {
            "subtitle_fetch": 0,
            "video_download": 0,
            "ocr_model_load": 0,
            "hard_subtitle_detect": 0,
            "ocr_extract": 0,
            "video_audio_extract": 0,
            "audio_download": 0,
            "asr_model_load": 0,
            "asr_transcribe": 0,
            "audio_cleanup": 0,
            "polish": 0,
        }
        self.final: FakeTask | None = None
        self._install_fakes()

    def close(self) -> None:
        self._temp_dir.cleanup()

    def __enter__(self) -> "RouteHarness":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _count(self, name: str) -> None:
        self.calls[name] += 1

    def _install_fakes(self) -> None:
        harness = self

        class SubtitleResult:
            def __init__(self) -> None:
                self.segments = list(harness.subtitle_segments)
                self.title = "字幕元数据标题"
                self.webpage_url = harness.task.url
                self.duration_sec = 60.0
                self.diagnostics = {
                    "platform_subtitle_found": bool(self.segments),
                }

            @property
            def found(self) -> bool:
                return bool(self.segments)

        def fetch_bilibili_subtitles(_url: str) -> SubtitleResult:
            self._count("subtitle_fetch")
            if self.subtitle_auth_error:
                raise BilibiliSubtitleAuthError("B站字幕鉴权失败：测试 Cookie 已失效")
            return SubtitleResult()

        class BilibiliSubtitleAuthError(RuntimeError):
            pass

        _install_module(
            "server.bilibili_subtitles",
            BilibiliSubtitleAuthError=BilibiliSubtitleAuthError,
            fetch_bilibili_subtitles=fetch_bilibili_subtitles,
        )

        class OCRExtractionCancelled(RuntimeError):
            pass

        class PaddleOCRUnavailable(RuntimeError):
            pass

        class PaddleOCRV5Processor:
            def __init__(processor_self) -> None:
                self._count("ocr_model_load")

            def close(processor_self) -> None:
                return None

        def get_ocr_processor() -> PaddleOCRV5Processor:
            return PaddleOCRV5Processor()

        def ocr_uses_gpu_runtime() -> bool:
            return False

        class Detection:
            found = self.hard_subtitle_found

            def to_dict(detection_self) -> dict[str, Any]:
                return {"hard_subtitle_found": detection_self.found}

        def detect_hard_subtitles(*_args: Any, **_kwargs: Any) -> Detection:
            self._count("hard_subtitle_detect")
            return Detection()

        def extract_ocr_segments(*_args: Any, **_kwargs: Any):
            self._count("ocr_extract")
            return list(self.ocr_segments), {"ocr_segment_count": len(self.ocr_segments)}

        def extract_audio_from_video(*_args: Any, **_kwargs: Any) -> str:
            self._count("video_audio_extract")
            return str(self.audio_path)

        _install_module(
            "server.video_ocr",
            OCRExtractionCancelled=OCRExtractionCancelled,
            PaddleOCRUnavailable=PaddleOCRUnavailable,
            PaddleOCRV5Processor=PaddleOCRV5Processor,
            get_ocr_processor=get_ocr_processor,
            ocr_uses_gpu_runtime=ocr_uses_gpu_runtime,
            detect_hard_subtitles=detect_hard_subtitles,
            extract_ocr_segments=extract_ocr_segments,
            extract_audio_from_video=extract_audio_from_video,
        )

        def download_video_with_progress(*_args: Any, **_kwargs: Any):
            self._count("video_download")
            return (
                str(self.video_path),
                {"title": "视频元数据标题", "url": self.task.url, "duration": 60.0},
                None,
            )

        def download_with_progress(*_args: Any, **_kwargs: Any):
            self._count("audio_download")
            return (
                str(self.audio_path),
                {"title": "音频元数据标题", "url": self.task.url, "duration": 60.0},
                None,
            )

        model_sentinel = object()

        def get_asr_model(**_kwargs: Any) -> object:
            self._count("asr_model_load")
            return model_sentinel

        class ModelLoadCancelled(RuntimeError):
            pass

        def transcribe_with_progress(
            _audio_path: str,
            model: object,
            *_args: Any,
            **_kwargs: Any,
        ) -> str:
            self._count("asr_transcribe")
            assert model is model_sentinel
            return "ASR 识别文本"

        def polish_with_progress(*_args: Any, **_kwargs: Any):
            self._count("polish")
            return True, "https://docs.example/result"

        def save_transcript_artifacts(
            _task_id: str,
            segments: list[TranscriptSegment],
            **_kwargs: Any,
        ):
            normalized = normalize_segments(segments)
            return str(self.root / "raw.txt"), str(self.root / "segments.json"), normalized

        worker_module.config.PROJECT_ROOT = self.root
        worker_module.config.PADDLEOCR_DEVICE = "cpu"
        worker_module.queue_service = self.queue
        worker_module.progress_tracker = NoOpProgressTracker()
        worker_module.download_video_with_progress = download_video_with_progress
        worker_module.download_with_progress = download_with_progress
        worker_module.transcribe_with_progress = transcribe_with_progress
        worker_module.polish_with_progress = polish_with_progress
        worker_module.save_transcript_artifacts = save_transcript_artifacts
        worker_module.should_auto_open_feishu = lambda: False
        worker_module.get_auto_fallback_route = lambda: self.auto_fallback_route
        worker_module.estimate_input_tokens = lambda value: value
        worker_module.model_manager = SimpleNamespace(
            get_model=get_asr_model,
            ModelLoadCancelled=ModelLoadCancelled,
            unload_model=lambda **_kwargs: None,
            is_model_loaded=lambda: False,
        )
        worker_module.idle_manager = SimpleNamespace(set_transcribing=lambda _value: None)
        worker_module.progress_db = SimpleNamespace(record_stats=lambda **_kwargs: None)

        self.service = worker_module.WorkerService()
        self.service._append_queue_log = lambda *_args, **_kwargs: None
        self.service._maybe_cleanup_audio = lambda audio, *_args, **_kwargs: (
            self._count("audio_cleanup") if audio else None
        )

        def finalize(
            _task: FakeTask,
            final: FakeTask,
            *,
            started_at: float,
            audio_file: str | None,
        ) -> None:
            del started_at, audio_file
            self.final = final

        self.service._finalize_task = finalize

    def run(self) -> FakeTask:
        self.service._process_task(self.task)
        assert self.final is not None
        return self.final


def _subtitle(text: str = "B站官方字幕") -> list[TranscriptSegment]:
    return [TranscriptSegment(0.0, 2.0, text, source="subtitle")]


def _ocr(text: str = "画面硬字幕") -> list[TranscriptSegment]:
    return [TranscriptSegment(0.0, 2.0, text, confidence=0.95, source="ocr")]


def test_auto_bilibili_subtitle_does_not_load_ocr_or_asr() -> None:
    with RouteHarness(
        site="bilibili",
        requested_route="auto",
        subtitle_segments=_subtitle(),
    ) as harness:
        final = harness.run()

        assert final.status == "completed"
        assert final.resolved_route == "subtitle"
        assert harness.calls["subtitle_fetch"] == 1
        assert harness.calls["video_download"] == 0
        assert harness.calls["ocr_model_load"] == 0
        assert harness.calls["asr_model_load"] == 0
        assert harness.calls["asr_transcribe"] == 0


def test_auto_without_platform_subtitle_uses_configured_ocr_only() -> None:
    with RouteHarness(
        site="bilibili",
        requested_route="auto",
        ocr_segments=_ocr(),
        auto_fallback_route="ocr",
    ) as harness:
        final = harness.run()

        assert final.status == "completed"
        assert final.resolved_route == "ocr"
        assert harness.calls["subtitle_fetch"] == 1
        assert harness.calls["video_download"] == 1
        assert harness.calls["ocr_model_load"] == 1
        assert harness.calls["hard_subtitle_detect"] == 0
        assert harness.calls["ocr_extract"] == 1
        assert harness.calls["asr_model_load"] == 0
        assert harness.calls["asr_transcribe"] == 0


def test_auto_auth_failure_uses_configured_ocr_fallback() -> None:
    with RouteHarness(
        site="bilibili",
        requested_route="auto",
        subtitle_auth_error=True,
        ocr_segments=_ocr(),
        auto_fallback_route="ocr",
    ) as harness:
        final = harness.run()

        assert final.status == "completed"
        assert final.resolved_route == "ocr"
        assert final.route_diagnostics["platform_subtitle_auth_failed"] is True
        assert "鉴权失败" in final.route_diagnostics["platform_subtitle_probe_error"]
        assert harness.calls["subtitle_fetch"] == 1
        assert harness.calls["ocr_extract"] == 1


def test_auto_without_any_subtitle_falls_back_to_asr() -> None:
    with RouteHarness(
        site="bilibili",
        requested_route="auto",
        auto_fallback_route="asr",
    ) as harness:
        final = harness.run()

        assert final.status == "completed"
        assert final.resolved_route == "asr"
        assert harness.calls["subtitle_fetch"] == 1
        assert harness.calls["video_download"] == 0
        assert harness.calls["hard_subtitle_detect"] == 0
        assert harness.calls["ocr_extract"] == 0
        assert harness.calls["video_audio_extract"] == 0
        assert harness.calls["audio_download"] == 1
        assert harness.calls["asr_model_load"] == 1
        assert harness.calls["asr_transcribe"] == 1
        assert harness.calls["audio_cleanup"] == 1


def test_explicit_ocr_empty_result_fails_without_asr_fallback() -> None:
    with RouteHarness(
        site="bilibili",
        requested_route="ocr",
        ocr_segments=[],
    ) as harness:
        final = harness.run()

        assert final.status == "failed"
        assert final.resolved_route == "ocr"
        assert "未从画面底部识别到可用字幕" in (final.error_message or "")
        assert harness.calls["subtitle_fetch"] == 0
        assert harness.calls["hard_subtitle_detect"] == 0
        assert harness.calls["ocr_extract"] == 1
        assert harness.calls["video_audio_extract"] == 0
        assert harness.calls["audio_download"] == 0
        assert harness.calls["asr_model_load"] == 0
        assert harness.calls["asr_transcribe"] == 0


def test_non_bilibili_auto_goes_directly_to_asr() -> None:
    with RouteHarness(site="youtube", requested_route="auto") as harness:
        final = harness.run()

        assert final.status == "completed"
        assert final.resolved_route == "asr"
        assert harness.calls["subtitle_fetch"] == 0
        assert harness.calls["video_download"] == 0
        assert harness.calls["ocr_model_load"] == 0
        assert harness.calls["audio_download"] == 1
        assert harness.calls["asr_model_load"] == 1
        assert harness.calls["asr_transcribe"] == 1
        assert harness.calls["audio_cleanup"] == 1


def test_auto_configured_ocr_empty_fails_without_asr_fallback() -> None:
    with RouteHarness(
        site="bilibili",
        requested_route="auto",
        ocr_segments=[],
        auto_fallback_route="ocr",
    ) as harness:
        final = harness.run()

        assert final.status == "failed"
        assert final.resolved_route == "ocr"
        assert harness.calls["ocr_extract"] == 1
        assert harness.calls["audio_download"] == 0
        assert harness.calls["asr_model_load"] == 0


def main() -> int:
    tests = [
        test_auto_bilibili_subtitle_does_not_load_ocr_or_asr,
        test_auto_without_platform_subtitle_uses_configured_ocr_only,
        test_auto_auth_failure_uses_configured_ocr_fallback,
        test_auto_without_any_subtitle_falls_back_to_asr,
        test_explicit_ocr_empty_result_fails_without_asr_fallback,
        test_non_bilibili_auto_goes_directly_to_asr,
        test_auto_configured_ocr_empty_fails_without_asr_fallback,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASS ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
