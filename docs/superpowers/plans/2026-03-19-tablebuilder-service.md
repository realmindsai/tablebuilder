# TableBuilder-as-a-Service Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the existing TableBuilder CLI in a FastAPI service with async job queue, conversational chat UI, and MCP tools.

**Architecture:** Single FastAPI process with a background worker thread. SQLite for job queue and user management. Claude API for natural language query resolution against the existing dictionary DB. HTMX + Jinja2 for the web UI.

**Tech Stack:** FastAPI, uvicorn, Jinja2, HTMX, Pico CSS, anthropic SDK, cryptography (Fernet), SQLite

**Spec:** `docs/superpowers/specs/2026-03-18-tablebuilder-service-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `src/tablebuilder/service/__init__.py` | Package marker |
| `src/tablebuilder/service/db.py` | SQLite connection, schema migrations, CRUD queries for users/jobs/events/chat |
| `src/tablebuilder/service/auth.py` | API key generation, SHA-256 hashing, Fernet credential encryption/decryption |
| `src/tablebuilder/service/job_logger.py` | Write job_events rows, capture screenshots, save page HTML |
| `src/tablebuilder/service/worker.py` | Background thread polling jobs table, runs existing pipeline |
| `src/tablebuilder/service/routes_api.py` | FastAPI router: /api/auth, /api/jobs, /api/search, /api/datasets |
| `src/tablebuilder/service/routes_chat.py` | FastAPI router: /api/chat, /api/chat/confirm |
| `src/tablebuilder/service/routes_web.py` | FastAPI router: HTML pages /, /jobs |
| `src/tablebuilder/service/chat_resolver.py` | Claude API tool-use against dictionary DB to resolve NL → TableRequest |
| `src/tablebuilder/service/mcp_tools.py` | MCP tool definitions wrapping REST API |
| `src/tablebuilder/service/app.py` | FastAPI app creation, lifespan (worker start/stop), route registration |
| `src/tablebuilder/service/templates/base.html` | Jinja2 base template with Pico CSS + HTMX |
| `src/tablebuilder/service/templates/chat.html` | Chat page template |
| `src/tablebuilder/service/templates/jobs.html` | Jobs dashboard template |
| `src/tablebuilder/service/templates/job_detail.html` | Single job detail with screenshot filmstrip |
| `tests/test_service_db.py` | Tests for db.py |
| `tests/test_service_auth.py` | Tests for auth.py |
| `tests/test_service_job_logger.py` | Tests for job_logger.py |
| `tests/test_service_worker.py` | Tests for worker.py |
| `tests/test_service_routes_api.py` | Tests for routes_api.py |
| `tests/test_service_routes_chat.py` | Tests for routes_chat.py |
| `tests/test_service_chat_resolver.py` | Tests for chat_resolver.py |
| `tests/test_service_e2e.py` | End-to-end: register → submit → poll → download |
| `deploy/tablebuilder-service.service` | Systemd unit file |
| `deploy/deploy.sh` | Deployment script |

### Modified Files

| File | Change |
|------|--------|
| `pyproject.toml` | Add fastapi, uvicorn, jinja2, anthropic, cryptography deps |
| `src/tablebuilder/cli.py` | Add `serve` command |

---

## Chunk 1: Foundation — Dependencies, Database, Auth

### Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add service dependencies to pyproject.toml**

Add to `dependencies` list:
```toml
"fastapi>=0.115",
"uvicorn>=0.34",
"jinja2>=3.1",
"anthropic>=0.52",
"cryptography>=44.0",
```

Add to `[dependency-groups] dev`:
```toml
"httpx>=0.28",
```

(`httpx` is needed for FastAPI's `TestClient`.)

- [ ] **Step 2: Install dependencies**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv sync`
Expected: All packages installed successfully

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add FastAPI service dependencies"
```

---

### Task 2: Database Layer

**Files:**
- Create: `src/tablebuilder/service/__init__.py`
- Create: `src/tablebuilder/service/db.py`
- Test: `tests/test_service_db.py`

- [ ] **Step 1: Create service package**

Create `src/tablebuilder/service/__init__.py`:
```python
# ABOUTME: FastAPI service package for TableBuilder-as-a-Service.
# ABOUTME: Provides async job queue, REST API, chat UI, and MCP tools.
```

- [ ] **Step 2: Write failing tests for database layer**

Create `tests/test_service_db.py`:
```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_db.py -v`
Expected: ImportError — `tablebuilder.service.db` does not exist

- [ ] **Step 4: Implement ServiceDB**

Create `src/tablebuilder/service/db.py`:
```python
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
    job_id TEXT REFERENCES jobs(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_db.py -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/tablebuilder/service/__init__.py src/tablebuilder/service/db.py tests/test_service_db.py
git commit -m "feat: add service database layer with users, jobs, events, chat tables"
```

---

### Task 3: Auth Module

**Files:**
- Create: `src/tablebuilder/service/auth.py`
- Test: `tests/test_service_auth.py`

- [ ] **Step 1: Write failing tests for auth**

Create `tests/test_service_auth.py`:
```python
# ABOUTME: Tests for API key generation, hashing, and credential encryption.
# ABOUTME: Validates the auth module's cryptographic operations.

import pytest

from tablebuilder.service.auth import (
    generate_api_key,
    hash_api_key,
    encrypt_credentials,
    decrypt_credentials,
    generate_encryption_key,
)


class TestApiKeyGeneration:
    def test_generate_api_key_returns_string(self):
        key = generate_api_key()
        assert isinstance(key, str)
        assert len(key) > 20

    def test_generate_api_key_unique(self):
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100

    def test_hash_api_key_deterministic(self):
        key = "test-key-123"
        h1 = hash_api_key(key)
        h2 = hash_api_key(key)
        assert h1 == h2

    def test_hash_api_key_different_inputs(self):
        h1 = hash_api_key("key1")
        h2 = hash_api_key("key2")
        assert h1 != h2


class TestCredentialEncryption:
    def test_roundtrip(self):
        key = generate_encryption_key()
        user_id = "testuser@abs.gov.au"
        password = "s3cret!pass"
        encrypted = encrypt_credentials(key, user_id, password)
        dec_user, dec_pass = decrypt_credentials(key, encrypted)
        assert dec_user == user_id
        assert dec_pass == password

    def test_encrypted_is_not_plaintext(self):
        key = generate_encryption_key()
        encrypted = encrypt_credentials(key, "user", "pass")
        assert "user" not in encrypted
        assert "pass" not in encrypted

    def test_wrong_key_fails(self):
        key1 = generate_encryption_key()
        key2 = generate_encryption_key()
        encrypted = encrypt_credentials(key1, "user", "pass")
        with pytest.raises(Exception):
            decrypt_credentials(key2, encrypted)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_auth.py -v`
Expected: ImportError

- [ ] **Step 3: Implement auth module**

Create `src/tablebuilder/service/auth.py`:
```python
# ABOUTME: API key generation, hashing, and credential encryption for the service.
# ABOUTME: Uses SHA-256 for API key hashing and Fernet for credential encryption.

import hashlib
import json
import secrets

from cryptography.fernet import Fernet


def generate_api_key() -> str:
    """Generate a cryptographically random API key."""
    return f"tb_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    """SHA-256 hash an API key for storage."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_encryption_key() -> str:
    """Generate a new Fernet encryption key (base64-encoded)."""
    return Fernet.generate_key().decode()


def encrypt_credentials(encryption_key: str, user_id: str, password: str) -> str:
    """Encrypt ABS credentials using Fernet. Returns base64-encoded ciphertext."""
    f = Fernet(encryption_key.encode())
    payload = json.dumps({"user_id": user_id, "password": password})
    return f.encrypt(payload.encode()).decode()


def decrypt_credentials(encryption_key: str, encrypted: str) -> tuple[str, str]:
    """Decrypt ABS credentials. Returns (user_id, password)."""
    f = Fernet(encryption_key.encode())
    payload = json.loads(f.decrypt(encrypted.encode()).decode())
    return payload["user_id"], payload["password"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_auth.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/tablebuilder/service/auth.py tests/test_service_auth.py
git commit -m "feat: add auth module with API key hashing and Fernet credential encryption"
```

---

### Task 4: Job Logger

**Files:**
- Create: `src/tablebuilder/service/job_logger.py`
- Test: `tests/test_service_job_logger.py`

- [ ] **Step 1: Write failing tests for job logger**

Create `tests/test_service_job_logger.py`:
```python
# ABOUTME: Tests for job event logging and screenshot capture.
# ABOUTME: Validates that the logger writes events and captures artifacts.

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tablebuilder.service.db import ServiceDB
from tablebuilder.service.job_logger import JobLogger


@pytest.fixture
def db(tmp_path):
    return ServiceDB(tmp_path / "test.db")


@pytest.fixture
def results_dir(tmp_path):
    return tmp_path / "results"


@pytest.fixture
def logger(db, results_dir):
    user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
    job_id = db.create_job(user_id=user_id, request_json='{}')
    return JobLogger(db=db, job_id=job_id, results_dir=results_dir)


class TestJobLoggerEvents:
    def test_log_progress(self, logger, db):
        logger.log_progress("Logging in...")
        events = db.get_events(logger.job_id)
        assert len(events) == 1
        assert events[0]["event_type"] == "progress"
        assert events[0]["message"] == "Logging in..."

    def test_log_progress_updates_job(self, logger, db):
        logger.log_progress("Building table...")
        job = db.get_job(logger.job_id)
        assert job["progress"] == "Building table..."

    def test_log_warning(self, logger, db):
        logger.log_warning("Session expired, retrying")
        events = db.get_events(logger.job_id)
        assert events[0]["event_type"] == "warning"

    def test_log_error(self, logger, db):
        logger.log_error("Login failed", detail="Traceback...")
        events = db.get_events(logger.job_id)
        assert events[0]["event_type"] == "error"
        assert events[0]["detail"] == "Traceback..."


class TestJobLoggerScreenshots:
    def test_capture_screenshot(self, logger, results_dir):
        page = MagicMock()
        logger.capture_screenshot(page, "after_login")
        expected_dir = results_dir / logger.job_id / "screenshots"
        assert expected_dir.exists()
        # Verify page.screenshot was called with a path in the right directory
        call_args = page.screenshot.call_args
        path = Path(call_args.kwargs["path"])
        assert "after_login" in path.name
        assert path.parent == expected_dir

    def test_screenshot_counter_increments(self, logger):
        page = MagicMock()
        logger.capture_screenshot(page, "step1")
        logger.capture_screenshot(page, "step2")
        call1 = page.screenshot.call_args_list[0]
        call2 = page.screenshot.call_args_list[1]
        path1 = Path(call1.kwargs["path"]).name
        path2 = Path(call2.kwargs["path"]).name
        assert path1.startswith("001_")
        assert path2.startswith("002_")

    def test_capture_screenshot_handles_error(self, logger, db):
        """If page.screenshot raises, log a warning but don't crash."""
        page = MagicMock()
        page.screenshot.side_effect = Exception("Browser crashed")
        logger.capture_screenshot(page, "failure")
        events = db.get_events(logger.job_id)
        assert any(e["event_type"] == "warning" for e in events)


class TestJobLoggerPageCapture:
    def test_save_page_html(self, logger, results_dir):
        page = MagicMock()
        page.content.return_value = "<html><body>Hello</body></html>"
        page.url = "https://tablebuilder.abs.gov.au/some/page"
        path = logger.save_page_state(page)
        assert Path(path).exists()
        assert "<html>" in Path(path).read_text()

    def test_save_page_state_handles_error(self, logger):
        """If page.content() raises, return empty string."""
        page = MagicMock()
        page.content.side_effect = Exception("Browser crashed")
        path = logger.save_page_state(page)
        assert path == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_job_logger.py -v`
Expected: ImportError

- [ ] **Step 3: Implement job logger**

Create `src/tablebuilder/service/job_logger.py`:
```python
# ABOUTME: Job event logger with screenshot capture for production debugging.
# ABOUTME: Records every state transition and captures browser screenshots at each step.

from pathlib import Path

from tablebuilder.logging_config import get_logger
from tablebuilder.service.db import ServiceDB

logger = get_logger("tablebuilder.service.job_logger")


class JobLogger:
    """Logs job events and captures screenshots for a single job run."""

    def __init__(self, db: ServiceDB, job_id: str, results_dir: Path):
        self.db = db
        self.job_id = job_id
        self.results_dir = results_dir
        self._screenshot_counter = 0

    def _screenshots_dir(self) -> Path:
        d = self.results_dir / self.job_id / "screenshots"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def log_progress(self, message: str) -> None:
        self.db.add_event(self.job_id, event_type="progress", message=message)
        self.db.update_progress(self.job_id, message)
        logger.info("Job %s: %s", self.job_id[:8], message)

    def log_warning(self, message: str, detail: str = "") -> None:
        self.db.add_event(
            self.job_id, event_type="warning", message=message, detail=detail
        )
        logger.warning("Job %s: %s", self.job_id[:8], message)

    def log_error(self, message: str, detail: str = "") -> None:
        self.db.add_event(
            self.job_id, event_type="error", message=message, detail=detail
        )
        logger.error("Job %s: %s", self.job_id[:8], message)

    def capture_screenshot(self, page, label: str) -> str:
        """Take a screenshot and log it. Returns the file path, or empty string on error."""
        self._screenshot_counter += 1
        filename = f"{self._screenshot_counter:03d}_{label}.png"
        filepath = self._screenshots_dir() / filename
        try:
            page.screenshot(path=str(filepath))
            self.db.add_event(
                self.job_id,
                event_type="screenshot",
                message=f"Screenshot: {label}",
                screenshot_path=str(filepath),
            )
            return str(filepath)
        except Exception as e:
            self.log_warning(
                f"Failed to capture screenshot '{label}': {e}"
            )
            return ""

    def save_page_state(self, page) -> str:
        """Save page HTML and URL for debugging. Returns HTML file path, or empty string on error."""
        try:
            html_content = page.content()
            url = page.url
            html_path = self.results_dir / self.job_id / "page_state.html"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(
                f"<!-- URL: {url} -->\n{html_content}"
            )
            self.db.add_event(
                self.job_id,
                event_type="error",
                message=f"Page state saved (URL: {url})",
                detail=str(html_path),
            )
            return str(html_path)
        except Exception as e:
            logger.error("Failed to save page state for job %s: %s", self.job_id[:8], e)
            return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_job_logger.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/tablebuilder/service/job_logger.py tests/test_service_job_logger.py
git commit -m "feat: add job logger with screenshot capture and event timeline"
```

---

## Chunk 2: Worker and API Routes

### Task 5: Worker

**Files:**
- Create: `src/tablebuilder/service/worker.py`
- Test: `tests/test_service_worker.py`

The worker runs the existing pipeline (`TableBuilderSession` → `open_dataset` → `build_table` → `queue_and_download`) in a background thread. Each function is imported from the existing modules and called with the same arguments as `cli.py:fetch`.

- [ ] **Step 1: Write failing tests for worker**

Create `tests/test_service_worker.py`:
```python
# ABOUTME: Tests for the background job worker thread.
# ABOUTME: Validates job lifecycle, error handling, and screenshot capture.

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tablebuilder.service.db import ServiceDB
from tablebuilder.service.worker import Worker


@pytest.fixture
def db(tmp_path):
    return ServiceDB(tmp_path / "test.db")


@pytest.fixture
def results_dir(tmp_path):
    return tmp_path / "results"


@pytest.fixture
def encryption_key():
    from tablebuilder.service.auth import generate_encryption_key
    return generate_encryption_key()


def _create_test_job(db, encryption_key):
    """Helper to create a user and job for testing."""
    from tablebuilder.service.auth import encrypt_credentials
    creds = encrypt_credentials(encryption_key, "testuser", "testpass")
    user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted=creds)
    request = {"dataset": "Test", "rows": ["VAR1"], "cols": [], "wafers": []}
    job_id = db.create_job(user_id=user_id, request_json=json.dumps(request))
    return job_id


class TestWorkerJobLifecycle:
    @patch("tablebuilder.service.worker.TableBuilderSession")
    @patch("tablebuilder.service.worker.open_dataset")
    @patch("tablebuilder.service.worker.build_table")
    @patch("tablebuilder.service.worker.queue_and_download")
    def test_successful_job(
        self, mock_download, mock_build, mock_open, mock_session,
        db, results_dir, encryption_key
    ):
        """A successful job moves from queued → running → completed."""
        mock_page = MagicMock()
        mock_session_instance = MagicMock()
        mock_session_instance.__enter__ = MagicMock(return_value=mock_page)
        mock_session_instance.__exit__ = MagicMock(return_value=False)
        mock_session.return_value = mock_session_instance

        job_id = _create_test_job(db, encryption_key)

        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        worker.process_one_job()

        job = db.get_job(job_id)
        assert job["status"] == "completed"
        events = db.get_events(job_id)
        assert any("Logging in" in e["message"] for e in events)
        assert any("Download complete" in e["message"] for e in events)

    @patch("tablebuilder.service.worker.TableBuilderSession")
    def test_failed_job_captures_error(
        self, mock_session, db, results_dir, encryption_key
    ):
        """A failed job records error message, detail, and marks as failed."""
        mock_session.side_effect = Exception("Browser exploded")

        job_id = _create_test_job(db, encryption_key)

        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        worker.process_one_job()

        job = db.get_job(job_id)
        assert job["status"] == "failed"
        assert "Browser exploded" in job["error_message"]

    @patch("tablebuilder.service.worker.TableBuilderSession")
    @patch("tablebuilder.service.worker.open_dataset")
    def test_session_expired_marks_failed(
        self, mock_open, mock_session, db, results_dir, encryption_key
    ):
        """SessionExpiredError during pipeline marks job as failed with event log."""
        from tablebuilder.navigator import SessionExpiredError

        mock_page = MagicMock()
        mock_session_instance = MagicMock()
        mock_session_instance.__enter__ = MagicMock(return_value=mock_page)
        mock_session_instance.__exit__ = MagicMock(return_value=False)
        mock_session.return_value = mock_session_instance
        mock_open.side_effect = SessionExpiredError("Session expired")

        job_id = _create_test_job(db, encryption_key)

        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        worker.process_one_job()

        job = db.get_job(job_id)
        assert job["status"] == "failed"
        assert "Session expired" in job["error_message"]
        events = db.get_events(job_id)
        assert any("Session expired" in e["message"] or "relogin" in e["message"].lower() for e in events)

    def test_no_jobs_returns_false(self, db, results_dir, encryption_key):
        """process_one_job returns False when no jobs are queued."""
        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        assert worker.process_one_job() is False


class TestWorkerThread:
    def test_start_and_stop(self, db, results_dir, encryption_key):
        """Worker can be started and stopped cleanly."""
        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        worker.start()
        assert worker.is_alive()
        worker.stop()
        worker.join(timeout=10)
        assert not worker.is_alive()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_worker.py -v`
Expected: ImportError

- [ ] **Step 3: Implement worker**

Create `src/tablebuilder/service/worker.py`:
```python
# ABOUTME: Background worker thread that processes TableBuilder fetch jobs.
# ABOUTME: Calls the existing pipeline (login → open dataset → build table → download).

import json
import sys
import threading
import traceback
import time
from pathlib import Path

from tablebuilder.browser import TableBuilderSession
from tablebuilder.config import Config
from tablebuilder.downloader import queue_and_download
from tablebuilder.knowledge import KnowledgeBase
from tablebuilder.logging_config import get_logger
from tablebuilder.models import TableRequest
from tablebuilder.navigator import open_dataset, SessionExpiredError
from tablebuilder.service.auth import decrypt_credentials
from tablebuilder.service.db import ServiceDB
from tablebuilder.service.job_logger import JobLogger
from tablebuilder.table_builder import build_table

logger = get_logger("tablebuilder.service.worker")


class Worker(threading.Thread):
    """Background thread that polls for queued jobs and runs them."""

    def __init__(
        self,
        db: ServiceDB,
        results_dir: Path,
        encryption_key: str,
        poll_interval: float = 5.0,
    ):
        super().__init__(daemon=True, name="tablebuilder-worker")
        self.db = db
        self.results_dir = results_dir
        self.encryption_key = encryption_key
        self.poll_interval = poll_interval
        self.knowledge = KnowledgeBase()
        self._stop_event = threading.Event()

    def run(self) -> None:
        logger.info("Worker started")
        while not self._stop_event.is_set():
            try:
                if not self.process_one_job():
                    self._stop_event.wait(self.poll_interval)
            except Exception:
                logger.exception("Unexpected worker error")
                self._stop_event.wait(self.poll_interval)
        logger.info("Worker stopped")

    def stop(self) -> None:
        self._stop_event.set()

    def is_alive(self) -> bool:
        return super().is_alive()

    def process_one_job(self) -> bool:
        """Process one queued job. Returns True if a job was found, False otherwise."""
        job = self.db.fetch_next_queued_job()
        if job is None:
            return False

        job_id = job["id"]
        jl = JobLogger(db=self.db, job_id=job_id, results_dir=self.results_dir)

        result_path = self.results_dir / job_id / "output.csv"
        result_path.parent.mkdir(parents=True, exist_ok=True)

        user_id, password = decrypt_credentials(
            self.encryption_key, job["abs_credentials_encrypted"]
        )
        config = Config(user_id=user_id, password=password)
        request = TableRequest(**json.loads(job["request_json"]))
        job_timeout = job["timeout_seconds"] or 600

        page = None
        session = None
        try:
            jl.log_progress("Logging in...")
            session = TableBuilderSession(config, headless=True, knowledge=self.knowledge)
            page = session.__enter__()
            jl.capture_screenshot(page, "after_login")

            jl.log_progress("Opening dataset...")
            open_dataset(page, request.dataset, knowledge=self.knowledge)
            jl.capture_screenshot(page, "dataset_opened")

            jl.log_progress("Building table...")
            build_table(page, request, knowledge=self.knowledge)
            jl.capture_screenshot(page, "table_built")

            jl.log_progress("Queuing download...")
            queue_and_download(
                page, str(result_path), timeout=job_timeout, knowledge=self.knowledge
            )
            jl.capture_screenshot(page, "download_complete")
            jl.log_progress("Download complete")

            session.__exit__(None, None, None)
            session = None
            self.db.mark_completed(job_id, str(result_path))
            self.knowledge.save()

        except SessionExpiredError:
            jl.log_warning("Session expired, attempting relogin...")
            if session:
                try:
                    session.relogin()
                    jl.log_progress("Relogin successful, but job needs manual retry")
                except Exception:
                    pass
                session.__exit__(None, None, None)
                session = None
            self.db.mark_failed(
                job_id, error_message="Session expired during job execution"
            )

        except Exception as e:
            tb = traceback.format_exc()
            screenshot_path = ""
            page_html_path = ""
            page_url = ""
            if page:
                screenshot_path = jl.capture_screenshot(page, "failure")
                page_html_path = jl.save_page_state(page)
                page_url = page.url
            jl.log_error(str(e), detail=tb)
            if session:
                session.__exit__(*sys.exc_info())
                session = None
            self.db.mark_failed(
                job_id,
                error_message=str(e),
                error_detail=tb,
                page_url=page_url,
                page_html_path=page_html_path,
                screenshot_path=screenshot_path,
            )
            self.knowledge.save()

        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_worker.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/tablebuilder/service/worker.py tests/test_service_worker.py
git commit -m "feat: add background worker thread for processing fetch jobs"
```

---

### Task 6: API Routes — Auth and Dictionary

**Files:**
- Create: `src/tablebuilder/service/routes_api.py`
- Test: `tests/test_service_routes_api.py`

These routes don't depend on the worker — they handle registration, credential verification, dictionary search, and dataset listing.

- [ ] **Step 1: Write failing tests for auth and dictionary routes**

Create `tests/test_service_routes_api.py`:
```python
# ABOUTME: Tests for the service REST API routes.
# ABOUTME: Covers auth registration, job CRUD, dictionary search, and error responses.

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tablebuilder.service.app import create_app
from tablebuilder.service.auth import generate_encryption_key


@pytest.fixture
def app_env(tmp_path):
    """Set up a test app with temporary database and results directory."""
    db_path = tmp_path / "test.db"
    results_dir = tmp_path / "results"
    encryption_key = generate_encryption_key()
    app = create_app(
        db_path=db_path,
        results_dir=results_dir,
        encryption_key=encryption_key,
        start_worker=False,
    )
    return app, db_path, results_dir, encryption_key


@pytest.fixture
def client(app_env):
    app, _, _, _ = app_env
    return TestClient(app)


@pytest.fixture
def registered_client(client):
    """A client with a registered user. Returns (client, api_key)."""
    resp = client.post("/api/auth/register", json={
        "abs_user_id": "testuser",
        "abs_password": "testpass",
    })
    api_key = resp.json()["api_key"]
    return client, api_key


class TestAuthRegister:
    def test_register_returns_api_key(self, client):
        resp = client.post("/api/auth/register", json={
            "abs_user_id": "testuser",
            "abs_password": "testpass",
        })
        assert resp.status_code == 200
        assert "api_key" in resp.json()
        assert resp.json()["api_key"].startswith("tb_")

    def test_register_missing_fields(self, client):
        resp = client.post("/api/auth/register", json={"abs_user_id": "test"})
        assert resp.status_code == 422


class TestAuthVerify:
    @patch("tablebuilder.service.routes_api.TableBuilderSession")
    def test_verify_valid_credentials(self, mock_session, registered_client):
        mock_page = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_page)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        client, api_key = registered_client
        resp = client.post(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "valid"

    @patch("tablebuilder.service.routes_api.TableBuilderSession")
    def test_verify_invalid_credentials(self, mock_session, registered_client):
        from tablebuilder.browser import LoginError
        mock_session.return_value.__enter__ = MagicMock(side_effect=LoginError("Bad creds"))
        client, api_key = registered_client
        resp = client.post(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 401

    def test_verify_without_auth(self, client):
        resp = client.post("/api/auth/verify")
        assert resp.status_code == 401


class TestAuthDelete:
    def test_delete_credentials(self, registered_client):
        client, api_key = registered_client
        resp = client.delete(
            "/api/auth/credentials",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        # Subsequent request should fail
        resp = client.get(
            "/api/jobs",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 401

    def test_delete_without_auth(self, client):
        resp = client.delete("/api/auth/credentials")
        assert resp.status_code == 401


class TestDictionarySearch:
    def test_search_no_auth_required(self, client):
        """Dictionary search does not require authentication."""
        resp = client.get("/api/search", params={"q": "population"})
        # Should return 200 even without auth (may return empty results)
        assert resp.status_code == 200

    def test_search_returns_list(self, client):
        resp = client.get("/api/search", params={"q": "age"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestJobSubmission:
    def test_submit_job(self, registered_client):
        client, api_key = registered_client
        resp = client.post(
            "/api/jobs",
            json={
                "dataset": "Test Dataset",
                "rows": ["VAR1"],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "queued"

    def test_submit_job_without_auth(self, client):
        resp = client.post("/api/jobs", json={"dataset": "X", "rows": ["Y"]})
        assert resp.status_code == 401

    def test_submit_job_empty_rows(self, registered_client):
        client, api_key = registered_client
        resp = client.post(
            "/api/jobs",
            json={"dataset": "Test", "rows": []},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    def test_get_job_status(self, registered_client):
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = client.post(
            "/api/jobs",
            json={"dataset": "Test", "rows": ["V"]},
            headers=headers,
        )
        job_id = resp.json()["job_id"]
        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_list_jobs(self, registered_client):
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}
        client.post("/api/jobs", json={"dataset": "D", "rows": ["R"]}, headers=headers)
        client.post("/api/jobs", json={"dataset": "D", "rows": ["R"]}, headers=headers)
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_download_before_completion(self, registered_client):
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = client.post(
            "/api/jobs",
            json={"dataset": "D", "rows": ["R"]},
            headers=headers,
        )
        job_id = resp.json()["job_id"]
        resp = client.get(f"/api/jobs/{job_id}/download", headers=headers)
        assert resp.status_code == 409

    def test_get_job_events(self, registered_client):
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = client.post(
            "/api/jobs",
            json={"dataset": "D", "rows": ["R"]},
            headers=headers,
        )
        job_id = resp.json()["job_id"]
        resp = client.get(f"/api/jobs/{job_id}/events", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_routes_api.py -v`
Expected: ImportError — `create_app` does not exist

- [ ] **Step 3: Implement routes_api.py**

Create `src/tablebuilder/service/routes_api.py`:
```python
# ABOUTME: REST API routes for auth, jobs, dictionary search, and datasets.
# ABOUTME: Handles job submission (202 Accepted), polling, and result download.

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from tablebuilder.config import Config
from tablebuilder.service.auth import (
    decrypt_credentials,
    encrypt_credentials,
    generate_api_key,
    hash_api_key,
)
from tablebuilder.service.db import ServiceDB

router = APIRouter(prefix="/api")


# -- Pydantic models --

class RegisterRequest(BaseModel):
    abs_user_id: str
    abs_password: str


class JobRequest(BaseModel):
    dataset: str
    rows: list[str]
    cols: list[str] = []
    wafers: list[str] = []
    timeout_seconds: int = 600

    @field_validator("rows")
    @classmethod
    def rows_not_empty(cls, v):
        if not v:
            raise ValueError("rows must contain at least one variable")
        return v


# -- Auth dependency --

async def get_current_user(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
    api_key = authorization.removeprefix("Bearer ")
    key_hash = hash_api_key(api_key)
    db: ServiceDB = request.app.state.db
    user = db.get_user_by_api_key_hash(key_hash)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    db.touch_user(user["id"])
    return user


# -- Auth routes --

@router.post("/auth/register")
async def register(body: RegisterRequest, request: Request):
    db: ServiceDB = request.app.state.db
    encryption_key: str = request.app.state.encryption_key
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    encrypted_creds = encrypt_credentials(
        encryption_key, body.abs_user_id, body.abs_password
    )
    db.create_user(api_key_hash=key_hash, abs_credentials_encrypted=encrypted_creds)
    return {"api_key": api_key}


@router.post("/auth/verify")
async def verify_credentials(
    request: Request, user: dict = Depends(get_current_user)
):
    """Test stored credentials by attempting an ABS login."""
    from tablebuilder.browser import TableBuilderSession, LoginError

    db: ServiceDB = request.app.state.db
    encryption_key: str = request.app.state.encryption_key
    abs_user, abs_pass = decrypt_credentials(
        encryption_key, user["abs_credentials_encrypted"]
    )
    config = Config(user_id=abs_user, password=abs_pass)
    try:
        with TableBuilderSession(config, headless=True) as page:
            pass  # login happens in __enter__
        return {"status": "valid", "message": "Credentials verified successfully"}
    except LoginError as e:
        raise HTTPException(status_code=401, detail=f"Credential verification failed: {e}")


@router.delete("/auth/credentials")
async def delete_credentials(
    request: Request, user: dict = Depends(get_current_user)
):
    db: ServiceDB = request.app.state.db
    db.delete_user(user["id"])
    return {"status": "deleted"}


# -- Job routes --

@router.post("/jobs", status_code=202)
async def submit_job(
    body: JobRequest, request: Request, user: dict = Depends(get_current_user)
):
    db: ServiceDB = request.app.state.db
    request_json = json.dumps({
        "dataset": body.dataset,
        "rows": body.rows,
        "cols": body.cols,
        "wafers": body.wafers,
    })
    job_id = db.create_job(
        user_id=user["id"],
        request_json=request_json,
        timeout_seconds=body.timeout_seconds,
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/jobs/{job_id}",
    }


@router.get("/jobs")
async def list_jobs(request: Request, user: dict = Depends(get_current_user)):
    db: ServiceDB = request.app.state.db
    return db.list_user_jobs(user["id"])


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request, user: dict = Depends(get_current_user)):
    db: ServiceDB = request.app.state.db
    job = db.get_job(job_id)
    if job is None or job["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    result = {
        "job_id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
    }
    if job["status"] == "completed":
        result["result_url"] = f"/api/jobs/{job_id}/download"
    if job["status"] == "failed":
        result["error_message"] = job["error_message"]
    return result


@router.get("/jobs/{job_id}/download")
async def download_job(
    job_id: str, request: Request, user: dict = Depends(get_current_user)
):
    db: ServiceDB = request.app.state.db
    job = db.get_job(job_id)
    if job is None or job["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail={"error": "Job not yet completed", "status": job["status"]},
        )
    result_path = Path(job["result_path"])
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="Result file not found")
    return FileResponse(result_path, media_type="text/csv", filename="tablebuilder_result.csv")


@router.get("/jobs/{job_id}/events")
async def get_job_events(
    job_id: str, request: Request, user: dict = Depends(get_current_user)
):
    db: ServiceDB = request.app.state.db
    job = db.get_job(job_id)
    if job is None or job["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return db.get_events(job_id)


@router.get("/jobs/{job_id}/debug")
async def get_job_debug(
    job_id: str, request: Request, user: dict = Depends(get_current_user)
):
    db: ServiceDB = request.app.state.db
    job = db.get_job(job_id)
    if job is None or job["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "error_message": job["error_message"],
        "error_detail": job["error_detail"],
        "page_url": job["page_url"],
        "page_html_path": job["page_html_path"],
        "screenshot_path": job["screenshot_path"],
        "events": db.get_events(job_id),
    }


# -- Dictionary routes (no auth required) --

@router.get("/search")
async def search_dictionary(q: str, limit: int = 20):
    from tablebuilder.dictionary_db import search, DEFAULT_DB_PATH

    if not DEFAULT_DB_PATH.exists():
        return []
    return search(DEFAULT_DB_PATH, q, limit=limit)


@router.get("/datasets")
async def list_datasets():
    from tablebuilder.dictionary_db import DEFAULT_DB_PATH

    import sqlite3
    if not DEFAULT_DB_PATH.exists():
        return []
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT name, summary FROM datasets ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/datasets/{name}/variables")
async def get_dataset_variables(name: str):
    from tablebuilder.dictionary_db import get_dataset, DEFAULT_DB_PATH

    if not DEFAULT_DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Dictionary database not found")
    result = get_dataset(DEFAULT_DB_PATH, name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found")
    return result
```

- [ ] **Step 4: Implement app.py (minimal, needed by tests)**

Create `src/tablebuilder/service/app.py`:
```python
# ABOUTME: FastAPI application factory with lifespan for worker management.
# ABOUTME: Registers all route modules and starts/stops the background worker.

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from tablebuilder.service.db import ServiceDB
from tablebuilder.service.worker import Worker


DEFAULT_DB_PATH = Path.home() / ".tablebuilder" / "service.db"
DEFAULT_RESULTS_DIR = Path.home() / ".tablebuilder" / "results"


def create_app(
    db_path: Path = DEFAULT_DB_PATH,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    encryption_key: str = "",
    anthropic_api_key: str = "",
    start_worker: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    worker: Worker | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal worker
        if start_worker and encryption_key:
            worker = Worker(
                db=app.state.db,
                results_dir=results_dir,
                encryption_key=encryption_key,
            )
            worker.start()
        yield
        if worker:
            worker.stop()
            worker.join(timeout=30)

    app = FastAPI(title="TableBuilder Service", lifespan=lifespan)

    # Attach shared state
    app.state.db = ServiceDB(db_path)
    app.state.encryption_key = encryption_key
    app.state.results_dir = results_dir
    app.state.chat_resolver = None
    if anthropic_api_key:
        from tablebuilder.service.chat_resolver import ChatResolver
        app.state.chat_resolver = ChatResolver(anthropic_api_key=anthropic_api_key)

    # Register routes
    from tablebuilder.service.routes_api import router as api_router
    app.include_router(api_router)

    return app


def _create_default_app() -> FastAPI:
    """Module-level app factory for uvicorn. Reads config from env vars."""
    import os
    encryption_key = os.environ.get("DB_ENCRYPTION_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return create_app(encryption_key=encryption_key, anthropic_api_key=anthropic_key)


# Module-level instance for uvicorn (e.g., uvicorn tablebuilder.service.app:app)
app = _create_default_app()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_routes_api.py -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/tablebuilder/service/routes_api.py src/tablebuilder/service/app.py tests/test_service_routes_api.py
git commit -m "feat: add REST API routes for auth, jobs, dictionary search"
```

---

### Task 7: CLI Serve Command

**Files:**
- Modify: `src/tablebuilder/cli.py`

- [ ] **Step 1: Write failing test for serve command**

Add to `tests/test_cli.py`:
```python
class TestCliServe:
    def test_serve_help_shows_flags(self):
        """serve --help lists --port and --host."""
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--host" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_cli.py::TestCliServe -v`
Expected: FAIL — no `serve` command

- [ ] **Step 3: Add serve command to cli.py**

Add to `src/tablebuilder/cli.py` after the `search` command:
```python
@cli.command()
@click.option("--port", default=8080, type=int, help="Port to listen on (default: 8080).")
@click.option("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0).")
def serve(port, host):
    """Start the TableBuilder API service."""
    import os
    import uvicorn
    from tablebuilder.service.app import create_app

    encryption_key = os.environ.get("DB_ENCRYPTION_KEY", "")
    if not encryption_key:
        click.echo(
            "Warning: DB_ENCRYPTION_KEY not set. "
            "Credential encryption will not work.",
            err=True,
        )

    app = create_app(encryption_key=encryption_key)
    click.echo(f"Starting TableBuilder service on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_cli.py::TestCliServe -v`
Expected: PASS

- [ ] **Step 5: Run all existing tests to verify nothing broke**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest --ignore=tests/test_integration.py -q`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/tablebuilder/cli.py tests/test_cli.py
git commit -m "feat: add 'serve' CLI command to start FastAPI service"
```

---

## Chunk 3: Chat, Web UI, MCP, and Deployment

### Task 8: Chat Resolver

**Files:**
- Create: `src/tablebuilder/service/chat_resolver.py`
- Test: `tests/test_service_chat_resolver.py`

The chat resolver uses the Claude API with tool-use to search the dictionary DB and resolve natural language into a `TableRequest`.

- [ ] **Step 1: Write failing tests for chat resolver**

Create `tests/test_service_chat_resolver.py`:
```python
# ABOUTME: Tests for the Claude API chat resolver.
# ABOUTME: Validates NL → TableRequest resolution using mocked Claude responses.

from unittest.mock import MagicMock, patch

import pytest

from tablebuilder.service.chat_resolver import ChatResolver


class TestChatResolver:
    @patch("tablebuilder.service.chat_resolver.anthropic.Anthropic")
    def test_resolve_returns_interpretation(self, mock_anthropic_class):
        """Resolver returns an interpretation dict with dataset and variables."""
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client

        # Simulate Claude returning a final text response
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [
            MagicMock(
                type="text",
                text='{"dataset": "Census 2021", "rows": ["SEXP Sex"], "cols": [], "wafers": [], "confirmation": "I found Census 2021 with variable SEXP Sex. Shall I fetch this?"}',
            )
        ]
        mock_client.messages.create.return_value = mock_response

        # Create resolver INSIDE the patch scope so mock takes effect
        resolver = ChatResolver(anthropic_api_key="test-key")
        result = resolver.resolve("population by sex from 2021 census")
        assert "dataset" in result or "confirmation" in result

    def test_build_system_prompt(self):
        """System prompt mentions TableBuilder and dictionary."""
        resolver = ChatResolver(anthropic_api_key="test-key")
        prompt = resolver._build_system_prompt()
        assert "TableBuilder" in prompt
        assert "dictionary" in prompt.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_chat_resolver.py -v`
Expected: ImportError

- [ ] **Step 3: Implement chat resolver**

Create `src/tablebuilder/service/chat_resolver.py`:
```python
# ABOUTME: Claude API integration for resolving natural language into TableRequests.
# ABOUTME: Uses tool-use to search the dictionary DB and build structured requests.

import json

import anthropic

from tablebuilder.dictionary_db import DEFAULT_DB_PATH, search, get_dataset
from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.service.chat_resolver")

SYSTEM_PROMPT = """You are a data assistant for ABS TableBuilder. You help users find and request Australian Bureau of Statistics census data.

You have access to a dictionary of datasets and variables. Use the search_dictionary tool to find matching datasets and variables. Use get_dataset_variables to see the full variable tree for a specific dataset.

When the user asks for data, search the dictionary, identify the right dataset and variables, and propose a structured request. Always confirm with the user before they submit.

Respond with a JSON object containing:
- "dataset": the exact dataset name
- "rows": list of variable labels for rows (required, at least one)
- "cols": list of variable labels for columns (optional)
- "wafers": list of variable labels for wafers/layers (optional)
- "confirmation": a human-readable summary asking the user to confirm

If you need clarification (ambiguous dataset, multiple matches), ask a follow-up question instead of guessing. In that case, respond with:
- "clarification": the question to ask the user"""

TOOLS = [
    {
        "name": "search_dictionary",
        "description": "Search the ABS data dictionary for datasets and variables matching a query. Returns ranked results with dataset name, variable code, label, and categories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'population remoteness area')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_dataset_variables",
        "description": "Get the full variable tree for a specific dataset by exact name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_name": {
                    "type": "string",
                    "description": "Exact dataset name",
                },
            },
            "required": ["dataset_name"],
        },
    },
]


class ChatResolver:
    """Resolves natural language queries into TableRequests using Claude API."""

    def __init__(self, anthropic_api_key: str):
        self.api_key = anthropic_api_key
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _build_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return the result as a string."""
        if tool_name == "search_dictionary":
            if not DEFAULT_DB_PATH.exists():
                return json.dumps([])
            results = search(
                DEFAULT_DB_PATH,
                tool_input["query"],
                limit=tool_input.get("limit", 10),
            )
            return json.dumps(results)

        elif tool_name == "get_dataset_variables":
            if not DEFAULT_DB_PATH.exists():
                return json.dumps(None)
            result = get_dataset(DEFAULT_DB_PATH, tool_input["dataset_name"])
            return json.dumps(result)

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def resolve(
        self, user_message: str, conversation_history: list[dict] | None = None
    ) -> dict:
        """Resolve a natural language query. Returns a dict with either
        dataset/rows/cols/wafers/confirmation or clarification."""
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": user_message})

        # Allow up to 5 tool-use rounds
        for _ in range(5):
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=self._build_system_prompt(),
                tools=TOOLS,
                messages=messages,
            )

            # Check if Claude wants to use a tool
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if tool_use_blocks:
                # Execute all tool calls
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in tool_use_blocks:
                    result = self._handle_tool_call(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            # Claude returned a final text response — parse as JSON
            text_blocks = [b for b in response.content if b.type == "text"]
            if text_blocks:
                try:
                    return json.loads(text_blocks[0].text)
                except json.JSONDecodeError:
                    return {"clarification": text_blocks[0].text}

        return {"clarification": "I wasn't able to resolve your request. Could you be more specific?"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_chat_resolver.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/tablebuilder/service/chat_resolver.py tests/test_service_chat_resolver.py
git commit -m "feat: add Claude API chat resolver for NL → TableRequest"
```

---

### Task 9: Chat Routes

**Files:**
- Create: `src/tablebuilder/service/routes_chat.py`
- Test: `tests/test_service_routes_chat.py`

- [ ] **Step 1: Write failing tests for chat routes**

Create `tests/test_service_routes_chat.py`:
```python
# ABOUTME: Tests for the chat API routes.
# ABOUTME: Validates session creation, multi-turn conversation, and job confirmation.

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from tablebuilder.service.app import create_app
from tablebuilder.service.auth import generate_encryption_key


@pytest.fixture
def app_env(tmp_path):
    db_path = tmp_path / "test.db"
    results_dir = tmp_path / "results"
    encryption_key = generate_encryption_key()
    app = create_app(
        db_path=db_path,
        results_dir=results_dir,
        encryption_key=encryption_key,
        anthropic_api_key="test-key",
        start_worker=False,
    )
    return app


@pytest.fixture
def registered_client(app_env):
    client = TestClient(app_env)
    resp = client.post("/api/auth/register", json={
        "abs_user_id": "testuser",
        "abs_password": "testpass",
    })
    api_key = resp.json()["api_key"]
    return client, api_key


class TestChatRoutes:
    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_chat_creates_session(self, mock_resolve, registered_client):
        mock_resolve.return_value = {
            "dataset": "Census 2021",
            "rows": ["SEXP Sex"],
            "cols": [],
            "wafers": [],
            "confirmation": "Shall I fetch this?",
        }
        client, api_key = registered_client
        resp = client.post(
            "/api/chat",
            json={"message": "population by sex"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_chat_confirm_creates_job(self, mock_resolve, registered_client):
        mock_resolve.return_value = {
            "dataset": "Census 2021",
            "rows": ["SEXP Sex"],
            "cols": [],
            "wafers": [],
            "confirmation": "Shall I fetch this?",
        }
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}

        # Start chat
        resp = client.post(
            "/api/chat",
            json={"message": "population by sex"},
            headers=headers,
        )
        session_id = resp.json()["session_id"]

        # Confirm
        resp = client.post(
            "/api/chat/confirm",
            json={"session_id": session_id},
            headers=headers,
        )
        assert resp.status_code == 200
        assert "job_id" in resp.json()

    def test_chat_without_auth(self, app_env):
        client = TestClient(app_env)
        resp = client.post("/api/chat", json={"message": "test"})
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_routes_chat.py -v`
Expected: ImportError or test failures

- [ ] **Step 3: Implement chat routes**

Create `src/tablebuilder/service/routes_chat.py`:
```python
# ABOUTME: Chat API routes for natural language data requests.
# ABOUTME: Manages multi-turn conversation sessions and job confirmation.

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from tablebuilder.service.routes_api import get_current_user

router = APIRouter(prefix="/api")


class ChatMessage(BaseModel):
    message: str
    session_id: str | None = None


class ChatConfirm(BaseModel):
    session_id: str


@router.post("/chat")
async def chat(
    body: ChatMessage, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    resolver = request.app.state.chat_resolver

    if body.session_id:
        session = db.get_chat_session(body.session_id)
        if session is None or session["user_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Chat session not found")
        history = json.loads(session["messages_json"])
    else:
        session_id = db.create_chat_session(
            user_id=user["id"], messages_json="[]"
        )
        session = db.get_chat_session(session_id)
        history = []

    result = resolver.resolve(body.message, conversation_history=history)

    # Update history
    history.append({"role": "user", "content": body.message})
    history.append({"role": "assistant", "content": json.dumps(result)})

    resolved_json = None
    if "dataset" in result and "rows" in result:
        resolved_json = json.dumps({
            "dataset": result["dataset"],
            "rows": result["rows"],
            "cols": result.get("cols", []),
            "wafers": result.get("wafers", []),
        })

    db.update_chat_session(
        session["id"],
        messages_json=json.dumps(history),
        resolved_request_json=resolved_json,
    )

    return {
        "session_id": session["id"],
        "response": result,
    }


@router.post("/chat/confirm")
async def confirm_chat(
    body: ChatConfirm, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    session = db.get_chat_session(body.session_id)
    if session is None or session["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Chat session not found")

    if not session["resolved_request_json"]:
        raise HTTPException(
            status_code=400, detail="No resolved request to confirm"
        )

    request_data = json.loads(session["resolved_request_json"])
    request_json = json.dumps(request_data)

    job_id = db.create_job(user_id=user["id"], request_json=request_json)
    db.link_chat_to_job(session["id"], job_id)

    return {
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/jobs/{job_id}",
    }
```

- [ ] **Step 4: Register chat routes in app.py**

Add to `create_app` in `app.py`, after the API router registration:
```python
    from tablebuilder.service.routes_chat import router as chat_router
    app.include_router(chat_router)
```

(`anthropic_api_key` and `chat_resolver` were already added to `create_app` in Task 6.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_routes_chat.py -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/tablebuilder/service/routes_chat.py src/tablebuilder/service/app.py src/tablebuilder/cli.py tests/test_service_routes_chat.py
git commit -m "feat: add chat routes for conversational data requests"
```

---

### Task 10: Web UI Templates and Routes

**Files:**
- Create: `src/tablebuilder/service/routes_web.py`
- Create: `src/tablebuilder/service/templates/base.html`
- Create: `src/tablebuilder/service/templates/chat.html`
- Create: `src/tablebuilder/service/templates/jobs.html`
- Create: `src/tablebuilder/service/templates/job_detail.html`

- [ ] **Step 1: Create base template**

Create `src/tablebuilder/service/templates/base.html`:
```html
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}TableBuilder Service{% endblock %}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <style>
        .status-queued { color: grey; }
        .status-running { color: #1e88e5; }
        .status-completed { color: #43a047; }
        .status-failed { color: #e53935; }
        .chat-container { max-width: 800px; margin: 0 auto; }
        .chat-messages { min-height: 400px; max-height: 600px; overflow-y: auto; padding: 1rem; border: 1px solid var(--pico-muted-border-color); border-radius: var(--pico-border-radius); margin-bottom: 1rem; }
        .chat-message { margin-bottom: 1rem; }
        .chat-message.user { text-align: right; }
        .chat-message.assistant { text-align: left; }
        .chat-bubble { display: inline-block; padding: 0.5rem 1rem; border-radius: 1rem; max-width: 80%; }
        .chat-message.user .chat-bubble { background: var(--pico-primary-background); color: var(--pico-primary-inverse); }
        .chat-message.assistant .chat-bubble { background: var(--pico-muted-background); }
        .filmstrip { display: flex; gap: 0.5rem; overflow-x: auto; padding: 0.5rem 0; }
        .filmstrip img { height: 150px; border: 1px solid var(--pico-muted-border-color); border-radius: 4px; cursor: pointer; }
        .filmstrip img:hover { border-color: var(--pico-primary); }
        nav ul { list-style: none; display: flex; gap: 1rem; }
    </style>
</head>
<body>
    <nav class="container">
        <ul>
            <li><strong>TableBuilder Service</strong></li>
        </ul>
        <ul>
            <li><a href="/">Chat</a></li>
            <li><a href="/jobs">Jobs</a></li>
        </ul>
    </nav>
    <main class="container">
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

- [ ] **Step 2: Create chat template**

Create `src/tablebuilder/service/templates/chat.html`:
```html
{% extends "base.html" %}
{% block title %}Chat - TableBuilder Service{% endblock %}
{% block content %}
<div class="chat-container">
    <div id="chat-messages" class="chat-messages">
        {% if not api_key %}
        <article>
            <h3>Enter your ABS credentials</h3>
            <form hx-post="/web/register" hx-target="#chat-messages" hx-swap="innerHTML">
                <label for="abs_user_id">ABS User ID</label>
                <input type="text" name="abs_user_id" id="abs_user_id" required>
                <label for="abs_password">ABS Password</label>
                <input type="password" name="abs_password" id="abs_password" required>
                <button type="submit">Register</button>
            </form>
        </article>
        {% else %}
        <p>Ask me for ABS data. For example: "population by remoteness area from the 2021 census"</p>
        {% endif %}
    </div>
    {% if api_key %}
    <form hx-post="/web/chat" hx-target="#chat-messages" hx-swap="beforeend" hx-on::after-request="this.reset()">
        <input type="hidden" name="session_id" id="session_id" value="">
        <div role="group">
            <input type="text" name="message" placeholder="Ask for data..." required autofocus>
            <button type="submit">Send</button>
        </div>
    </form>
    {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 3: Create jobs template**

Create `src/tablebuilder/service/templates/jobs.html`:
```html
{% extends "base.html" %}
{% block title %}Jobs - TableBuilder Service{% endblock %}
{% block content %}
<h2>Your Jobs</h2>
{% if not api_key %}
<p>Please <a href="/">register</a> first.</p>
{% elif jobs %}
<table>
    <thead>
        <tr>
            <th>Dataset</th>
            <th>Status</th>
            <th>Submitted</th>
            <th>Duration</th>
            <th>Action</th>
        </tr>
    </thead>
    <tbody>
        {% for job in jobs %}
        <tr>
            <td>{{ job.dataset_name }}</td>
            <td><span class="status-{{ job.status }}">{{ job.status }}</span></td>
            <td>{{ job.created_at[:16] }}</td>
            <td>{{ job.duration or "-" }}</td>
            <td>
                {% if job.status == "completed" %}
                <a href="/api/jobs/{{ job.id }}/download">Download CSV</a>
                {% elif job.status == "failed" %}
                <a href="/jobs/{{ job.id }}">View Error</a>
                {% elif job.status == "running" %}
                <span hx-get="/web/job-status/{{ job.id }}" hx-trigger="every 10s" hx-swap="outerHTML">
                    {{ job.progress or "Starting..." }}
                </span>
                {% else %}
                Queued
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p>No jobs yet. <a href="/">Start a chat</a> to request data.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Create job detail template**

Create `src/tablebuilder/service/templates/job_detail.html`:
```html
{% extends "base.html" %}
{% block title %}Job {{ job.id[:8] }} - TableBuilder Service{% endblock %}
{% block content %}
<h2>Job {{ job.id[:8] }}</h2>
<dl>
    <dt>Status</dt>
    <dd><span class="status-{{ job.status }}">{{ job.status }}</span></dd>
    <dt>Dataset</dt>
    <dd>{{ job.dataset_name }}</dd>
    <dt>Submitted</dt>
    <dd>{{ job.created_at }}</dd>
    {% if job.error_message %}
    <dt>Error</dt>
    <dd>{{ job.error_message }}</dd>
    {% endif %}
</dl>

{% if events %}
<h3>Event Timeline</h3>
<table>
    <thead><tr><th>Time</th><th>Type</th><th>Message</th></tr></thead>
    <tbody>
        {% for event in events %}
        <tr>
            <td>{{ event.timestamp[:19] }}</td>
            <td>{{ event.event_type }}</td>
            <td>{{ event.message }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endif %}

{% if screenshots %}
<h3>Screenshots</h3>
<div class="filmstrip">
    {% for ss in screenshots %}
    <img src="/web/screenshot/{{ job.id }}/{{ ss }}" alt="{{ ss }}" title="{{ ss }}">
    {% endfor %}
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Implement web routes**

Create `src/tablebuilder/service/routes_web.py`:
```python
# ABOUTME: Web UI routes serving HTML pages for chat and job management.
# ABOUTME: Uses Jinja2 templates with HTMX for dynamic updates.

import json
from pathlib import Path

from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates

from tablebuilder.service.auth import (
    encrypt_credentials,
    generate_api_key,
    hash_api_key,
)

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _get_api_key_from_cookie(request: Request) -> str | None:
    return request.cookies.get("tb_api_key")


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    api_key = _get_api_key_from_cookie(request)
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "api_key": api_key,
    })


@router.post("/web/register", response_class=HTMLResponse)
async def web_register(
    request: Request,
    abs_user_id: str = Form(...),
    abs_password: str = Form(...),
):
    db = request.app.state.db
    encryption_key = request.app.state.encryption_key
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    encrypted = encrypt_credentials(encryption_key, abs_user_id, abs_password)
    db.create_user(api_key_hash=key_hash, abs_credentials_encrypted=encrypted)

    response = HTMLResponse(
        '<p>Registered! Ask me for ABS data. For example: '
        '"population by remoteness area from the 2021 census"</p>'
    )
    response.set_cookie("tb_api_key", api_key, httponly=True, max_age=86400 * 365)
    return response


@router.post("/web/chat", response_class=HTMLResponse)
async def web_chat(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(""),
):
    api_key = _get_api_key_from_cookie(request)
    if not api_key:
        return HTMLResponse("<p>Please register first.</p>", status_code=401)

    db = request.app.state.db
    resolver = request.app.state.chat_resolver
    key_hash = hash_api_key(api_key)
    user = db.get_user_by_api_key_hash(key_hash)
    if not user:
        return HTMLResponse("<p>Session expired. Please register again.</p>", status_code=401)

    # Get or create chat session
    history = []
    if session_id:
        session = db.get_chat_session(session_id)
        if session and session["user_id"] == user["id"]:
            history = json.loads(session["messages_json"])
    else:
        session_id = db.create_chat_session(user_id=user["id"], messages_json="[]")

    result = resolver.resolve(message, conversation_history=history)

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": json.dumps(result)})

    resolved_json = None
    if "dataset" in result and "rows" in result:
        resolved_json = json.dumps({
            "dataset": result["dataset"],
            "rows": result["rows"],
            "cols": result.get("cols", []),
            "wafers": result.get("wafers", []),
        })

    db.update_chat_session(session_id, json.dumps(history), resolved_json)

    # Build HTML response
    html = f'<div class="chat-message user"><div class="chat-bubble">{message}</div></div>'

    if "confirmation" in result:
        html += f"""<div class="chat-message assistant"><div class="chat-bubble">
            {result['confirmation']}
            <form hx-post="/web/confirm" hx-target="#chat-messages" hx-swap="beforeend">
                <input type="hidden" name="session_id" value="{session_id}">
                <button type="submit">Fetch this data</button>
            </form>
        </div></div>"""
    elif "clarification" in result:
        html += f'<div class="chat-message assistant"><div class="chat-bubble">{result["clarification"]}</div></div>'

    # Update the session_id hidden field
    html += f'<script>document.getElementById("session_id").value = "{session_id}";</script>'
    return HTMLResponse(html)


@router.post("/web/confirm", response_class=HTMLResponse)
async def web_confirm(request: Request, session_id: str = Form(...)):
    api_key = _get_api_key_from_cookie(request)
    if not api_key:
        return HTMLResponse("<p>Please register first.</p>", status_code=401)

    db = request.app.state.db
    key_hash = hash_api_key(api_key)
    user = db.get_user_by_api_key_hash(key_hash)
    if not user:
        return HTMLResponse("<p>Session expired.</p>", status_code=401)

    session = db.get_chat_session(session_id)
    if not session or not session["resolved_request_json"]:
        return HTMLResponse("<p>No request to confirm.</p>", status_code=400)

    job_id = db.create_job(
        user_id=user["id"],
        request_json=session["resolved_request_json"],
    )
    db.link_chat_to_job(session_id, job_id)

    return HTMLResponse(f"""<div class="chat-message assistant"><div class="chat-bubble">
        Job submitted! <a href="/jobs/{job_id}">Track progress</a>
        <div hx-get="/web/job-status/{job_id}" hx-trigger="every 10s" hx-swap="innerHTML">
            Status: queued
        </div>
    </div></div>""")


@router.get("/web/job-status/{job_id}", response_class=HTMLResponse)
async def web_job_status(job_id: str, request: Request):
    db = request.app.state.db
    job = db.get_job(job_id)
    if not job:
        return HTMLResponse("Job not found")

    status = job["status"]
    progress = job["progress"] or status
    if status == "completed":
        return HTMLResponse(
            f'<span class="status-completed">Completed!</span> '
            f'<a href="/api/jobs/{job_id}/download">Download CSV</a>'
        )
    elif status == "failed":
        return HTMLResponse(
            f'<span class="status-failed">Failed: {job["error_message"]}</span> '
            f'<a href="/jobs/{job_id}">View details</a>'
        )
    return HTMLResponse(f'<span class="status-{status}">{progress}</span>')


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    api_key = _get_api_key_from_cookie(request)
    jobs = []
    if api_key:
        db = request.app.state.db
        key_hash = hash_api_key(api_key)
        user = db.get_user_by_api_key_hash(key_hash)
        if user:
            raw_jobs = db.list_user_jobs(user["id"])
            for j in raw_jobs:
                req = json.loads(j.get("request_json", "{}"))
                j["dataset_name"] = req.get("dataset", "Unknown")
                j["duration"] = ""
                if j.get("started_at") and j.get("completed_at"):
                    # Simple duration display
                    j["duration"] = "completed"
                jobs = raw_jobs

    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "api_key": api_key,
        "jobs": jobs,
    })


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail_page(job_id: str, request: Request):
    api_key = _get_api_key_from_cookie(request)
    if not api_key:
        return templates.TemplateResponse("jobs.html", {
            "request": request, "api_key": None, "jobs": [],
        })

    db = request.app.state.db
    key_hash = hash_api_key(api_key)
    user = db.get_user_by_api_key_hash(key_hash)
    if not user:
        return HTMLResponse("Unauthorized", status_code=401)

    job = db.get_job(job_id)
    if not job or job["user_id"] != user["id"]:
        return HTMLResponse("Job not found", status_code=404)

    req = json.loads(job.get("request_json", "{}"))
    job["dataset_name"] = req.get("dataset", "Unknown")

    events = db.get_events(job_id)
    screenshots = [
        e["screenshot_path"].split("/")[-1]
        for e in events
        if e.get("screenshot_path")
    ]

    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "job": job,
        "events": events,
        "screenshots": screenshots,
    })


@router.get("/web/screenshot/{job_id}/{filename}")
async def serve_screenshot(job_id: str, filename: str, request: Request):
    results_dir = request.app.state.results_dir
    path = results_dir / job_id / "screenshots" / filename
    if not path.exists():
        return Response(status_code=404)
    return FileResponse(path, media_type="image/png")
```

- [ ] **Step 6: Register web routes in app.py**

Add to `create_app` in `app.py`, after the chat router registration:
```python
    from tablebuilder.service.routes_web import router as web_router
    app.include_router(web_router)
```

- [ ] **Step 7: Run all tests**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest --ignore=tests/test_integration.py -q`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add src/tablebuilder/service/routes_web.py src/tablebuilder/service/templates/ src/tablebuilder/service/app.py
git commit -m "feat: add web UI with chat page, jobs dashboard, and screenshot filmstrip"
```

---

### Task 11: MCP Tools

**Files:**
- Create: `src/tablebuilder/service/mcp_tools.py`

This is a thin wrapper that calls the REST API. Implementation depends on which MCP framework you use (fastmcp, mcp-server, etc.). Defer detailed implementation until the REST API is deployed and tested.

- [ ] **Step 1: Create MCP tools stub**

Create `src/tablebuilder/service/mcp_tools.py`:
```python
# ABOUTME: MCP tool definitions for TableBuilder service.
# ABOUTME: Wraps REST API endpoints for use from Claude Code / Claude Desktop.

# MCP tools call the same REST API as any other client.
# They use a configured API key from environment variables.
#
# Tools:
#   - search_dictionary(query) → search results
#   - submit_job(dataset, rows, cols, wafers) → job_id
#   - job_status(job_id) → status + progress
#   - download_result(job_id) → CSV content
#   - list_jobs() → user's recent jobs
#
# Implementation deferred until REST API is deployed and tested.
# See spec: docs/superpowers/specs/2026-03-18-tablebuilder-service-design.md
```

- [ ] **Step 2: Commit**

```bash
git add src/tablebuilder/service/mcp_tools.py
git commit -m "docs: add MCP tools stub (implementation deferred until API deployed)"
```

---

### Task 12: Deployment Files

**Files:**
- Create: `deploy/tablebuilder-service.service`
- Create: `deploy/deploy.sh`

- [ ] **Step 1: Create systemd unit file**

Create `deploy/tablebuilder-service.service`:
```ini
[Unit]
Description=TableBuilder API Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=dewoller
WorkingDirectory=/tank/services/active_services/tablebuilder-service

ExecStartPre=+/usr/local/bin/sops-decrypt.sh tablebuilder-service
EnvironmentFile=-/run/secrets/tablebuilder-service/.env
ExecStart=/tank/services/active_services/tablebuilder-service/.venv/bin/uvicorn tablebuilder.service.app:app --host 0.0.0.0 --port 8080
ExecStopPost=+/bin/rm -rf /run/secrets/tablebuilder-service

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create deploy script**

Create `deploy/deploy.sh`:
```bash
#!/usr/bin/env bash
# ABOUTME: Deploy tablebuilder-service to a target host.
# ABOUTME: Installs systemd unit and restarts the service.
set -euo pipefail

TARGET="${1:?Usage: $0 <host>}"
SVC="tablebuilder-service"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cat "${SCRIPT_DIR}/${SVC}.service" | /usr/bin/ssh "${TARGET}" \
  "sudo tee /etc/systemd/system/${SVC}.service > /dev/null"

/usr/bin/ssh "${TARGET}" \
  "sudo systemctl daemon-reload && sudo systemctl enable ${SVC} && sudo systemctl restart ${SVC}"

echo "Deployed ${SVC} to ${TARGET}"
```

- [ ] **Step 3: Make deploy script executable and commit**

```bash
chmod +x deploy/deploy.sh
git add deploy/
git commit -m "feat: add systemd unit and deploy script for tablebuilder-service"
```

---

### Task 13: End-to-End Integration Test

**Files:**
- Create: `tests/test_service_e2e.py`

- [ ] **Step 1: Write end-to-end test**

Create `tests/test_service_e2e.py`:
```python
# ABOUTME: End-to-end test for the full service lifecycle.
# ABOUTME: Tests register → submit job → poll → download with mocked Playwright.

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from tablebuilder.service.app import create_app
from tablebuilder.service.auth import generate_encryption_key


@pytest.fixture
def service(tmp_path):
    """Create a full service with worker running."""
    db_path = tmp_path / "e2e.db"
    results_dir = tmp_path / "results"
    encryption_key = generate_encryption_key()
    app = create_app(
        db_path=db_path,
        results_dir=results_dir,
        encryption_key=encryption_key,
        start_worker=False,  # We'll manually trigger processing
    )
    client = TestClient(app)
    return client, app, results_dir


class TestServiceE2E:
    @patch("tablebuilder.service.worker.TableBuilderSession")
    @patch("tablebuilder.service.worker.open_dataset")
    @patch("tablebuilder.service.worker.build_table")
    @patch("tablebuilder.service.worker.queue_and_download")
    def test_full_lifecycle(
        self, mock_download, mock_build, mock_open, mock_session, service
    ):
        """Register → submit → process → poll → download."""
        client, app, results_dir = service

        # Mock the Playwright pipeline
        mock_page = MagicMock()
        mock_sess = MagicMock()
        mock_sess.__enter__ = MagicMock(return_value=mock_page)
        mock_sess.__exit__ = MagicMock(return_value=False)
        mock_session.return_value = mock_sess

        def fake_download(page, output_path, timeout=600, knowledge=None):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text("col1,col2\n1,2\n")

        mock_download.side_effect = fake_download

        # 1. Register
        resp = client.post("/api/auth/register", json={
            "abs_user_id": "testuser",
            "abs_password": "testpass",
        })
        assert resp.status_code == 200
        api_key = resp.json()["api_key"]
        headers = {"Authorization": f"Bearer {api_key}"}

        # 2. Submit job
        resp = client.post("/api/jobs", json={
            "dataset": "Census 2021",
            "rows": ["SEXP Sex"],
        }, headers=headers)
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        # 3. Verify queued
        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.json()["status"] == "queued"

        # 4. Process the job via worker
        from tablebuilder.service.worker import Worker
        worker = Worker(
            db=app.state.db,
            results_dir=results_dir,
            encryption_key=app.state.encryption_key,
        )
        worker.process_one_job()

        # 5. Verify completed
        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.json()["status"] == "completed"
        assert "result_url" in resp.json()

        # 6. Download
        resp = client.get(f"/api/jobs/{job_id}/download", headers=headers)
        assert resp.status_code == 200
        assert "col1,col2" in resp.text

        # 7. Check events
        resp = client.get(f"/api/jobs/{job_id}/events", headers=headers)
        events = resp.json()
        assert len(events) > 0
        messages = [e["message"] for e in events]
        assert any("Logging in" in m for m in messages)
        assert any("Download complete" in m for m in messages)
```

- [ ] **Step 2: Run e2e test**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest tests/test_service_e2e.py -v`
Expected: All tests pass

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/dewoller/code/rmai/tablebuilder && uv run pytest --ignore=tests/test_integration.py -q`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_service_e2e.py
git commit -m "test: add end-to-end test for full service lifecycle"
```
