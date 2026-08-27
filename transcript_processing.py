"""Deterministic cleanup applied between ASR and transcript correction."""

from __future__ import annotations

import re


# Only natural-language punctuation is removed. ASCII punctuation and symbols
# used inside numbers, versions, addresses, and technical names stay intact.
_ASR_PUNCTUATION_RE = re.compile(r"[，。！？；：、…—]")
_INLINE_SPACE_RE = re.compile(r"[\t\r\f\v ]+")
_SENTENCE_RE = re.compile(r".+?(?:[。！？!?]+[”’」』】）》]?|$)", re.S)
_ASCII_WORD_EDGE_RE = re.compile(r"[A-Za-z0-9]$")
_ASCII_WORD_START_RE = re.compile(r"^[A-Za-z0-9]")


def remove_asr_punctuation(text: str) -> str:
    """Remove the explicitly allowed Chinese punctuation from ASR output."""
    return _ASR_PUNCTUATION_RE.sub("", text or "")


def format_transcript_locally(text: str, *, target_paragraph_chars: int = 320) -> str:
    """Turn punctuated ASR output into readable paragraphs without rewriting it.

    This path deliberately preserves the recognizer's words and punctuation. It
    only normalizes whitespace and groups complete sentences into paragraphs,
    so disabling DeepSeek never routes the text through punctuation removal.
    """
    source = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not source:
        return ""

    paragraphs: list[str] = []
    source_blocks = re.split(r"\n\s*\n+", source)
    for source_block in source_blocks:
        lines = [
            cleaned
            for line in source_block.splitlines()
            if (cleaned := _INLINE_SPACE_RE.sub(" ", line).strip())
        ]
        block = ""
        for line in lines:
            separator = (
                " "
                if block
                and _ASCII_WORD_EDGE_RE.search(block)
                and _ASCII_WORD_START_RE.search(line)
                else ""
            )
            block += separator + line
        if not block:
            continue

        sentences = [match.group(0).strip() for match in _SENTENCE_RE.finditer(block)]
        if not sentences:
            sentences = [block]

        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) > target_paragraph_chars:
                paragraphs.append(current)
                current = sentence
            else:
                current += sentence
        if current:
            paragraphs.append(current)

    return "\n\n".join(paragraphs).strip()
