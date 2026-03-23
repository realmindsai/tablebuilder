# TableBuilder-as-a-Service Design

**Date:** 2026-03-18
**Status:** Approved
**Author:** Doctor Dee + Claude

## Overview

Wrap the existing TableBuilder CLI browser automation in a FastAPI service that provides:
1. An async REST API for submitting data fetch jobs and polling for results
2. A conversational web chat UI that resolves natural language queries into structured TableRequests using Claude API + the existing dictionary DB
3. MCP tools for direct use from Claude Code / Claude Desktop
4. Comprehensive production error capture with screenshot timelines for every job

## Target Users

**Primary:** Researchers and analysts who know roughly what ABS data they want but find TableBuilder painful to use (e.g., "I need population figures by remoteness area from the 2021 census").

**Secondary:** Developers who want programmatic API access to ABS TableBuilder data.

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Credential model | Bring-your-own ABS credentials | We're a better UI layer, not a data reseller |
| Async pattern | Polling-based (POST returns job_id, GET polls status) | Simplest, well-suited for 20-min fetch times |
| Job queue | SQLite table, single worker thread | Adequate for 5-10 users, a few requests/day |
| Web framework | FastAPI + Jinja2 + HTMX | No JS build step, server-rendered, easy to maintain |
| Credential storage | Envelope encryption (DB key protected by sops + age) | Fits existing RMAI infrastructure |
| Conversational layer | Claude API with tool-use against dictionary DB | Dictionary DB already has 96 datasets, 28k+ variables |
| Deployment | Systemd service on totoro, standard sops + age pattern | Consistent with all other RMAI services |

## API Design

### Dictionary / Discovery

```
GET  /api/datasets                        → list all 96 datasets
GET  /api/datasets/{name}/variables       → variable tree for a dataset ({name} is URL-encoded dataset name)
GET  /api/search?q=population+remoteness  → FTS5 search
```

### Job Management (Async Pattern)

```
POST /api/jobs                → submit fetch request, returns job_id
GET  /api/jobs/{job_id}       → poll status + result link when done
GET  /api/jobs                → list user's jobs (with status filters)
GET  /api/jobs/{job_id}/download  → download result CSV
GET  /api/jobs/{job_id}/events    → full event timeline with screenshot URLs
GET  /api/jobs/{job_id}/debug     → error detail, traceback, page HTML, console log
```

### Conversational

```
POST /api/chat           → natural language query, returns {session_id, interpretation, confirmation_prompt}
POST /api/chat/confirm   → {session_id} confirms the resolved request, creates the job
```

Both endpoints require `session_id` (UUID). First `POST /api/chat` without a `session_id` creates a new session; subsequent messages include the returned `session_id` for multi-turn conversation.

### Auth

```
POST   /api/auth/register  → store encrypted ABS credentials, returns API key
POST   /api/auth/verify    → test credentials by attempting login
DELETE /api/auth/credentials → remove stored credentials
```

### Async Job Lifecycle

```
POST /api/jobs
  Request body:
  {
    "dataset": "Census 2021 - Counting Persons, Place of Usual Residence",
    "rows": ["SEXP Sex"],           // required, non-empty list of variable labels
    "cols": ["AGEP Age"],           // optional, default []
    "wafers": ["STATE State"],      // optional, default []
    "timeout_seconds": 600          // optional, default 600
  }
  Variables are specified as label strings (e.g., "SEXP Sex") matching the dictionary DB.

  → 202 Accepted {job_id, status: "queued", poll_url: "/api/jobs/abc123"}

GET /api/jobs/abc123
  → {status: "queued", progress: null}

GET /api/jobs/abc123  (later)
  → {status: "running", progress: "Building table..."}

GET /api/jobs/abc123  (later)
  → {status: "completed", result_url: "/api/jobs/abc123/download"}

GET /api/jobs/abc123/download  (before completion)
  → 409 Conflict {error: "Job not yet completed", status: "running"}
```

Status transitions: `queued → running → completed` or `queued → running → failed`.

Authentication: API key per user, passed as `Authorization: Bearer <key>` header.

## Data Model

All service data in a single SQLite database (`~/.tablebuilder/service.db`), separate from the existing dictionary DB.

### users

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    api_key_hash TEXT UNIQUE NOT NULL,  -- SHA-256 hash of the API key (plaintext never stored)
    abs_credentials_encrypted TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
```

API keys are hashed (SHA-256) before storage. The plaintext key is returned once at registration and never stored. Authentication compares `SHA-256(bearer_token)` against `api_key_hash`.

Credentials encrypted using a key from the service's `.env.sops` (envelope encryption — DB key protected by sops + age).

### jobs

```sql
CREATE TABLE jobs (
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
```

### job_events

Full audit trail for every job — always on, production and test.

```sql
CREATE TABLE job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    detail TEXT,
    screenshot_path TEXT
);
```

Event types: `progress`, `warning`, `error`, `screenshot`, `retry`.

### chat_sessions

```sql
CREATE TABLE chat_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    messages_json TEXT NOT NULL,
    resolved_request_json TEXT,
    job_id TEXT REFERENCES jobs(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

## Worker Architecture

Background thread in the same FastAPI process. Runs the existing pipeline code unchanged.

```
FastAPI process
├── API endpoints (async, handles HTTP)
├── Worker thread (picks up jobs, runs Playwright)
│   └── Uses existing: TableBuilderSession → Navigator → TableBuilder → Downloader
└── Job event logger (writes to job_events table)
```

### Worker Loop

A single `KnowledgeBase` instance is shared across the worker's lifetime (matching the CLI pattern). This keeps the self-healing selector system and timing recording active for all service jobs.

Key imports: `TableRequest` from `tablebuilder.models`, `SessionExpiredError` from `tablebuilder.navigator` (that's where it lives — not in `browser`), `KnowledgeBase` from `tablebuilder.knowledge`.

```python
knowledge = KnowledgeBase()  # shared across all jobs

while True:
    job = db.fetch_next_queued_job()
    if not job:
        sleep(5)
        continue

    credentials = decrypt(job.user.abs_credentials_encrypted)
    config = Config(user_id=credentials.user, password=credentials.password)
    request = TableRequest(**json.loads(job.request_json))
    result_path = Path(f"~/.tablebuilder/results/{job.id}/output.csv").expanduser()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    job_timeout = job.timeout_seconds or 600

    page = None
    session = None
    try:
        log_event(job, "progress", "Logging in...")
        session = TableBuilderSession(config, headless=True, knowledge=knowledge)
        page = session.__enter__()

        log_event(job, "progress", "Opening dataset...")
        screenshot(job, page, "after_login")

        open_dataset(page, request.dataset, knowledge=knowledge)
        log_event(job, "progress", "Building table...")
        screenshot(job, page, "dataset_opened")

        build_table(page, request, knowledge=knowledge)
        log_event(job, "progress", "Queuing download...")
        screenshot(job, page, "table_built")

        queue_and_download(page, str(result_path), job_timeout, knowledge=knowledge)
        log_event(job, "progress", "Download complete")

        session.__exit__(None, None, None)
        mark_completed(job, result_path)
    except SessionExpiredError:
        log_event(job, "warning", "Session expired, attempting relogin...")
        if session:
            session.relogin()  # accessible because we hold the session reference
            # retry logic here
    except Exception as e:
        if page:
            screenshot(job, page, "failure")
            save_page_html(job, page)
        if session:
            session.__exit__(*sys.exc_info())
        mark_failed(job, error=str(e), traceback=full_traceback())
```

### Key Constraints

- **Single worker thread** — one Chromium instance at a time, avoids RAM pressure on totoro
- **No changes to existing pipeline code** — worker calls `open_dataset`, `build_table`, `queue_and_download` exactly as the CLI does
- **Job timeout** — 30 min max wall-clock per job (configurable)
- **Graceful shutdown** — SIGTERM lets current job finish or marks it failed

## Conversational Layer

### Resolution Flow

1. `/api/chat` receives natural language message
2. Backend runs FTS5 search against dictionary DB for candidates
3. Search results + user message sent to Claude API with tool-use
4. Claude resolves intent into a structured `TableRequest`
5. Response returned as confirmation prompt with dataset/variable details
6. User confirms → `/api/chat/confirm` → creates the job

### Claude API Tool Definitions

```
- search_dictionary(query) → matching datasets/variables/categories
- get_dataset_variables(dataset_id) → full variable tree
```

Multi-turn conversation handles disambiguation ("Did you mean the 2016 or 2021 census?", "All remoteness categories or just Remote + Very Remote?").

### MCP Tools

For direct use from Claude Code / Claude Desktop — no resolution layer needed, Claude IS the conversational interface:

```
- search_dictionary(query) → search results
- submit_job(dataset, rows, cols, wafers) → job_id
- job_status(job_id) → status + progress
- download_result(job_id) → CSV content or path
- list_jobs() → user's recent jobs
```

MCP authentication: The MCP server config (in Claude Desktop `claude_desktop_config.json` or Claude Code settings) includes the user's API key as an environment variable. The MCP tools pass this key as the Bearer token when calling the REST API — same auth path as any other client.

## Production Error Capture

Always on — same code path for tests and production.

### Every Job Gets

- **Screenshot timeline** — at each state transition (login, dataset opened, table built, queued, downloaded). Stored in `~/.tablebuilder/results/{job_id}/screenshots/` with timestamps (`001_login_complete.png`, `002_dataset_opened.png`, etc.)
- **Full event log** in `job_events` — every state transition, selector tried, retry, knowledge base warning

### On Failure, Additionally

- Page HTML snapshot (full DOM at moment of failure)
- Current URL
- Full Python traceback
- Browser console log

### Browseable via Web UI

- Failed job page shows screenshot timeline as a filmstrip
- Completed job screenshots kept for 7 days (verify CSV correctness)
- Debug endpoint (`/api/jobs/{job_id}/debug`) for programmatic access

## Web UI

Two pages, server-rendered with HTMX.

### Chat Page (`/`)

- Standard chat layout: text input at bottom, messages above
- Confirmation cards with dataset/variable details and "Fetch this" button
- Job status card that polls via HTMX (`hx-get` every 10s)
- First visit: credential entry form

### Jobs Page (`/jobs`)

- Table of past jobs: name, status, submitted time, duration
- Click completed → download CSV
- Click failed → error message + screenshot filmstrip timeline
- Status badges: queued (grey), running (blue), completed (green), failed (red)

### Tech Stack

- FastAPI + Jinja2 templates (no separate frontend build)
- HTMX for polling and dynamic updates
- Pico CSS for clean defaults
- No React, no npm, no JS build step

## Project Structure

```
src/tablebuilder/
├── cli.py                  # existing (unchanged, gains `serve` command)
├── browser.py              # existing (unchanged)
├── navigator.py            # existing (unchanged)
├── table_builder.py        # existing (unchanged)
├── downloader.py           # existing (unchanged)
├── ... other existing modules ...
│
├── service/
│   ├── __init__.py
│   ├── app.py              # FastAPI app, route registration, lifespan (worker start/stop)
│   ├── routes_api.py       # /api/jobs, /api/search, /api/auth endpoints
│   ├── routes_chat.py      # /api/chat, /api/chat/confirm
│   ├── routes_web.py       # HTML pages (/, /jobs)
│   ├── worker.py           # background job worker thread
│   ├── job_logger.py       # job_events logging + screenshot capture
│   ├── db.py               # SQLite connection, migrations, queries
│   ├── auth.py             # credential encryption, API key management
│   ├── chat_resolver.py    # Claude API + dictionary DB → TableRequest
│   ├── mcp_tools.py        # MCP tool definitions
│   └── templates/
│       ├── base.html
│       ├── chat.html
│       └── jobs.html
```

### New Dependencies

- `fastapi` + `uvicorn`
- `jinja2`
- `anthropic` (Claude API for chat resolver)
- `cryptography` (Fernet for credential envelope encryption)

### New CLI Command

```bash
uv run tablebuilder serve --port 8080 --host 0.0.0.0
```

### Configuration

Service-specific config in `.env.sops`:

```
ANTHROPIC_API_KEY=sk-ant-...
DB_ENCRYPTION_KEY=<generated Fernet key>
TABLEBUILDER_SERVICE_PORT=8080
```

## Credential Security

### Two-Layer Model

1. **Service secrets** (Anthropic API key, DB encryption key) → `.env.sops`, decrypted at startup via `sops-decrypt.sh` into `/run/secrets/tablebuilder-service/.env` (tmpfs). Standard RMAI pattern.
2. **User ABS credentials** → encrypted in SQLite `users` table using `DB_ENCRYPTION_KEY` from layer 1. Envelope encryption: DB key protected by age, user credentials protected by DB key.

### Key Rotation

Offline migration (service stopped):
1. Stop the service (`systemctl stop tablebuilder-service`)
2. Rotate `DB_ENCRYPTION_KEY` in `.env.sops`
3. Run migration script to re-encrypt all rows in `users` table (reads old key, writes new key)
4. Restart service (`systemctl start tablebuilder-service`)

## Deployment

### Totoro Setup

```
/tank/services/active_services/tablebuilder-service/
├── .env.sops
├── deploy/
│   ├── tablebuilder-service.service
│   └── deploy.sh
```

### Systemd Unit

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

### Playwright Prerequisites

```bash
uv sync
uv run playwright install chromium
uv run playwright install-deps
```

### Data Directories

```
~/.tablebuilder/
├── service.db              # users, jobs, job_events, chat_sessions
├── dictionary.db           # existing FTS5 search (read-only)
├── knowledge.json          # existing self-healing knowledge base
├── results/{job_id}/       # job outputs
│   ├── output.csv
│   └── screenshots/
└── logs/                   # existing log files
```

### Network Access

Initial: `totoro:8080` on Tailscale. Later: reverse proxy with Caddy/nginx for `tablebuilder.realmindsai.com.au` with TLS.

## Testing Strategy

### Unit Tests

- `test_routes_api.py` — job submission validation, status responses, auth checks
- `test_routes_chat.py` — chat message handling, confirmation flow (mocked Claude API)
- `test_db.py` — job CRUD, user CRUD, event logging, migrations
- `test_auth.py` — credential encryption/decryption roundtrip, API key generation
- `test_chat_resolver.py` — dictionary search → TableRequest resolution (mocked Claude API, real dictionary DB)
- `test_worker.py` — job state transitions, error capture, screenshot logging (mocked Playwright)
- `test_job_logger.py` — event logging, screenshot paths, timeline reconstruction

### Integration Tests

- `test_worker_integration.py` — real job against ABS with real credentials
- `test_chat_integration.py` — real Claude API call with real dictionary DB
- `test_api_flow.py` — register → submit → poll → download (TestClient, mocked Playwright)

### End-to-End Tests

- `test_e2e.py` — full HTTP lifecycle against running FastAPI server with real ABS browser automation

### Error Scenario Tests

- Job fails mid-run → screenshot captured, traceback stored, events complete
- ABS login fails → clear error, credentials flagged
- Session expires mid-job → retry via `relogin()`, events logged
- Browser crashes → job marked failed, Chromium cleaned up
- Concurrent job while one running → queues properly
