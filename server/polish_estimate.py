"""DeepSeek polish-phase duration estimation (TTFT + generation)."""

from __future__ import annotations

import math
import statistics
from typing import Callable
from urllib.parse import urlparse

import config
from prompts import build_polish_user_message, render_polish_system
from server.settings_store import (
    get_deepseek_model,
    get_polish_prompt_template,
    get_transcript_correction_prompt,
)

# Chinese-heavy transcript ≈ 1.6 chars per token (empirical default).
CHARS_PER_TOKEN = 1.6

# Summary + TOC + markdown structure overhead (chars), beyond polished body.
OUTPUT_OVERHEAD_CHARS = 1200
OUTPUT_EXPANSION = 1.05
OUTPUT_TOKENS_STD_RATIO = 0.22

MODEL_PROFILES: dict[str, dict[str, dict[str, float]]] = {
    "v4-pro": {
        "provider": {
            "deepseek-official-nothink": {
                "ttft_base": 1.5,
                "ttft_per_1k_token": 0.05,
                "output_tps": 40.0,
            },
            "deepseek-official-think": {
                "ttft_base": 128.0,
                "ttft_per_1k_token": 0.5,
                "output_tps": 40.0,
            },
            "fireworks": {
                "ttft_base": 0.99,
                "ttft_per_1k_token": 0.03,
                "output_tps": 167.0,
            },
        }
    },
    "v4-flash": {
        "provider": {
            "deepseek-official": {
                "ttft_base": 1.11,
                "ttft_per_1k_token": 0.03,
                "output_tps": 83.0,
            },
            "together-ai": {
                "ttft_base": 0.99,
                "ttft_per_1k_token": 0.02,
                "output_tps": 100.0,
            },
        }
    },
}

_PROJECT_MODEL_TO_PROFILE: dict[str, tuple[str, str]] = {
    "deepseek-v4-pro": ("v4-pro", "deepseek-official-nothink"),
    "deepseek-v4-flash": ("v4-flash", "deepseek-official"),
}


def detect_provider(base_url: str | None = None) -> str:
    host = (urlparse(base_url or config.DEEPSEEK_BASE_URL).hostname or "").lower()
    if "fireworks" in host:
        return "fireworks"
    if "together" in host:
        return "together-ai"
    return "deepseek-official"


def resolve_model_profile(
    *,
    deepseek_model: str | None = None,
    base_url: str | None = None,
) -> tuple[str, str]:
    model_key = deepseek_model or get_deepseek_model()
    profile_model, default_provider = _PROJECT_MODEL_TO_PROFILE.get(
        model_key,
        ("v4-pro", "deepseek-official-nothink"),
    )
    provider = detect_provider(base_url)
    providers = MODEL_PROFILES[profile_model]["provider"]
    if provider in providers:
        return profile_model, provider
    if default_provider in providers:
        return profile_model, default_provider
    return profile_model, next(iter(providers))


def estimate_input_tokens(polish_chars: int) -> int:
    from server.settings_store import is_second_stage_enabled

    transcript_chars = max(0, polish_chars)
    if not is_second_stage_enabled():
        total_chars = len(get_transcript_correction_prompt()) + transcript_chars
        return max(1, int(total_chars / CHARS_PER_TOKEN))

    template_chars = len(build_polish_user_message(""))
    system_prompt = render_polish_system(get_polish_prompt_template())
    # Strict mode sends the full transcript twice: correction, then organization.
    total_chars = (
        len(get_transcript_correction_prompt())
        + transcript_chars
        + len(system_prompt)
        + template_chars
        + transcript_chars
    )
    return max(1, int(total_chars / CHARS_PER_TOKEN))


def estimate_output_tokens(
    polish_chars: int,
) -> tuple[int, float]:
    from server.settings_store import is_second_stage_enabled

    if not is_second_stage_enabled():
        mean = max(64, int(max(0, polish_chars) / CHARS_PER_TOKEN))
        return mean, max(32.0, mean * OUTPUT_TOKENS_STD_RATIO)

    body_chars = max(0, polish_chars) * OUTPUT_EXPANSION
    output_chars = body_chars + OUTPUT_OVERHEAD_CHARS
    output_chars += max(0, polish_chars)  # first correction call
    mean = max(64, int(output_chars / CHARS_PER_TOKEN))
    std = max(32.0, mean * OUTPUT_TOKENS_STD_RATIO)
    return mean, std


def estimate_polish_time(
    polish_chars: int,
    *,
    deepseek_model: str | None = None,
    base_url: str | None = None,
    percentile: float = 0.95,
) -> dict[str, float | int | str | None]:
    """Return TTFT, generation, mean/P95 total seconds for the polish API call."""
    input_tokens = estimate_input_tokens(polish_chars)
    output_mean, output_std = estimate_output_tokens(polish_chars)
    profile_model, provider = resolve_model_profile(
        deepseek_model=deepseek_model,
        base_url=base_url,
    )
    profile = MODEL_PROFILES[profile_model]["provider"][provider]

    from server.settings_store import is_second_stage_enabled

    calls = 2 if is_second_stage_enabled() else 1
    ttft = calls * profile["ttft_base"] + (input_tokens / 1000.0) * profile["ttft_per_1k_token"]
    tps = profile["output_tps"]
    gen_time_mean = output_mean / tps
    total_mean = ttft + gen_time_mean

    z = 1.645 if percentile >= 0.95 else 2.326
    output_p95 = output_mean + z * output_std
    total_p95 = ttft + output_p95 / tps

    return {
        "model": profile_model,
        "provider": provider,
        "api_calls": calls,
        "input_tokens": input_tokens,
        "output_tokens_mean": output_mean,
        "ttft_sec": round(ttft, 3),
        "gen_time_sec": round(gen_time_mean, 3),
        "total_mean_sec": round(total_mean, 3),
        "total_p95_sec": round(total_p95, 3),
    }


def polish_progress_percent(
    elapsed_sec: float,
    estimate: dict[str, float | int | str | None],
    *,
    total_sec: float | None = None,
    cap: float = 95.0,
) -> float:
    """Two-phase bar: slow during TTFT, then exponential approach to cap."""
    ttft = float(estimate.get("ttft_sec") or 1.0)
    total = float(
        total_sec
        or estimate.get("total_mean_sec")
        or estimate.get("total_p95_sec")
        or 60.0
    )
    gen_time = max(0.5, total - ttft)

    if elapsed_sec <= ttft:
        return 10.0 + 15.0 * min(1.0, elapsed_sec / max(ttft, 0.1))

    gen_elapsed = elapsed_sec - ttft
    gen_pct = 1.0 - math.exp(-gen_elapsed / gen_time)
    return min(cap, 25.0 + 70.0 * gen_pct)


def _history_pairs(limit: int = 50) -> list[tuple[int, float]]:
    from server.progress_db import fetch_polish_history_pairs

    return fetch_polish_history_pairs(limit=limit)


def _history_predict_fn() -> Callable[[int], float] | None:
    pairs = _history_pairs()
    if len(pairs) < 5:
        return None

    xs = [float(p[0]) for p in pairs]
    ys = [float(p[1]) for p in pairs]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x < 1.0:
        return None

    slope = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / var_x
    intercept = mean_y - slope * mean_x

    if slope <= 0:
        return lambda chars: max(10.0, statistics.median(ys))

    return lambda chars: max(10.0, intercept + slope * max(0, chars))


def estimate_polish_seconds(
    polish_chars: int = 0,
    *,
    deepseek_model: str | None = None,
    base_url: str | None = None,
    use_mean_api: bool = False,
) -> float:
    """Blend API profile latency with local history regression when available."""
    api = estimate_polish_time(
        polish_chars,
        deepseek_model=deepseek_model,
        base_url=base_url,
    )
    if use_mean_api:
        api_total = float(api["total_mean_sec"] or api["total_p95_sec"])
    else:
        api_total = float(api["total_p95_sec"] or api["total_mean_sec"])

    predict = _history_predict_fn()
    if predict is None:
        return max(15.0, api_total)

    hist_total = predict(polish_chars)
    n = len(_history_pairs())
    hist_weight = min(0.65, (n / 30.0) * 0.65)
    blended = hist_total * hist_weight + api_total * (1.0 - hist_weight)
    return max(15.0, blended)
