"""History persistence (M07)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

import config
from server.queue_db import RequestedRoute, ResolvedRoute
from video_urls import canonical_video_key

DB_PATH = config.PROJECT_ROOT / "data" / "queue.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    url TEXT NOT NULL,
    title TEXT,
    duration_sec REAL,
    site TEXT,
    source TEXT,
    status TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    processing_duration_sec REAL,
    output_doc_url TEXT,
    output_text_path TEXT,
    local_audio_path TEXT,
    error_message TEXT,
    requested_route TEXT NOT NULL DEFAULT 'asr',
    resolved_route TEXT,
    route_diagnostics TEXT,
    raw_text_path TEXT,
    source_segments_path TEXT,
    parent_history_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_processed ON history(processed_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_status ON history(status);
"""

_lock = threading.Lock()


@dataclass
class HistoryRow:
    id: str
    task_id: str | None
    url: str
    title: str | None
    duration_sec: float | None
    site: str | None
    source: str | None
    status: str
    processed_at: str
    processing_duration_sec: float | None
    output_doc_url: str | None
    output_text_path: str | None
    local_audio_path: str | None
    error_message: str | None
    requested_route: RequestedRoute = "asr"
    resolved_route: ResolvedRoute | None = "asr"
    route_diagnostics: dict[str, Any] | None = None
    raw_text_path: str | None = None
    source_segments_path: str | None = None
    parent_history_id: str | None = None

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        from server.error_summary import summarize_task_error

        data = {
            "id": self.id,
            "task_id": self.task_id,
            "url": self.url,
            "title": self.title,
            "duration_sec": self.duration_sec,
            "site": self.site,
            "source": self.source,
            "status": self.status,
            "processed_at": self.processed_at,
            "processing_duration_sec": self.processing_duration_sec,
            "output_doc_url": self.output_doc_url,
            "output_text_path": self.output_text_path,
            "local_audio_path": self.local_audio_path,
            "error_message": self.error_message,
            "requested_route": self.requested_route,
            "resolved_route": self.resolved_route,
            "route_diagnostics": self.route_diagnostics,
            "raw_text_path": self.raw_text_path,
            "source_segments_path": self.source_segments_path,
            "parent_history_id": self.parent_history_id,
        }
        if self.error_message:
            data["error_summary"] = summarize_task_error(self.error_message)
        if self.status == "completed":
            from server.article_store import load_polished
            from server.recommendation import parse_recommendation

            data["recommendation"] = parse_recommendation(load_polished(self.task_id))
        if include_text:
            from prompts import build_followup_article_message
            from server.article_store import load_polished

            polished = load_polished(self.task_id)
            if polished:
                data["output_text"] = polished
                data["followup_context"] = build_followup_article_message(polished)
            else:
                data["output_text"] = None
                data["followup_context"] = None
        return data


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def init_history() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate_columns(conn)
        conn.commit()


def _migrate_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(history)")}
    resolved_route_added = "resolved_route" not in existing
    for col, typ in (
        ("url_key", "TEXT"),
        ("requested_route", "TEXT NOT NULL DEFAULT 'asr'"),
        ("resolved_route", "TEXT"),
        ("route_diagnostics", "TEXT"),
        ("raw_text_path", "TEXT"),
        ("source_segments_path", "TEXT"),
        ("parent_history_id", "TEXT"),
    ):
        if col not in existing:
            conn.execute(f"ALTER TABLE history ADD COLUMN {col} {typ}")
    conn.execute(
        "UPDATE history SET requested_route = 'asr' "
        "WHERE requested_route IS NULL OR requested_route = ''"
    )
    if resolved_route_added:
        conn.execute("UPDATE history SET resolved_route = 'asr'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_url_key ON history(url_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_parent ON history(parent_history_id)")
    rows = conn.execute(
        "SELECT id, url FROM history WHERE url_key IS NULL OR url_key = ''"
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE history SET url_key = ? WHERE id = ?",
            (canonical_video_key(row["url"]), row["id"]),
        )
    # Re-key B站分 P：旧逻辑只按 BV 去重，会误挡同合集其他集。
    bilibili_rows = conn.execute(
        """
        SELECT id, url, url_key FROM history
        WHERE lower(url) LIKE '%bilibili.com/video/%'
        """
    ).fetchall()
    for row in bilibili_rows:
        new_key = canonical_video_key(row["url"])
        if row["url_key"] != new_key:
            conn.execute(
                "UPDATE history SET url_key = ? WHERE id = ?",
                (new_key, row["id"]),
            )


def _row_from_sql(row: sqlite3.Row) -> HistoryRow:
    keys = row.keys()
    return HistoryRow(
        id=row["id"],
        task_id=row["task_id"],
        url=row["url"],
        title=row["title"],
        duration_sec=row["duration_sec"],
        site=row["site"],
        source=row["source"],
        status=row["status"],
        processed_at=row["processed_at"],
        processing_duration_sec=row["processing_duration_sec"],
        output_doc_url=row["output_doc_url"],
        output_text_path=row["output_text_path"],
        local_audio_path=row["local_audio_path"],
        error_message=row["error_message"],
        requested_route=(
            row["requested_route"]
            if "requested_route" in keys and row["requested_route"]
            else "asr"
        ),
        resolved_route=row["resolved_route"] if "resolved_route" in keys else "asr",
        route_diagnostics=(
            _decode_route_diagnostics(row["route_diagnostics"])
            if "route_diagnostics" in keys
            else None
        ),
        raw_text_path=row["raw_text_path"] if "raw_text_path" in keys else None,
        source_segments_path=(
            row["source_segments_path"] if "source_segments_path" in keys else None
        ),
        parent_history_id=(
            row["parent_history_id"] if "parent_history_id" in keys else None
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


def upsert_from_task(
    *,
    task_id: str,
    url: str,
    title: str | None,
    duration_sec: float | None,
    site: str | None,
    source: str | None,
    status: str,
    processing_duration_sec: float | None,
    output_doc_url: str | None,
    output_text_path: str | None,
    local_audio_path: str | None,
    error_message: str | None,
    requested_route: RequestedRoute = "asr",
    resolved_route: ResolvedRoute | None = "asr",
    route_diagnostics: dict[str, Any] | None = None,
    raw_text_path: str | None = None,
    source_segments_path: str | None = None,
    parent_history_id: str | None = None,
) -> HistoryRow:
    now = _now_iso()
    url_key = canonical_video_key(url)
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM history WHERE task_id = ?", (task_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE history SET
                    status=?, processed_at=?, processing_duration_sec=?,
                    output_doc_url=?, output_text_path=?, local_audio_path=?,
                    error_message=?, title=?, duration_sec=?, url_key=?,
                    requested_route=?, resolved_route=?, route_diagnostics=?,
                    raw_text_path=?, source_segments_path=?, parent_history_id=?
                WHERE task_id=?
                """,
                (
                    status,
                    now,
                    processing_duration_sec,
                    output_doc_url,
                    output_text_path,
                    local_audio_path,
                    error_message,
                    title,
                    duration_sec,
                    url_key,
                    requested_route,
                    resolved_route,
                    _encode_route_diagnostics(route_diagnostics),
                    raw_text_path,
                    source_segments_path,
                    parent_history_id,
                    task_id,
                ),
            )
            hid = existing["id"]
        else:
            hid = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO history (
                    id, task_id, url, title, duration_sec, site, source, status,
                    processed_at, processing_duration_sec, output_doc_url,
                    output_text_path, local_audio_path, error_message, url_key,
                    requested_route, resolved_route, route_diagnostics,
                    raw_text_path, source_segments_path, parent_history_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hid,
                    task_id,
                    url,
                    title,
                    duration_sec,
                    site,
                    source,
                    status,
                    now,
                    processing_duration_sec,
                    output_doc_url,
                    output_text_path,
                    local_audio_path,
                    error_message,
                    url_key,
                    requested_route,
                    resolved_route,
                    _encode_route_diagnostics(route_diagnostics),
                    raw_text_path,
                    source_segments_path,
                    parent_history_id,
                ),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM history WHERE id = ?", (hid,)).fetchone()
        assert row is not None
        return _row_from_sql(row)


def get_history(history_id: str) -> HistoryRow | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM history WHERE id = ?", (history_id,)).fetchone()
        return _row_from_sql(row) if row else None


def find_by_url(url: str) -> HistoryRow | None:
    key = canonical_video_key(url)
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM history WHERE url_key = ? LIMIT 1",
            (key,),
        ).fetchone()
        return _row_from_sql(row) if row else None


def list_history(
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    query: str | None = None,
) -> tuple[list[HistoryRow], int]:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if query:
        clauses.append("(title LIKE ? OR url LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM history {where}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"""
            SELECT * FROM history {where}
            ORDER BY processed_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
    return [_row_from_sql(r) for r in rows], int(total)


def delete_history(history_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM history WHERE id = ?", (history_id,))
        conn.commit()
        return cur.rowcount > 0
