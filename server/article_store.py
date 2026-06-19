"""Local storage for polished article markdown used in follow-up chat."""

from __future__ import annotations

from pathlib import Path

import config


def polished_dir() -> Path:
    return config.PROJECT_ROOT / "downloads" / "polished"


def polished_path(task_id: str) -> Path:
    return polished_dir() / f"{task_id}.md"


def save_polished(task_id: str, body_md: str) -> Path:
    path = polished_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body_md.strip() + "\n", encoding="utf-8")
    return path


def load_polished(task_id: str | None) -> str | None:
    if not task_id:
        return None
    path = polished_path(task_id)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def delete_polished(task_id: str | None) -> None:
    if not task_id:
        return
    path = polished_path(task_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def polished_storage_stats() -> dict[str, int]:
    directory = polished_dir()
    count = 0
    total_bytes = 0
    if directory.is_dir():
        for path in directory.glob("*.md"):
            if not path.is_file():
                continue
            count += 1
            try:
                total_bytes += path.stat().st_size
            except OSError:
                pass
    return {"count": count, "bytes": total_bytes}


def clear_all_polished() -> dict[str, int]:
    directory = polished_dir()
    deleted_count = 0
    freed_bytes = 0
    if not directory.is_dir():
        return {"deleted_count": 0, "freed_bytes": 0}
    for path in directory.glob("*.md"):
        if not path.is_file():
            continue
        try:
            freed_bytes += path.stat().st_size
            path.unlink()
            deleted_count += 1
        except OSError:
            pass
    return {"deleted_count": deleted_count, "freed_bytes": freed_bytes}
