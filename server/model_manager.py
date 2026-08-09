"""ASR model lazy/eager loading, idle unload, and GPU release."""

from __future__ import annotations

import asyncio
import logging
import threading
import time

logger = logging.getLogger("server.model")

LOAD_TIMEOUT_SEC = 300.0

_model = None
_model_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_loading = False
_load_started_at: float | None = None
_device_cache: str | None = None


def warm_device_cache(device: str) -> None:
    global _device_cache
    _device_cache = device


def _runtime_device() -> str:
    global _device_cache
    if _device_cache is not None:
        return _device_cache
    try:
        from bilibili_transcriber import DEVICE

        _device_cache = DEVICE
    except ImportError:
        _device_cache = "cpu"
    return _device_cache


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def is_model_loaded() -> bool:
    return _model is not None


def is_loading() -> bool:
    return _loading


def load_elapsed_seconds() -> float:
    if not _loading or _load_started_at is None:
        return 0.0
    return max(0.0, time.monotonic() - _load_started_at)


def status_fields() -> dict:
    from server import progress_db
    from server.gpu_stats import gpu_status_fields
    from server.model_lifecycle import lifecycle_fields

    eta = progress_db.estimate_model_load_seconds(device=_runtime_device())
    fields = {
        "model_load_eta_seconds": int(eta),
        "model_load_elapsed_seconds": round(load_elapsed_seconds(), 1),
    }
    fields.update(lifecycle_fields())
    fields.update(gpu_status_fields())
    return fields


def _emit(event_type: str, payload: dict | None = None) -> None:
    if not _loop:
        return
    from server.websocket_manager import ws_manager

    asyncio.run_coroutine_threadsafe(
        ws_manager.broadcast(event_type, payload or {}),
        _loop,
    )


def get_model(*, emit_event: bool = True):
    """Load model on first use (lazy). Thread-safe singleton."""
    global _model, _loading, _load_started_at
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model
        _loading = True
        _load_started_at = time.monotonic()
        logger.info("正在加载 Fun-ASR-Nano-2512 模型…")

        from server import progress_db

        try:
            from bilibili_transcriber import DEVICE, load_asr_model
        except ImportError:
            DEVICE = "cpu"
            from bilibili_transcriber import load_asr_model

        warm_device_cache(DEVICE)

        eta = progress_db.estimate_model_load_seconds(device=DEVICE)
        if emit_event:
            _emit(
                "model.loading",
                {"message": "正在加载模型", "eta_seconds": int(eta)},
            )
        start = time.monotonic()
        try:
            loaded = load_asr_model()
            elapsed = time.monotonic() - start
            if elapsed > LOAD_TIMEOUT_SEC:
                raise TimeoutError("模型加载超时")
            _model = loaded
            progress_db.record_model_load(load_sec=elapsed, device=DEVICE)
            from server.model_lifecycle import record_loaded

            record_loaded()
            logger.info("Fun-ASR-Nano-2512 模型加载完成 (%.1fs)", elapsed)
            if emit_event:
                _emit("model.loaded", {"load_sec": round(elapsed, 1)})
            return _model
        finally:
            _loading = False
            _load_started_at = None


def preload_model_async() -> None:
    def _load() -> None:
        try:
            get_model()
        except Exception:
            logger.exception("预加载模型失败")

    threading.Thread(target=_load, name="model-preload", daemon=True).start()


def unload_model(*, emit_event: bool = False, unload_source: str = "unload") -> bool:
    """Release model reference and clear GPU cache. Returns True if unloaded."""
    global _model
    with _model_lock:
        if _model is None:
            return False
        logger.info("正在卸载 Fun-ASR-Nano-2512 模型并释放显存")
        _model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            logger.exception("释放 GPU 显存失败")
        from server.model_lifecycle import record_unloaded

        record_unloaded(source=unload_source)
        if emit_event:
            _emit("model.unloaded", {})
        return True
