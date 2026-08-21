"""Progress statistics and ETA calibration (M05)."""

from __future__ import annotations

import statistics
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import config

DB_PATH = config.PROJECT_ROOT / "data" / "queue.db"

# Default coefficients when no history exists.
DEFAULT_TRANSCRIBE_RATE = 0.08  # transcribe_sec ≈ duration_sec * rate
DEFAULT_POLISH_SEC = 90.0
DEFAULT_DOWNLOAD_SEC = 45.0
DEFAULT_MODEL_LOAD_SEC_CUDA = 35.0
DEFAULT_MODEL_LOAD_SEC_CPU = 90.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS progress_stats (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    duration_sec REAL,
    subtitle_sec REAL NOT NULL DEFAULT 0,
    download_sec REAL,
    model_load_sec REAL NOT NULL DEFAULT 0,
    transcribe_sec REAL,
    polish_sec REAL,
    polish_tokens INTEGER,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_load_stats (
    id TEXT PRIMARY KEY,
    load_sec REAL NOT NULL,
    device TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_unload_stats (
    id TEXT PRIMARY KEY,
    recorded_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'unload'
);
"""

_lock = threading.Lock()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def _migrate_progress_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(progress_stats)")}
    if "polish_chars" not in cols:
        conn.execute("ALTER TABLE progress_stats ADD COLUMN polish_chars INTEGER")
    if "subtitle_sec" not in cols:
        conn.execute(
            "ALTER TABLE progress_stats ADD COLUMN subtitle_sec REAL NOT NULL DEFAULT 0"
        )
    if "model_load_sec" not in cols:
        conn.execute(
            "ALTER TABLE progress_stats ADD COLUMN model_load_sec REAL NOT NULL DEFAULT 0"
        )


def init_progress_stats() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate_progress_columns(conn)
        conn.commit()


def record_stats(
    *,
    task_id: str,
    duration_sec: float | None,
    download_sec: float,
    transcribe_sec: float,
    polish_sec: float,
    polish_tokens: int | None = None,
    polish_chars: int | None = None,
    subtitle_sec: float = 0.0,
    model_load_sec: float = 0.0,
) -> None:
    with _connect() as conn:
        _migrate_progress_columns(conn)
        conn.execute(
            """
            INSERT INTO progress_stats (
                id, task_id, duration_sec, subtitle_sec, download_sec,
                model_load_sec, transcribe_sec, polish_sec, polish_tokens,
                polish_chars, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                task_id,
                duration_sec,
                subtitle_sec,
                download_sec,
                model_load_sec,
                transcribe_sec,
                polish_sec,
                polish_tokens,
                polish_chars,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_task_stats(task_id: str) -> dict[str, Any] | None:
    """Return the newest measured phase timings for one task."""
    with _connect() as conn:
        _migrate_progress_columns(conn)
        conn.commit()
        row = conn.execute(
            """
            SELECT duration_sec, subtitle_sec, download_sec, model_load_sec,
                   transcribe_sec, polish_sec, polish_tokens, polish_chars, recorded_at
            FROM progress_stats
            WHERE task_id = ?
            ORDER BY recorded_at DESC LIMIT 1
            """,
            (task_id,),
        ).fetchone()
    return dict(row) if row else None


def fetch_polish_history_pairs(*, limit: int = 50) -> list[tuple[int, float]]:
    """(polish_chars, polish_sec) rows for local calibration."""
    with _connect() as conn:
        _migrate_progress_columns(conn)
        conn.commit()
        try:
            rows = conn.execute(
                """
                SELECT polish_chars, polish_sec FROM progress_stats
                WHERE polish_sec > 0 AND polish_chars > 0
                ORDER BY recorded_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
    return [(int(r["polish_chars"]), float(r["polish_sec"])) for r in rows]


def _median_transcribe_rate() -> float:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT transcribe_sec, duration_sec FROM progress_stats
            WHERE duration_sec > 0 AND transcribe_sec > 0
            ORDER BY recorded_at DESC LIMIT 50
            """
        ).fetchall()
    if not rows:
        return DEFAULT_TRANSCRIBE_RATE
    rates = [float(r["transcribe_sec"]) / float(r["duration_sec"]) for r in rows]
    return statistics.median(rates)


def _median_polish_sec() -> float:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT polish_sec FROM progress_stats
            WHERE polish_sec > 0
            ORDER BY recorded_at DESC LIMIT 50
            """
        ).fetchall()
    if not rows:
        return DEFAULT_POLISH_SEC
    return statistics.median([float(r["polish_sec"]) for r in rows])


def _median_download_sec() -> float:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT download_sec FROM progress_stats
            WHERE download_sec > 0
            ORDER BY recorded_at DESC LIMIT 50
            """
        ).fetchall()
    if not rows:
        return DEFAULT_DOWNLOAD_SEC
    return statistics.median([float(r["download_sec"]) for r in rows])


def estimate_phase_seconds(
    *,
    duration_sec: float | None,
    phase: str,
    polish_chars: int = 0,
    deepseek_model: str | None = None,
) -> float:
    if phase == "download":
        return _median_download_sec()
    if phase == "transcribe":
        dur = duration_sec or 600.0
        return max(30.0, dur * _median_transcribe_rate())
    if phase == "polish":
        from server.polish_estimate import estimate_polish_seconds

        if polish_chars > 0:
            return estimate_polish_seconds(
                polish_chars,
                deepseek_model=deepseek_model,
            )
        median = _median_polish_sec()
        if median != DEFAULT_POLISH_SEC:
            return median
        return estimate_polish_seconds(8000, deepseek_model=deepseek_model)
    return 60.0


def record_model_load(*, load_sec: float, device: str) -> None:
    if load_sec <= 0:
        return
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO model_load_stats (id, load_sec, device, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                load_sec,
                device,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def last_model_load_at() -> str | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT recorded_at FROM model_load_stats
            ORDER BY recorded_at DESC LIMIT 1
            """
        ).fetchone()
    return str(row["recorded_at"]) if row else None


def record_model_unload(*, source: str = "unload", recorded_at: str | None = None) -> None:
    init_progress_stats()
    at = recorded_at or datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO model_unload_stats (id, recorded_at, source)
            VALUES (?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                at,
                source,
            ),
        )
        conn.commit()


def last_model_unload_at() -> str | None:
    init_progress_stats()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT recorded_at FROM model_unload_stats
            ORDER BY recorded_at DESC LIMIT 1
            """
        ).fetchone()
    return str(row["recorded_at"]) if row else None


def estimate_model_load_seconds(*, device: str = "cpu") -> float:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT load_sec FROM model_load_stats
            WHERE device = ? AND load_sec > 0
            ORDER BY recorded_at DESC LIMIT 20
            """,
            (device,),
        ).fetchall()
        if not rows:
            rows = conn.execute(
                """
                SELECT load_sec FROM model_load_stats
                WHERE load_sec > 0
                ORDER BY recorded_at DESC LIMIT 20
                """
            ).fetchall()
    if rows:
        return max(10.0, statistics.median([float(r["load_sec"]) for r in rows]))
    if device == "cuda":
        return DEFAULT_MODEL_LOAD_SEC_CUDA
    return DEFAULT_MODEL_LOAD_SEC_CPU
