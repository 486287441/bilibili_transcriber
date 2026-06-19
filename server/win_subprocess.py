"""Hide console windows for child processes on Windows (ffmpeg, lark-cli, etc.)."""

from __future__ import annotations

import subprocess
import sys

_patched = False
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _hidden_startupinfo() -> subprocess.STARTUPINFO:
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return info


def _apply_hidden_flags(kwargs: dict) -> None:
    if kwargs.get("startupinfo") is None:
        kwargs["startupinfo"] = _hidden_startupinfo()
    kwargs.setdefault("creationflags", CREATE_NO_WINDOW)


def patch_subprocess_no_window() -> None:
    """Patch subprocess so spawned tools (ffmpeg, cmd wrappers) do not flash CMD."""
    global _patched
    if _patched or sys.platform != "win32":
        return

    orig_popen = subprocess.Popen

    class Popen(orig_popen):
        def __init__(self, *args, **kwargs):
            _apply_hidden_flags(kwargs)
            super().__init__(*args, **kwargs)

    subprocess.Popen = Popen  # type: ignore[misc,assignment]

    for name in ("run", "call", "check_output", "check_call"):
        orig = getattr(subprocess, name)

        def wrapper(*args, _orig=orig, **kwargs):
            _apply_hidden_flags(kwargs)
            return _orig(*args, **kwargs)

        setattr(subprocess, name, wrapper)

    _patched = True
