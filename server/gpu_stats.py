"""GPU memory usage for status API."""

from __future__ import annotations


def gpu_status_fields() -> dict:
    """Return CUDA memory stats for the current PyTorch process (device 0)."""
    empty = {
        "gpu_available": False,
        "gpu_device": None,
        "gpu_memory_allocated_bytes": None,
        "gpu_memory_reserved_bytes": None,
        "gpu_memory_total_bytes": None,
    }
    try:
        import torch
    except ImportError:
        return empty

    if not torch.cuda.is_available():
        return empty

    device_index = 0
    try:
        props = torch.cuda.get_device_properties(device_index)
        return {
            "gpu_available": True,
            "gpu_device": torch.cuda.get_device_name(device_index),
            "gpu_memory_allocated_bytes": int(torch.cuda.memory_allocated(device_index)),
            "gpu_memory_reserved_bytes": int(torch.cuda.memory_reserved(device_index)),
            "gpu_memory_total_bytes": int(props.total_memory),
        }
    except Exception:
        return empty
