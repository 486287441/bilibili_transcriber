"""Startup warmup: PyTorch runtime, bootstrap cache, lifecycle reconcile."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("server.warmup")


def warmup_pytorch() -> str:
    """Import PyTorch and touch CUDA — does not load SenseVoice weights."""
    t0 = time.monotonic()
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        name = torch.cuda.get_device_name(0)
        torch.cuda.empty_cache()
        logger.info(
            "PyTorch 预热完成 device=cuda (%s) (%.0fms)",
            name,
            (time.monotonic() - t0) * 1000,
        )
    else:
        logger.info(
            "PyTorch 预热完成 device=cpu (%.0fms)",
            (time.monotonic() - t0) * 1000,
        )

    from server import model_manager

    model_manager.warm_device_cache(device)
    return device


def warmup() -> None:
    """Block until PyTorch, data cache, and lifecycle reconcile are ready."""
    t0 = time.monotonic()
    try:
        warmup_pytorch()

        from server.model_lifecycle import reconcile_on_startup

        reconcile_on_startup()

        from server.bootstrap_cache import warm as warm_bootstrap

        warm_bootstrap()

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info("启动预热全部完成 (总计 %.0fms)", elapsed_ms)
    except Exception:
        logger.exception("启动预热失败")
