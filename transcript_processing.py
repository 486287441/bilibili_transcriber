"""Deterministic cleanup applied between ASR and transcript correction."""

from __future__ import annotations

import re


# Only natural-language punctuation is removed. ASCII punctuation and symbols
# used inside numbers, versions, addresses, and technical names stay intact.
_ASR_PUNCTUATION_RE = re.compile(r"[，。！？；：、…—]")


def remove_asr_punctuation(text: str) -> str:
    """Remove the explicitly allowed Chinese punctuation from ASR output."""
    return _ASR_PUNCTUATION_RE.sub("", text or "")
