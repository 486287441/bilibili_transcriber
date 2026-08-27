"""SQLite persistence for the task queue."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Literal

import config

DB_PATH = config.PROJECT_ROOT / "data" / "queue.db"

RequestedRoute = Literal["auto", "ocr", "asr"]
ResolvedRoute = Literal["ocr", "asr"]
REQUESTED_ROUTES = frozenset({"auto", "ocr", "asr"})
RESOLVED_ROUTES = frozenset({"ocr", "asr"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    telegram_chat_id INTEGER,
    site TEXT,
    title TEXT,
    duration_sec REAL,
    status TEXT NOT NULL,
    position INTEGER NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    output_doc_url TEXT,
    output_text_path TEXT,
    requested_route TEXT NOT NULL DEFAULT 'auto',
    resolved_route TEXT,
    route_diagnostics TEXT,
    raw_text_path TEXT,
    source_segments_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status_position ON tasks(status, position);
CREATE INDEX IF NOT EXISTS idx_tasks_url ON tasks(url);
"""

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRow:
    id: str
    url: str
    source: str
    telegram_chat_id: int | None
    site: str | None
    title: str | None
    duration_sec: float | None
    status: str
    position: int
    retry_count: int
    max_retries: int
    error_message: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None
    output_doc_url: str | None
    output_text_path: str | None
    reprocess_mode: str | None = None
    history_source_id: str | None = None
    local_audio_path: str | None = None
    requested_route: RequestedRoute = "asr"
    resolved_route: ResolvedRoute | None = None
    route_diagnostics: dict[str, Any] | None = None
    raw_text_path: str | None = None
    source_segments_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        from server.error_summary import summarize_task_error

        data = {
            "id": self.id,
            "url": self.url,
            "source": self.source,
            "telegram_chat_id": self.telegram_chat_id,
            "site": self.site,
            "title": self.title,
            "duration_sec": self.duration_sec,
            "status": self.status,
            "position": self.position,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "output_doc_url": self.output_doc_url,
            "output_text_path": self.output_text_path,
            "reprocess_mode": self.reprocess_mode,
            "history_source_id": self.history_source_id,
            "local_audio_path": self.local_audio_path,
            "requested_route": self.requested_route,
            "resolved_route": self.resolved_route,
            "route_diagnostics": self.route_diagnostics,
            "raw_text_path": self.raw_text_path,
            "source_segments_path": self.source_segments_path,
        }
        if self.error_message:
            data["error_summary"] = summarize_task_error(self.error_message)
        return data


def _row_from_sql(row: sqlite3.Row) -> TaskRow:
    keys = row.keys()
    return TaskRow(
        id=row["id"],
        url=row["url"],
        source=row["source"],
        telegram_chat_id=row["telegram_chat_id"],
        site=row["site"],
        title=row["title"],
        duration_sec=row["duration_sec"],
        status=row["status"],
        position=row["position"],
        retry_count=row["retry_count"],
        max_retries=row["max_retries"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        output_doc_url=row["output_doc_url"],
        output_text_path=row["output_text_path"],
        reprocess_mode=row["reprocess_mode"] if "reprocess_mode" in keys else None,
        history_source_id=row["history_source_id"] if "history_source_id" in keys else None,
        local_audio_path=row["local_audio_path"] if "local_audio_path" in keys else None,
        requested_route=(
            row["requested_route"]
            if "requested_route" in keys and row["requested_route"]
            else "asr"
        ),
        resolved_route=row["resolved_route"] if "resolved_route" in keys else None,
        route_diagnostics=(
            _decode_route_diagnostics(row["route_diagnostics"])
            if "route_diagnostics" in keys
            else None
        ),
        raw_text_path=row["raw_text_path"] if "raw_text_path" in keys else None,
        source_segments_path=(
            row["source_segments_path"] if "source_segments_path" in keys else None
        ),
    )


def _encode_route_diagnostics(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_route_diagnostics(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _migrate_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    resolved_route_added = "resolved_route" not in existing
    for col, typ in (
        ("reprocess_mode", "TEXT"),
        ("history_source_id", "TEXT"),
        ("local_audio_path", "TEXT"),
        ("requested_route", "TEXT NOT NULL DEFAULT 'asr'"),
        ("resolved_route", "TEXT"),
        ("route_diagnostics", "TEXT"),
        ("raw_text_path", "TEXT"),
        ("source_segments_path", "TEXT"),
    ):
        if col not in existing:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typ}")
    conn.execute(
        "UPDATE tasks SET requested_route = 'asr' "
        "WHERE requested_route IS NULL OR requested_route = ''"
    )
    if resolved_route_added:
        conn.execute("UPDATE tasks SET resolved_route = 'asr'")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate_columns(conn)
        conn.commit()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def next_position(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 AS p FROM tasks").fetchone()
    return int(row["p"])


def insert_task(conn: sqlite3.Connection, task: TaskRow) -> None:
    conn.execute(
        """
        INSERT INTO tasks (
            id, url, source, telegram_chat_id, site, title, duration_sec,
            status, position, retry_count, max_retries, error_message,
            created_at, updated_at, started_at, completed_at,
            output_doc_url, output_text_path,
            reprocess_mode, history_source_id, local_audio_path,
            requested_route, resolved_route, route_diagnostics,
            raw_text_path, source_segments_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task.id,
            task.url,
            task.source,
            task.telegram_chat_id,
            task.site,
            task.title,
            task.duration_sec,
            task.status,
            task.position,
            task.retry_count,
            task.max_retries,
            task.error_message,
            task.created_at,
            task.updated_at,
            task.started_at,
            task.completed_at,
            task.output_doc_url,
            task.output_text_path,
            task.reprocess_mode,
            task.history_source_id,
            task.local_audio_path,
            task.requested_route,
            task.resolved_route,
            _encode_route_diagnostics(task.route_diagnostics),
            task.raw_text_path,
            task.source_segments_path,
        ),
    )


def get_task(task_id: str) -> TaskRow | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_from_sql(row) if row else None


def list_tasks(*, status: str | None = None) -> list[TaskRow]:
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY position ASC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status != 'completed'
                ORDER BY position ASC
                """
            ).fetchall()
        return [_row_from_sql(r) for r in rows]


def find_active_by_url(url: str) -> TaskRow | None:
    from video_urls import canonical_video_key

    key = canonical_video_key(url)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status IN ('pending', 'downloading', 'transcribing', 'polishing')
            ORDER BY position ASC
            """
        ).fetchall()
        for row in rows:
            if canonical_video_key(row["url"]) == key:
                return _row_from_sql(row)
    return None


def update_task_fields(task_id: str, **fields: Any) -> TaskRow | None:
    if not fields:
        return get_task(task_id)
    if "route_diagnostics" in fields:
        fields["route_diagnostics"] = _encode_route_diagnostics(fields["route_diagnostics"])
    fields["updated_at"] = _now_iso()
    columns = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    with _connect() as conn:
        conn.execute(f"UPDATE tasks SET {columns} WHERE id = ?", values)
        conn.commit()
    return get_task(task_id)


def update_task_fields_if_status(
    task_id: str,
    expected_status: str,
    **fields: Any,
) -> TaskRow | None:
    """Update one task only while it is still in ``expected_status``.

    State changes must not be implemented as a read followed by an
    unconditional update: a cancel/claim request can otherwise overwrite a
    newer worker state.  Returning ``None`` means the row disappeared or its
    state changed before this compare-and-swap completed.
    """

    if not fields:
        task = get_task(task_id)
        return task if task and task.status == expected_status else None
    if "route_diagnostics" in fields:
        fields["route_diagnostics"] = _encode_route_diagnostics(fields["route_diagnostics"])
    fields["updated_at"] = _now_iso()
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = [*fields.values(), task_id, expected_status]
    with _connect() as conn:
        cursor = conn.execute(
            f"UPDATE tasks SET {columns} WHERE id = ? AND status = ?",
            values,
        )
        if cursor.rowcount != 1:
            return None
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.commit()
        return _row_from_sql(row) if row else None


def delete_task(task_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return cur.rowcount > 0


def cancel_pending_task(task_id: str) -> TaskRow | None:
    """Atomically cancel and remove a task only if it is still pending."""

    now = _now_iso()
    with _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE tasks
            SET status = 'cancelled', updated_at = ?, completed_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now, now, task_id),
        )
        if cursor.rowcount != 1:
            return None
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.execute("DELETE FROM tasks WHERE id = ? AND status = 'cancelled'", (task_id,))
        conn.commit()
        return _row_from_sql(row) if row else None


def remove_active_task(task_id: str) -> TaskRow | None:
    """Atomically remove a cancellable active task from the persistent queue.

    The worker may still be inside a blocking third-party call.  Removing the
    SQLite row here makes the user's delete durable immediately; the separate
    in-memory cancellation flag remains alive until the worker reaches its
    next safe checkpoint and cleans temporary files.
    """

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM tasks
            WHERE id = ? AND status IN ('downloading', 'transcribing', 'polishing')
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        cursor = conn.execute(
            """
            DELETE FROM tasks
            WHERE id = ? AND status IN ('downloading', 'transcribing', 'polishing')
            """,
            (task_id,),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        return _row_from_sql(row)


def purge_completed_tasks() -> int:
    """Remove completed tasks from queue (they live in history)."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE status = 'completed'")
        conn.commit()
        return cur.rowcount


def claim_next_pending() -> TaskRow | None:
    """Atomically pick the next pending task (lowest position)."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'pending'
            ORDER BY position ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        task_id = row["id"]
        now = _now_iso()
        conn.execute(
            """
            UPDATE tasks
            SET status = 'downloading', updated_at = ?, started_at = COALESCE(started_at, ?)
            WHERE id = ? AND status = 'pending'
            """,
            (now, now, task_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if updated and updated["status"] == "downloading":
            return _row_from_sql(updated)
        return None


def reorder_tasks(ids: list[str]) -> list[TaskRow]:
    """Assign positions 1..n for *ids* in order; remaining tasks follow."""
    all_rows = list_tasks()
    other_ids = [t.id for t in all_rows if t.id not in ids]
    ordered = ids + other_ids
    with _connect() as conn:
        for idx, task_id in enumerate(ordered, start=1):
            conn.execute(
                "UPDATE tasks SET position = ?, updated_at = ? WHERE id = ?",
                (idx, _now_iso(), task_id),
            )
        conn.commit()
    return list_tasks()


def create_pending_task(
    *,
    url: str,
    source: str,
    telegram_chat_id: int | None,
    site: str | None,
    reprocess_mode: str | None = None,
    history_source_id: str | None = None,
    local_audio_path: str | None = None,
    title: str | None = None,
    duration_sec: float | None = None,
    requested_route: RequestedRoute = "auto",
) -> TaskRow:
    now = _now_iso()
    with _connect() as conn:
        position = next_position(conn)
        task = TaskRow(
            id=str(uuid.uuid4()),
            url=url,
            source=source,
            telegram_chat_id=telegram_chat_id,
            site=site,
            title=title,
            duration_sec=duration_sec,
            status="pending",
            position=position,
            retry_count=0,
            max_retries=3,
            error_message=None,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
            output_doc_url=None,
            output_text_path=None,
            reprocess_mode=reprocess_mode,
            history_source_id=history_source_id,
            local_audio_path=local_audio_path,
            requested_route=requested_route,
            resolved_route=None,
            route_diagnostics=None,
            raw_text_path=None,
            source_segments_path=None,
        )
        insert_task(conn, task)
        conn.commit()
        return task


def count_by_status(status: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE status = ?",
            (status,),
        ).fetchone()
        return int(row["c"])


def find_recent_completed_by_url(url: str, *, within_minutes: int) -> TaskRow | None:
    if within_minutes <= 0:
        return None
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=within_minutes)).isoformat()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM tasks
            WHERE url = ? AND status = 'completed' AND completed_at >= ?
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            (url, cutoff),
        ).fetchone()
        return _row_from_sql(row) if row else None


def recover_interrupted() -> list[str]:
    """On startup: reset mid-pipeline tasks to pending so they can retry.

    Interrupted downloads/transcriptions are not resumable at the byte level,
    so we rewind to pending rather than leaving a stuck in-progress status.
    """
    now = _now_iso()
    recovered: list[str] = []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id FROM tasks
            WHERE status IN ('downloading', 'transcribing', 'polishing')
            """
        ).fetchall()
        for row in rows:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'pending', updated_at = ?, error_message = ?
                WHERE id = ?
                """,
                (now, "服务重启，任务已重新排队", row["id"]),
            )
            recovered.append(row["id"])
        conn.commit()
    return recovered
