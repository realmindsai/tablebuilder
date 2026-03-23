# TableBuilder Research Assistant — Code Walkthrough

*2026-03-22T17:36:55Z by Showboat 0.6.1*
<!-- showboat-id: 9ee2bffe-4cae-4346-b320-7c675aa8a933 -->

This walkthrough traces a single user request through every layer of the TableBuilder Research Assistant — from the browser to Claude to the database and back. Each code snippet is extracted live from the repository.

## 1. The App Boots

Everything starts in `app.py`. The factory function wires up the database, encryption, Claude resolver, and background worker — then registers three routers for the API, chat, and web UI.

```bash
sed -n '29,76p' src/tablebuilder/service/app.py
```

```output
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

    from tablebuilder.service.routes_chat import router as chat_router
    app.include_router(chat_router)

    from tablebuilder.service.routes_web import router as web_router
    app.include_router(web_router)

    return app
```

Key things: `ServiceDB` is the SQLite layer, `ChatResolver` wraps the Claude API, and the `Worker` is a daemon thread that processes fetch jobs in the background. All three are attached to `app.state` so every route handler can access them.

## 2. The Database Schema

Five tables hold all persistent state. The schema is created on first boot and migrated forward for existing databases.

```bash
sed -n '10,67p' src/tablebuilder/service/db.py
```

```output
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
```

The relationship: `users` own `chat_sessions`, which accumulate `proposals_json` (shopping cart items) and link to `jobs` when proposals are confirmed. `session_events` logs every interaction for audit. `job_events` tracks the worker's progress through each fetch.

## 3. User Arrives — The Chat Page

When a user hits `/`, the web router checks for an API key cookie. No cookie? Show the registration form. Got one? Show the two-panel chat UI.

```bash
cat src/tablebuilder/service/templates/chat.html
```

```output
{% extends "base.html" %}
{% block title %}Chat - TableBuilder Service{% endblock %}
{% block content %}
{% if not api_key %}
<div class="chat-container">
    <article>
        <h3>Enter your ABS credentials</h3>
        <form method="post" action="/web/register">
            <label for="abs_user_id">ABS User ID</label>
            <input type="text" name="abs_user_id" id="abs_user_id" required>
            <label for="abs_password">ABS Password</label>
            <input type="password" name="abs_password" id="abs_password" required>
            <button type="submit">Register</button>
        </form>
    </article>
</div>
{% else %}
<div class="two-panel">
    <div class="chat-container">
        <div id="chat-messages" class="chat-messages">
            <p>I'm your ABS data research assistant. Tell me about your research question and I'll help you find the right datasets and variables.</p>
        </div>
        <form id="chat-form" hx-post="/web/chat" hx-target="#chat-messages" hx-swap="beforeend"
              hx-on::before-request="document.getElementById('send-btn').setAttribute('aria-busy','true')"
              hx-on::after-request="this.reset(); document.getElementById('send-btn').removeAttribute('aria-busy'); document.getElementById('chat-messages').scrollTop = document.getElementById('chat-messages').scrollHeight">
            <input type="hidden" name="session_id" id="session_id" value="">
            <div role="group">
                <input type="text" name="message" placeholder="What data are you looking for?" required autofocus>
                <button type="submit" id="send-btn">Send</button>
            </div>
        </form>
    </div>
    <div class="cart-panel">
        <h3>Data Cart</h3>
        <div id="cart-items">
            <p style="color: var(--pico-muted-color);">No proposals yet. Start chatting to discover datasets.</p>
        </div>
    </div>
</div>
<script>
document.body.addEventListener('htmx:afterSwap', function() {
    var el = document.getElementById('chat-messages');
    if (el) el.scrollTop = el.scrollHeight;
});
</script>
{% endif %}
{% endblock %}
```

Two-panel grid: chat on the left (`#chat-messages`), shopping cart on the right (`#cart-items`). HTMX handles all interactivity — the form POSTs to `/web/chat`, appends the response HTML, and auto-scrolls. The hidden `session_id` field maintains conversation state across messages.

## 4. Registration — Encrypting Credentials

When the user registers, their ABS credentials are encrypted with Fernet and stored alongside a hashed API key.

```bash
sed -n '49,65p' src/tablebuilder/service/routes_web.py
```

```output
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

    from fastapi.responses import RedirectResponse
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("tb_api_key", api_key, httponly=True, max_age=86400 * 365)
    return response
```

The API key is set as an httponly cookie (invisible to JavaScript) and the credentials are Fernet-encrypted in the database. Only the background worker ever decrypts them — and only to log into ABS.

## 5. Sending a Message — The Core Loop

When the user types a research question, `web_chat` creates a session, builds cart context, calls the resolver, persists proposals, and returns HTML with an OOB swap to update the cart.

```bash
sed -n '68,136p' src/tablebuilder/service/routes_web.py
```

```output
@router.post("/web/chat", response_class=HTMLResponse)
async def web_chat(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(""),
):
    api_key = _get_valid_api_key(request)
    if not api_key:
        return HTMLResponse("<p>Please register first.</p>", status_code=401)

    db = request.app.state.db
    resolver = request.app.state.chat_resolver
    key_hash = hash_api_key(api_key)
    user = db.get_user_by_api_key_hash(key_hash)
    if not user:
        return HTMLResponse("<p>Session expired. Please register again.</p>", status_code=401)

    history = []
    if session_id:
        session = db.get_chat_session(session_id)
        if session and session["user_id"] == user["id"]:
            history = json.loads(session["messages_json"])
    else:
        session_id = db.create_chat_session(user_id=user["id"], messages_json="[]")

    # Build cart context
    proposals = db.get_proposals(session_id)
    cart_context = ""
    if proposals:
        lines = []
        for p in proposals:
            status = "CHECKED" if p["status"] == "checked" else "unchecked"
            lines.append(f"- [{status}] {p['dataset']}: rows={p.get('rows', [])}")
        cart_context = "\n".join(lines)

    db.add_session_event(session_id, "user_message", message)

    result = resolver.resolve(
        message,
        conversation_history=history,
        session_id=session_id,
        db=db,
        cart_context=cart_context,
    )

    # Persist proposals
    for payload in result.get("display_payloads", []):
        if payload["type"] == "proposal":
            db.add_proposal(session_id, payload["data"])
            db.add_session_event(
                session_id, "proposal_created",
                f"Proposed: {payload['data']['dataset']}",
                metadata_json=json.dumps(payload["data"]),
            )

    text = result.get("text", "")
    db.add_session_event(session_id, "assistant_message", text)
    db.update_chat_session(session_id, json.dumps(result.get("messages", [])))

    # Build response HTML
    html = f'<div class="chat-message user"><div class="chat-bubble">{message}</div></div>'

    # Render choice buttons inline if present
    for payload in result.get("display_payloads", []):
        if payload["type"] == "choices":
            choices_html = _render_choices(payload["data"], session_id)
            text += choices_html

    html += f'<div class="chat-message assistant"><div class="chat-bubble">{text}</div></div>'
```

Notice how cart context is injected: existing proposals are formatted as text and passed to the resolver so Claude knows what's already in the cart. The result comes back with `text` (Claude's response) and `display_payloads` (proposals, choices). Proposals are persisted to the DB and rendered as an OOB swap into `#cart-items`.

## 6. The Resolver — Claude as Data Scientist

This is the brain. The system prompt establishes a persona, not a workflow. Claude gets 6 tools and decides how to use them.

```bash
sed -n '13,28p' src/tablebuilder/service/chat_resolver.py
```

```output
SYSTEM_PROMPT = """You are a senior research data scientist with deep expertise in Australian Bureau of Statistics census and survey data. You've spent years working with the 96 datasets in ABS TableBuilder — you know the variables, the quirks, the gaps.

A researcher has come to you for help. Your job is to understand their research question and help them get the exact data they need. You're collegial, curious, and opinionated when it matters. You get excited when you spot a connection the researcher hasn't seen. You know when to suggest a better variable and when to just give them what they asked for.

You understand research methodology — you can advise on denominators, confounders, and geographic levels. You know that cross-tabulation needs compatible datasets and that geographic hierarchies matter.

You have tools to search and explore the ABS data dictionary. Use them proactively — when a researcher mentions a topic, search for it immediately. Show them what's available. Suggest combinations they might not have considered.

When you find relevant data, use the propose_table_request tool to add it to the researcher's data cart. Include your confidence assessment:
- match_confidence (0-100): how well the dataset's variables cover what the researcher is asking about
- clarity_confidence (0-100): has the researcher been specific enough that you're confident this data will answer their question?

If clarity_confidence would be below 70, ask a follow-up question before proposing. Use present_choices when a structured selection would be clearer than an open question (e.g., geographic levels, variable options).

When the researcher asks for a summary of the session, use show_session_summary.

```

No JSON output constraints. No rigid workflow. Claude talks naturally and uses tools when it makes sense. The 6 tools split into two categories — let's see them:

```bash
grep -n '"name":' src/tablebuilder/service/chat_resolver.py | head -6
```

```output
36:        "name": "search_dictionary",
48:        "name": "get_dataset_variables",
59:        "name": "compare_datasets",
70:        "name": "propose_table_request",
87:        "name": "present_choices",
100:        "name": "show_session_summary",
```

**Research tools** (`search_dictionary`, `get_dataset_variables`, `compare_datasets`) query the FTS5 dictionary database. **Display tools** (`propose_table_request`, `present_choices`, `show_session_summary`) produce structured payloads that the UI renders — Claude gets a text confirmation back, the researcher sees a rich UI element.

## 7. The Resolve Loop — Up to 10 Agentic Rounds

The resolver runs Claude in a loop. Each round, Claude can call tools or produce text. Display tools collect payloads in `_display_payloads` for the UI.

```bash
sed -n '112,174p' src/tablebuilder/service/chat_resolver.py
```

```output
        self._client = None
        self._display_payloads: list = []
        self._session_id: str | None = None
        self._db = None

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
            results = search(DEFAULT_DB_PATH, tool_input["query"], limit=tool_input.get("limit", 10))
            return json.dumps(results)

        elif tool_name == "get_dataset_variables":
            if not DEFAULT_DB_PATH.exists():
                return json.dumps(None)
            result = get_dataset(DEFAULT_DB_PATH, tool_input["dataset_name"])
            if result is None:
                return json.dumps(None)
            summary = {"name": result["name"], "geographies": result.get("geographies", []), "groups": []}
            for group in result.get("groups", []):
                g = {"path": group["path"], "variables": []}
                for var in group.get("variables", []):
                    cats = var.get("categories", [])
                    g["variables"].append({"code": var.get("code", ""), "label": var["label"], "category_count": len(cats), "sample_categories": cats[:5]})
                summary["groups"].append(g)
            return json.dumps(summary)

        elif tool_name == "compare_datasets":
            if not DEFAULT_DB_PATH.exists():
                return json.dumps([])
            result = compare_datasets(DEFAULT_DB_PATH, tool_input["dataset_names"])
            return json.dumps(result)

        elif tool_name == "propose_table_request":
            proposal_id = f"p{len(self._display_payloads) + 1}"
            proposal = {
                "id": proposal_id,
                "dataset": tool_input["dataset"],
                "rows": tool_input.get("rows", []),
                "cols": tool_input.get("cols", []),
                "wafers": tool_input.get("wafers", []),
                "match_confidence": tool_input["match_confidence"],
                "clarity_confidence": tool_input["clarity_confidence"],
                "rationale": tool_input["rationale"],
                "status": "checked",
                "job_id": None,
            }
            self._display_payloads.append({"type": "proposal", "data": proposal})
            return f"Proposal #{proposal_id} stored and shown to researcher."

        elif tool_name == "present_choices":
            choices = {
                "question": tool_input["question"],
```

When Claude calls `propose_table_request`, the handler builds a proposal dict with confidence scores and appends it to `_display_payloads`. Claude sees "Proposal #p1 stored and shown to researcher." — the UI gets the structured data for rendering a cart card.

## 8. The Dictionary Database — 96 Datasets, 28K Variables

Claude's knowledge comes from a SQLite FTS5 database built from cached JSON extracts of every ABS TableBuilder dataset.

```bash
sqlite3 data/dictionary.db "SELECT COUNT(*) as datasets FROM datasets; SELECT COUNT(*) as variables FROM variables; SELECT COUNT(*) as categories FROM categories;" 2>/dev/null || sqlite3 ~/.tablebuilder/dictionary.db "SELECT COUNT(*) as datasets FROM datasets; SELECT COUNT(*) as variables FROM variables; SELECT COUNT(*) as categories FROM categories;"
```

```output
131
36923
457681
```

That's 131 datasets, 36,923 variables, and 457,681 categories — all full-text searchable. Here's what a search looks like under the hood:

```bash
uv run python3 << 'PYEOF'
from tablebuilder.dictionary_db import search, _resolve_data_path
db = _resolve_data_path('dictionary.db')
results = search(db, 'income housing', limit=5)
for r in results:
    ds = r['dataset_name']
    code = r['code']
    label = r['label']
    print(f'{ds:45s} {code:8s} {label}')
PYEOF
```

```output
Disability, Ageing and Carers, 2022                    Main source of household income
Income and Housing, 2015-16                            Superannuation account paying regular income
Income and Housing, 2017-18                            Superannuation account paying regular income
Income and Housing, 2017-18                            Weekly housing costs as a percentage of gross income ranges
Income and Housing, 2017-18                            Weekly housing costs as a percentage of income ranges - alternative version
```

This is what Claude sees when it calls `search_dictionary({query: "income housing"})` — ranked FTS5 results across all datasets. It finds "Income and Housing" datasets immediately.

## 9. The Shopping Cart — Toggle and Fetch

When Claude proposes a table, the web route persists it and sends an OOB swap to update the cart panel. Each card is a self-contained HTMX component:

```bash
grep -A 25 'def _render_cart_card' src/tablebuilder/service/routes_web.py | head -30
```

```output
def _render_cart_card(proposal: dict, session_id: str) -> str:
    """Render a single proposal card HTML."""
    p = proposal
    checked = p["status"] == "checked"
    confirmed = p["status"] == "confirmed"
    opacity = "1" if checked or confirmed else "0.5"
    check_mark = "checked" if checked else ""
    disabled = "disabled" if confirmed else ""
    status_label = ""
    if confirmed:
        job_id = p.get("job_id", "")
        status_label = f' <a href="/jobs/{job_id}">Queued</a>'

    rows = ", ".join(p.get("rows", []))
    cols = ", ".join(p.get("cols", []))
    wafers = ", ".join(p.get("wafers", []))
    axes = f"Rows: {rows}" if rows else ""
    if cols:
        axes += f" | Cols: {cols}"
    if wafers:
        axes += f" | Wafers: {wafers}"

    return f"""<div id="cart-card-{p['id']}" style="opacity: {opacity}; padding: 0.5rem; border: 1px solid var(--pico-muted-border-color); border-radius: 0.5rem; margin-bottom: 0.5rem;">
        <label style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;">
            <input type="checkbox" {check_mark} {disabled}
                hx-post="/web/cart/toggle/{p['id']}"
```

Each checkbox POSTs to `/web/cart/toggle/{proposal_id}` with `hx-swap="outerHTML"` — the server toggles the status and returns just the updated card HTML. No page reload, no full cart re-render.

The **Fetch Selected** button queues a job for each checked proposal:

```bash
grep -A 35 'async def web_cart_fetch' src/tablebuilder/service/routes_web.py
```

```output
async def web_cart_fetch(
    request: Request,
    session_id: str = Form(...),
):
    api_key = _get_valid_api_key(request)
    if not api_key:
        return HTMLResponse("<p>Please register first.</p>", status_code=401)

    db = request.app.state.db
    key_hash = hash_api_key(api_key)
    user = db.get_user_by_api_key_hash(key_hash)
    if not user:
        return HTMLResponse("<p>Session expired.</p>", status_code=401)

    session = db.get_chat_session(session_id)
    if not session or session["user_id"] != user["id"]:
        return HTMLResponse("<p>Session not found.</p>", status_code=404)

    proposals = db.get_proposals(session_id)
    checked = [p for p in proposals if p.get("status") == "checked"]
    if not checked:
        return HTMLResponse("<p>No proposals selected.</p>", status_code=400)

    job_ids = []
    for proposal in checked:
        request_json = json.dumps({
            "dataset": proposal["dataset"],
            "rows": proposal.get("rows", []),
            "cols": proposal.get("cols", []),
            "wafers": proposal.get("wafers", []),
        })
        job_id = db.create_job(user_id=user["id"], request_json=request_json)
        db.update_proposal_status(session_id, proposal["id"], "confirmed")
        job_ids.append(job_id)

    db.add_session_event(
```

For each checked proposal: build a `request_json`, create a job (status=`queued`), mark the proposal as `confirmed`. The cart re-renders with checkboxes disabled and "Queued" links.

## 10. The Background Worker — Fetching Real Data

The worker thread polls every 5 seconds for queued jobs. When it finds one, it atomically claims it and runs the full ABS pipeline:

```bash
grep -A 5 'def fetch_next_queued_job' src/tablebuilder/service/db.py
```

```output
    def fetch_next_queued_job(self) -> dict | None:
        """Atomically claim the oldest queued job. Returns job + user credentials."""
        conn = self._connect()
        row = conn.execute(
            "SELECT j.*, u.abs_credentials_encrypted "
            "FROM jobs j JOIN users u ON j.user_id = u.id "
```

The SELECT + UPDATE runs in a single connection — no other worker can claim the same job. The worker then decrypts the ABS credentials, logs in via HTTP (no browser), navigates the dataset tree, selects variable categories, retrieves data, and downloads the CSV.

## 11. The Audit Trail — Every Event Logged

Every interaction is captured in `session_events`. Let's verify with a live test:

```bash
uv run python3 << 'PYEOF'
from tablebuilder.service.db import ServiceDB
from pathlib import Path
import tempfile, json

db = ServiceDB(Path(tempfile.mktemp(suffix='.db')))
uid = db.create_user(api_key_hash='test', abs_credentials_encrypted='enc')
sid = db.create_chat_session(user_id=uid, messages_json='[]')

# Simulate a conversation
db.add_session_event(sid, 'user_message', 'I want income data by region')
db.add_session_event(sid, 'tool_call', 'search_dictionary', metadata_json=json.dumps({'query': 'income region'}))
db.add_session_event(sid, 'tool_result', '5 results found')
db.add_session_event(sid, 'proposal_created', 'Census 2021 income by SA2')
db.add_session_event(sid, 'assistant_message', 'I found income data for you.')
db.add_session_event(sid, 'proposal_toggled', 'p1 -> unchecked')
db.add_session_event(sid, 'proposal_toggled', 'p1 -> checked')
db.add_session_event(sid, 'jobs_queued', 'Queued 1 job(s)')

events = db.get_session_events(sid)
for e in events:
    print(f"  {e['event_type']:20s} {e['message']}")
print(f'\nTotal events: {len(events)}')
PYEOF
```

```output
  user_message         I want income data by region
  tool_call            search_dictionary
  tool_result          5 results found
  proposal_created     Census 2021 income by SA2
  assistant_message    I found income data for you.
  proposal_toggled     p1 -> unchecked
  proposal_toggled     p1 -> checked
  jobs_queued          Queued 1 job(s)

Total events: 8
```

Every step of the conversation is replayable from the event log — useful for demos, debugging, and analytics.

## 12. Putting It All Together — The Test Suite

Finally, let's verify the whole system works by running all the tests we wrote:

```bash
uv run pytest tests/test_service_db.py tests/test_dictionary_db.py tests/test_service_chat_resolver.py tests/test_service_routes_chat.py tests/test_service_routes_web.py tests/test_research_assistant_integration.py -v --tb=no 2>&1 | tail -40
```

```output
tests/test_dictionary_db.py::TestGetDataset::test_get_existing_dataset PASSED [ 57%]
tests/test_dictionary_db.py::TestGetDataset::test_get_missing_dataset PASSED [ 59%]
tests/test_dictionary_db.py::TestGetVariablesByCode::test_find_by_code PASSED [ 60%]
tests/test_dictionary_db.py::TestGetVariablesByCode::test_find_missing_code PASSED [ 61%]
tests/test_dictionary_db.py::TestCompareDatasets::test_compare_two_datasets PASSED [ 62%]
tests/test_dictionary_db.py::TestCompareDatasets::test_compare_nonexistent_dataset PASSED [ 63%]
tests/test_dictionary_db.py::TestCompareDatasets::test_compare_single_dataset PASSED [ 64%]
tests/test_service_chat_resolver.py::TestChatResolver::test_resolve_returns_interpretation PASSED [ 65%]
tests/test_service_chat_resolver.py::TestChatResolver::test_resolve_returns_text_and_payloads PASSED [ 67%]
tests/test_service_chat_resolver.py::TestChatResolver::test_build_system_prompt_has_persona PASSED [ 68%]
tests/test_service_chat_resolver.py::TestChatResolverTools::test_tools_include_all_six PASSED [ 69%]
tests/test_service_chat_resolver.py::TestChatResolverTools::test_handle_propose_table_request PASSED [ 70%]
tests/test_service_chat_resolver.py::TestChatResolverTools::test_handle_present_choices PASSED [ 71%]
tests/test_service_routes_chat.py::TestChatRoutes::test_chat_creates_session PASSED [ 72%]
tests/test_service_routes_chat.py::TestChatRoutes::test_chat_returns_text_and_payloads PASSED [ 73%]
tests/test_service_routes_chat.py::TestChatRoutes::test_chat_confirm_creates_job PASSED [ 75%]
tests/test_service_routes_chat.py::TestChatRoutes::test_confirm_queues_checked_proposals PASSED [ 76%]
tests/test_service_routes_chat.py::TestChatRoutes::test_chat_without_auth PASSED [ 77%]
tests/test_service_routes_web.py::TestCartToggle::test_toggle_unchecks_proposal PASSED [ 78%]
tests/test_service_routes_web.py::TestCartToggle::test_toggle_checks_unchecked_proposal PASSED [ 79%]
tests/test_service_routes_web.py::TestCartFetch::test_fetch_creates_jobs_for_checked PASSED [ 80%]
tests/test_service_routes_web.py::TestWebChat::test_web_chat_returns_oob_cart_update PASSED [ 81%]
tests/test_research_assistant_integration.py::TestFullConversationFlow::test_chat_to_proposal_to_cart_to_fetch PASSED [ 82%]
tests/test_research_assistant_integration.py::TestMultiProposalSession::test_two_proposals_uncheck_one_fetch PASSED [ 84%]
tests/test_research_assistant_integration.py::TestMultiProposalSession::test_confirm_with_all_unchecked_returns_400 PASSED [ 85%]
tests/test_research_assistant_integration.py::TestChoiceButtonsFlow::test_choices_rendered_in_web_chat PASSED [ 86%]
tests/test_research_assistant_integration.py::TestChoiceButtonsFlow::test_choice_selection_sends_label_as_message PASSED [ 87%]
tests/test_research_assistant_integration.py::TestSessionEventAuditTrail::test_full_conversation_event_trail PASSED [ 88%]
tests/test_research_assistant_integration.py::TestSessionEventAuditTrail::test_events_have_timestamps PASSED [ 89%]
tests/test_research_assistant_integration.py::TestCartContextPassedToResolver::test_second_chat_includes_cart_context PASSED [ 90%]
tests/test_research_assistant_integration.py::TestCartContextPassedToResolver::test_unchecked_proposal_shown_as_unchecked_in_context PASSED [ 92%]
tests/test_research_assistant_integration.py::TestApiRoutesJsonFormat::test_chat_response_format PASSED [ 93%]
tests/test_research_assistant_integration.py::TestApiRoutesJsonFormat::test_confirm_response_format PASSED [ 94%]
tests/test_research_assistant_integration.py::TestApiRoutesJsonFormat::test_multi_turn_conversation_via_api PASSED [ 95%]
tests/test_research_assistant_integration.py::TestApiRoutesJsonFormat::test_chat_without_session_creates_new PASSED [ 96%]
tests/test_research_assistant_integration.py::TestWebCartFullFlow::test_web_chat_to_toggle_to_fetch PASSED [ 97%]
tests/test_research_assistant_integration.py::TestWebCartFullFlow::test_web_fetch_no_checked_returns_400 PASSED [ 98%]
tests/test_research_assistant_integration.py::TestWebCartFullFlow::test_web_toggle_logs_session_event PASSED [100%]

============================== 88 passed in 1.26s ==============================
```

88 tests, all green, in 1.26 seconds. The full stack — database, resolver, routes, cart, events — is verified end-to-end.

---

## Summary

The data flow is:

1. **Browser** → HTMX form POST → `web_chat()`
2. **Route** → creates/loads session, builds cart context, calls `resolver.resolve()`
3. **Resolver** → Claude agentic loop (1-10 rounds), searches dictionary, proposes tables
4. **Display payloads** → proposals persisted to DB, OOB-swapped into cart panel
5. **Cart toggle** → HTMX checkbox → `web_cart_toggle()` → DB update → re-rendered card
6. **Fetch Selected** → `web_cart_fetch()` → one job per checked proposal → status "queued"
7. **Worker thread** → polls DB, claims job, decrypts creds, runs ABS pipeline, downloads CSV
8. **Status polling** → HTMX every 10s → `web_job_status()` → "Completed! Download CSV"

The Python layer is deliberately thin — Claude drives the conversation, the DB tracks state, HTMX handles UI updates. No JavaScript frameworks, no client-side state management, no build step.
