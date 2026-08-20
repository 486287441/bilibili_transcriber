"""Manual GPU smoke test for the persistent isolated PP-OCRv5 runtime."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    # Match the server: Torch is loaded in the parent, Paddle stays in the OCR
    # child process so their Windows cuDNN DLLs cannot conflict.
    import torch

    from server.video_ocr import get_ocr_processor, release_ocr_processor

    with tempfile.TemporaryDirectory(prefix="ocr-gpu-smoke-") as temp_dir:
        image_path = Path(temp_dir) / "subtitle.png"
        image = Image.new("RGB", (960, 240), "black")
        ImageDraw.Draw(image).text((260, 100), "PP-OCRv5 GPU batch 123", fill="white")
        image.save(image_path)

        started = time.perf_counter()
        first = get_ocr_processor()
        load_sec = time.perf_counter() - started
        second = get_ocr_processor()
        batch_started = time.perf_counter()
        batches = first.recognize_many([image_path, image_path])
        first_batch_sec = time.perf_counter() - batch_started
        repeat_started = time.perf_counter()
        repeat_batches = first.recognize_many([image_path, image_path])
        repeat_batch_sec = time.perf_counter() - repeat_started
        result = {
            "torch_cuda": torch.cuda.is_available(),
            "ocr_device": getattr(first, "device", "local"),
            "singleton_reused": first is second,
            "batch_results": len(batches),
            "line_counts": [len(lines) for lines in batches],
            "load_sec": round(load_sec, 3),
            "first_batch_sec": round(first_batch_sec, 3),
            "repeat_batch_sec": round(repeat_batch_sec, 3),
        }
        print(json.dumps(result, ensure_ascii=False))
        assert result["torch_cuda"] is True
        assert result["ocr_device"].startswith("gpu")
        assert result["singleton_reused"] is True
        assert result["batch_results"] == 2
        assert len(repeat_batches) == 2
        release_ocr_processor()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
