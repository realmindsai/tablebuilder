# ABOUTME: Tests for the service database layer.
# ABOUTME: Covers schema creation, user CRUD, job CRUD, and event logging.

import json
import sqlite3
from pathlib import Path

import pytest

from tablebuilder.service.db import ServiceDB


@pytest.fixture
def db(tmp_path):
    """Create a ServiceDB with a temporary database file."""
    db_path = tmp_path / "test_service.db"
    return ServiceDB(db_path)


class TestServiceDBSchema:
    def test_tables_created(self, db):
        """All four tables exist after initialization."""
        conn = sqlite3.connect(db.db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        conn.close()
        assert "users" in table_names
        assert "jobs" in table_names
        assert "job_events" in table_names
        assert "chat_sessions" in table_names

    def test_wal_mode_enabled(self, db):
        """WAL mode is enabled for concurrent reads."""
        conn = sqlite3.connect(db.db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_session_events_table_exists(self, db):
        """session_events table exists after initialization."""
        conn = sqlite3.connect(db.db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        conn.close()
        assert "session_events" in table_names


class TestServiceDBUsers:
    def test_create_user(self, db):
        """Create a user and retrieve by API key hash."""
        user_id = db.create_user(
            api_key_hash="abc123hash",
            abs_credentials_encrypted="encrypted_blob",
        )
        assert user_id is not None

    def test_get_user_by_api_key_hash(self, db):
        """Retrieve a user by their API key hash."""
        user_id = db.create_user(
            api_key_hash="abc123hash",
            abs_credentials_encrypted="encrypted_blob",
        )
        user = db.get_user_by_api_key_hash("abc123hash")
        assert user is not None
        assert user["id"] == user_id
        assert user["abs_credentials_encrypted"] == "encrypted_blob"

    def test_get_user_nonexistent(self, db):
        """Non-existent API key hash returns None."""
        user = db.get_user_by_api_key_hash("doesnotexist")
        assert user is None

    def test_delete_user(self, db):
        """Delete a user removes them from the database."""
        user_id = db.create_user(
            api_key_hash="abc123hash",
            abs_credentials_encrypted="encrypted_blob",
        )
        db.delete_user(user_id)
        user = db.get_user_by_api_key_hash("abc123hash")
        assert user is None


class TestServiceDBJobs:
    def test_create_job(self, db):
        """Create a job and retrieve it."""
        user_id = db.create_user(
            api_key_hash="hash1",
            abs_credentials_encrypted="creds",
        )
        request_json = json.dumps({
            "dataset": "Test Dataset",
            "rows": ["VAR1"],
            "cols": [],
            "wafers": [],
        })
        job_id = db.create_job(user_id=user_id, request_json=request_json)
        job = db.get_job(job_id)
        assert job is not None
        assert job["status"] == "queued"
        assert job["user_id"] == user_id

    def test_fetch_next_queued_job(self, db):
        """Fetch next queued job returns oldest queued job with user credentials."""
        user_id = db.create_user(
            api_key_hash="hash1",
            abs_credentials_encrypted="creds",
        )
        job_id = db.create_job(user_id=user_id, request_json='{"dataset":"D","rows":["R"]}')
        result = db.fetch_next_queued_job()
        assert result is not None
        assert result["id"] == job_id
        assert result["abs_credentials_encrypted"] == "creds"
        # Job should now be 'running'
        job = db.get_job(job_id)
        assert job["status"] == "running"

    def test_fetch_next_queued_job_empty(self, db):
        """Returns None when no queued jobs exist."""
        result = db.fetch_next_queued_job()
        assert result is None

    def test_mark_completed(self, db):
        """Mark a job as completed with a result path."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        job_id = db.create_job(user_id=user_id, request_json='{}')
        db.fetch_next_queued_job()  # moves to running
        db.mark_completed(job_id, result_path="/tmp/result.csv")
        job = db.get_job(job_id)
        assert job["status"] == "completed"
        assert job["result_path"] == "/tmp/result.csv"
        assert job["completed_at"] is not None

    def test_mark_failed(self, db):
        """Mark a job as failed with error details."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        job_id = db.create_job(user_id=user_id, request_json='{}')
        db.fetch_next_queued_job()
        db.mark_failed(
            job_id,
            error_message="Login failed",
            error_detail="Full traceback...",
            page_url="https://example.com/login",
            page_html_path="/tmp/page.html",
            screenshot_path="/tmp/fail.png",
        )
        job = db.get_job(job_id)
        assert job["status"] == "failed"
        assert job["error_message"] == "Login failed"
        assert job["error_detail"] == "Full traceback..."

    def test_list_user_jobs(self, db):
        """List jobs for a specific user."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        db.create_job(user_id=user_id, request_json='{"n":1}')
        db.create_job(user_id=user_id, request_json='{"n":2}')
        jobs = db.list_user_jobs(user_id)
        assert len(jobs) == 2

    def test_update_progress(self, db):
        """Update a job's progress message."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        job_id = db.create_job(user_id=user_id, request_json='{}')
        db.update_progress(job_id, "Logging in...")
        job = db.get_job(job_id)
        assert job["progress"] == "Logging in..."


class TestServiceDBJobEvents:
    def test_add_event(self, db):
        """Add a job event and retrieve it."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        job_id = db.create_job(user_id=user_id, request_json='{}')
        db.add_event(job_id, event_type="progress", message="Logging in...")
        events = db.get_events(job_id)
        assert len(events) == 1
        assert events[0]["event_type"] == "progress"
        assert events[0]["message"] == "Logging in..."

    def test_events_ordered_by_timestamp(self, db):
        """Events are returned in chronological order."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        job_id = db.create_job(user_id=user_id, request_json='{}')
        db.add_event(job_id, event_type="progress", message="Step 1")
        db.add_event(job_id, event_type="progress", message="Step 2")
        events = db.get_events(job_id)
        assert events[0]["message"] == "Step 1"
        assert events[1]["message"] == "Step 2"


class TestServiceDBChatSessions:
    def test_create_chat_session(self, db):
        """Create a chat session and retrieve it."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        session_id = db.create_chat_session(user_id=user_id, messages_json="[]")
        session = db.get_chat_session(session_id)
        assert session is not None
        assert session["user_id"] == user_id

    def test_update_chat_session(self, db):
        """Update a chat session's messages and resolved request."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        session_id = db.create_chat_session(user_id=user_id, messages_json="[]")
        db.update_chat_session(
            session_id,
            messages_json='[{"role":"user","content":"test"}]',
            resolved_request_json='{"dataset":"D","rows":["R"]}',
        )
        session = db.get_chat_session(session_id)
        assert '"role":"user"' in session["messages_json"]
        assert session["resolved_request_json"] is not None

    def test_link_chat_to_job(self, db):
        """Link a chat session to a job."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        session_id = db.create_chat_session(user_id=user_id, messages_json="[]")
        job_id = db.create_job(user_id=user_id, request_json='{}')
        db.link_chat_to_job(session_id, job_id)
        session = db.get_chat_session(session_id)
        assert session["job_id"] == job_id


class TestServiceDBSessionEvents:
    def test_add_session_event(self, db):
        """Add a session event and retrieve it."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        session_id = db.create_chat_session(user_id=user_id, messages_json="[]")
        db.add_session_event(
            session_id, event_type="user_message", message="Hello",
        )
        events = db.get_session_events(session_id)
        assert len(events) == 1
        assert events[0]["event_type"] == "user_message"
        assert events[0]["message"] == "Hello"

    def test_session_events_ordered_by_timestamp(self, db):
        """Session events are returned in chronological order."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        session_id = db.create_chat_session(user_id=user_id, messages_json="[]")
        db.add_session_event(session_id, event_type="user_message", message="First")
        db.add_session_event(session_id, event_type="tool_call", message="search")
        events = db.get_session_events(session_id)
        assert events[0]["message"] == "First"
        assert events[1]["message"] == "search"

    def test_session_event_with_metadata(self, db):
        """Session events can store JSON metadata."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        session_id = db.create_chat_session(user_id=user_id, messages_json="[]")
        db.add_session_event(
            session_id, event_type="tool_call", message="search_dictionary",
            metadata_json='{"query": "income", "limit": 10}',
        )
        events = db.get_session_events(session_id)
        assert events[0]["metadata_json"] == '{"query": "income", "limit": 10}'
