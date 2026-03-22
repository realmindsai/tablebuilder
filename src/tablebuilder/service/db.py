# ABOUTME: SQLite database for the TableBuilder service layer.
# ABOUTME: Manages users, jobs, job_events, and chat_sessions tables.

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    api_key_hash TEXT UNIQUE NOT NULL,
    abs_credentials_encrypted TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'queued',
    progress TEXT,
    request_json TEXT NOT NULL,
    result_path TEXT,
    error_message TEXT,
    error_detail TEXT,
    screenshot_path TEXT,
    page_url TEXT,
    page_html_path TEXT,
    timeout_seconds INTEGER DEFAULT 600,
    retry_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    detail TEXT,
    screenshot_path TEXT
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    messages_json TEXT NOT NULL,
    resolved_request_json TEXT,
    proposals_json TEXT DEFAULT '[]',
    research_question TEXT DEFAULT '',
    job_id TEXT REFERENCES jobs(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id),
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    detail TEXT,
    metadata_json TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ServiceDB:
    """SQLite database for the TableBuilder service."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA_SQL)
        # Migrate existing chat_sessions table with new columns
        for col, definition in [
            ("proposals_json", "TEXT DEFAULT '[]'"),
            ("research_question", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE chat_sessions ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
        conn.close()

    # -- Users --

    def create_user(self, api_key_hash: str, abs_credentials_encrypted: str) -> str:
        user_id = uuid4().hex
        conn = self._connect()
        conn.execute(
            "INSERT INTO users (id, api_key_hash, abs_credentials_encrypted, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, api_key_hash, abs_credentials_encrypted, _now()),
        )
        conn.commit()
        conn.close()
        return user_id

    def get_user_by_api_key_hash(self, api_key_hash: str) -> dict | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM users WHERE api_key_hash = ?", (api_key_hash,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_user(self, user_id: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()

    def touch_user(self, user_id: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE users SET last_used_at = ? WHERE id = ?", (_now(), user_id)
        )
        conn.commit()
        conn.close()

    # -- Jobs --

    def create_job(
        self, user_id: str, request_json: str, timeout_seconds: int = 600
    ) -> str:
        job_id = uuid4().hex
        conn = self._connect()
        conn.execute(
            "INSERT INTO jobs (id, user_id, request_json, timeout_seconds, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (job_id, user_id, request_json, timeout_seconds, _now()),
        )
        conn.commit()
        conn.close()
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def fetch_next_queued_job(self) -> dict | None:
        """Atomically claim the oldest queued job. Returns job + user credentials."""
        conn = self._connect()
        row = conn.execute(
            "SELECT j.*, u.abs_credentials_encrypted "
            "FROM jobs j JOIN users u ON j.user_id = u.id "
            "WHERE j.status = 'queued' "
            "ORDER BY j.created_at LIMIT 1"
        ).fetchone()
        if row is None:
            conn.close()
            return None
        job_id = row["id"]
        conn.execute(
            "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
            (_now(), job_id),
        )
        conn.commit()
        result = dict(row)
        conn.close()
        return result

    def update_progress(self, job_id: str, progress: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE jobs SET progress = ? WHERE id = ?", (progress, job_id)
        )
        conn.commit()
        conn.close()

    def mark_completed(self, job_id: str, result_path: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE jobs SET status = 'completed', result_path = ?, completed_at = ? "
            "WHERE id = ?",
            (result_path, _now(), job_id),
        )
        conn.commit()
        conn.close()

    def mark_failed(
        self,
        job_id: str,
        error_message: str,
        error_detail: str = "",
        page_url: str = "",
        page_html_path: str = "",
        screenshot_path: str = "",
    ) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE jobs SET status = 'failed', error_message = ?, error_detail = ?, "
            "page_url = ?, page_html_path = ?, screenshot_path = ?, completed_at = ? "
            "WHERE id = ?",
            (error_message, error_detail, page_url, page_html_path, screenshot_path,
             _now(), job_id),
        )
        conn.commit()
        conn.close()

    def list_user_jobs(self, user_id: str, status: str | None = None) -> list[dict]:
        conn = self._connect()
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? AND status = ? ORDER BY created_at DESC",
                (user_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # -- Job Events --

    def add_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        detail: str = "",
        screenshot_path: str = "",
    ) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO job_events (job_id, timestamp, event_type, message, detail, screenshot_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, _now(), event_type, message, detail, screenshot_path),
        )
        conn.commit()
        conn.close()

    def get_events(self, job_id: str) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM job_events WHERE job_id = ? ORDER BY timestamp, id",
            (job_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # -- Chat Sessions --

    def create_chat_session(self, user_id: str, messages_json: str) -> str:
        session_id = uuid4().hex
        now = _now()
        conn = self._connect()
        conn.execute(
            "INSERT INTO chat_sessions (id, user_id, messages_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, messages_json, now, now),
        )
        conn.commit()
        conn.close()
        return session_id

    def get_chat_session(self, session_id: str) -> dict | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def update_chat_session(
        self,
        session_id: str,
        messages_json: str,
        resolved_request_json: str | None = None,
    ) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE chat_sessions SET messages_json = ?, resolved_request_json = ?, updated_at = ? "
            "WHERE id = ?",
            (messages_json, resolved_request_json, _now(), session_id),
        )
        conn.commit()
        conn.close()

    def link_chat_to_job(self, session_id: str, job_id: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE chat_sessions SET job_id = ?, updated_at = ? WHERE id = ?",
            (job_id, _now(), session_id),
        )
        conn.commit()
        conn.close()

    # -- Session Events --

    def add_session_event(
        self,
        session_id: str,
        event_type: str,
        message: str,
        detail: str = "",
        metadata_json: str = "",
    ) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO session_events (session_id, timestamp, event_type, message, detail, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, _now(), event_type, message, detail, metadata_json),
        )
        conn.commit()
        conn.close()

    def get_session_events(self, session_id: str) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM session_events WHERE session_id = ? ORDER BY timestamp, id",
            (session_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
