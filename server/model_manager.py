"""SenseVoice model lazy/eager loading, idle unload, and GPU release."""

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

    try:
        from bilibili_transcriber import DEVICE
    except ImportError:
        DEVICE = "cpu"

    eta = progress_db.estimate_model_load_seconds(device=DEVICE)
    return {
        "model_load_eta_seconds": int(eta),
        "model_load_elapsed_seconds": round(load_elapsed_seconds(), 1),
    }


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
        logger.info("正在加载 SenseVoice 模型…")

        from server import progress_db

        try:
            from bilibili_transcriber import DEVICE, load_sensevoice_model
        except ImportError:
            DEVICE = "cpu"
            from bilibili_transcriber import load_sensevoice_model

        eta = progress_db.estimate_model_load_seconds(device=DEVICE)
        if emit_event:
            _emit(
                "model.loading",
                {"message": "正在加载模型", "eta_seconds": int(eta)},
            )
        start = time.monotonic()
        try:
            loaded = load_sensevoice_model()
            elapsed = time.monotonic() - start
            if elapsed > LOAD_TIMEOUT_SEC:
                raise TimeoutError("模型加载超时")
            _model = loaded
            progress_db.record_model_load(load_sec=elapsed, device=DEVICE)
            logger.info("SenseVoice 模型加载完成 (%.1fs)", elapsed)
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


def unload_model(*, emit_event: bool = False) -> bool:
    """Release model reference and clear GPU cache. Returns True if unloaded."""
    global _model
    with _model_lock:
        if _model is None:
            return False
        logger.info("正在卸载 SenseVoice 模型并释放显存")
        _model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            logger.exception("释放 GPU 显存失败")
        if emit_event:
            _emit("model.unloaded", {})
        return True
