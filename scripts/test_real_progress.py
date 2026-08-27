"""Fast unit checks for real ASR and streamed polish progress adapters."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_asr_vad_batch_progress() -> None:
    from bilibili_transcriber import _generate_with_vad_progress

    class FakeModel:
        vad_model = object()
        model = object()
        kwargs = {"frontend": SimpleNamespace(fs=10)}

        def inference(self, *args, **kwargs):
            if kwargs.get("model") is self.vad_model:
                return [{"value": [[0, 10_000], [20_000, 40_000]]}]
            return [{"text": "ok"}]

        def generate(self, **_kwargs):
            self.inference("audio", model=self.vad_model)
            self.inference([[0] * 100], model=self.model)
            self.inference([[0] * 200], model=self.model)
            return [{"text": "ok"}]

    events = []
    result = _generate_with_vad_progress(FakeModel(), "audio.wav", events.append)
    assert result[0]["text"] == "ok"
    assert [event["stage"] for event in events] == [
        "vad_complete",
        "asr_batch_complete",
        "asr_batch_complete",
    ]
    assert events[-1]["processed_speech_sec"] == 30.0
    assert events[-1]["total_speech_sec"] == 30.0


def test_deepseek_stream_assembly() -> None:
    import deepseek_client

    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="甲"))],
            usage=None,
        ),
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="乙"))],
            usage=None,
        ),
        SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(completion_tokens=2),
        ),
    ]

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["stream"] is True
            assert kwargs["stream_options"] == {"include_usage": True}
            return iter(chunks)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    original_client = deepseek_client._client
    events = []
    deepseek_client._client = lambda: fake_client
    try:
        result = deepseek_client._completion("system", "user", progress_callback=events.append)
    finally:
        deepseek_client._client = original_client

    assert result == "甲乙"
    assert events[-1]["done"] is True
    assert events[-1]["output_chars"] == 2
    assert events[-1]["completion_tokens"] == 2


def main() -> int:
    test_asr_vad_batch_progress()
    test_deepseek_stream_assembly()
    print("REAL PROGRESS TESTS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
