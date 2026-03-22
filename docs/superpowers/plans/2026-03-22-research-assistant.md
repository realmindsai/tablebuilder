# Research Assistant Bot Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the transactional chat resolver with an AI-driven research assistant that uses a data scientist persona, 6 tools, a shopping cart UI, confidence scoring, and full session event logging.

**Architecture:** Claude drives the conversation via extended tool-use. Python is a thin tool executor + event logger. Display tools produce dual returns — text confirmation to Claude, structured payloads to the UI via HTMX OOB swaps. Shopping cart accumulates proposals; researcher controls when to fetch.

**Tech Stack:** FastAPI, Anthropic Claude API (tool-use), SQLite, HTMX (with OOB swaps), Pico CSS, Jinja2

**Spec:** `docs/superpowers/specs/2026-03-22-research-assistant-design.md`

---

## File Structure

| File | Role | Change type |
|------|------|-------------|
| `src/tablebuilder/service/db.py` | Schema: `session_events` table, `proposals_json` + `research_question` columns, new CRUD methods | Modify |
| `src/tablebuilder/dictionary_db.py` | New `compare_datasets()` function | Modify |
| `src/tablebuilder/service/chat_resolver.py` | New persona prompt, 6 tools, display payload collection, richer return type | Modify |
| `src/tablebuilder/service/routes_chat.py` | Handle new resolve return format, updated session persistence | Modify |
| `src/tablebuilder/service/routes_web.py` | Cart endpoints (`toggle`, `fetch`), two-panel rendering, OOB swaps | Modify |
| `src/tablebuilder/service/templates/base.html` | Two-panel grid layout for chat page | Modify |
| `src/tablebuilder/service/templates/chat.html` | Two-panel layout, cart component, choice buttons | Modify |
| `tests/test_service_db.py` | Tests for new schema and CRUD methods | Modify |
| `tests/test_dictionary_db.py` | Tests for `compare_datasets()` | Modify |
| `tests/test_service_chat_resolver.py` | Tests for new tools, persona, display payloads | Modify |
| `tests/test_service_routes_chat.py` | Tests for updated response format | Modify |
| `tests/test_service_routes_web.py` | Tests for cart endpoints | Create |

---

## Chunk 1: Database Layer — Schema Migration + CRUD

### Task 1: Add `session_events` table and new `chat_sessions` columns

**Files:**
- Modify: `src/tablebuilder/service/db.py:9-56` (schema SQL) and `db.py:245-291` (chat session methods)
- Test: `tests/test_service_db.py`

- [ ] **Step 1: Write failing tests for `session_events` table**

```python
# In tests/test_service_db.py, add to TestServiceDBSchema:

def test_session_events_table_exists(self, db):
    """session_events table exists after initialization."""
    conn = sqlite3.connect(db.db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t[0] for t in tables]
    conn.close()
    assert "session_events" in table_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_service_db.py::TestServiceDBSchema::test_session_events_table_exists -v`
Expected: FAIL — `session_events` not in table_names

- [ ] **Step 3: Add `session_events` table and new columns to schema SQL in `db.py`**

Add to `_SCHEMA_SQL` after the `chat_sessions` CREATE TABLE:

```sql
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id),
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    detail TEXT,
    metadata_json TEXT
);
```

Also add two columns to the `chat_sessions` CREATE TABLE:
```sql
    proposals_json TEXT DEFAULT '[]',
    research_question TEXT DEFAULT '',
```
These go after the `resolved_request_json TEXT,` line.

**IMPORTANT — Migration for existing databases:** `CREATE TABLE IF NOT EXISTS` won't add new columns to an existing table. Add migration code to `_init_schema()` after `conn.executescript(_SCHEMA_SQL)`:

```python
        # Migrate existing chat_sessions table with new columns
        for col, definition in [
            ("proposals_json", "TEXT DEFAULT '[]'"),
            ("research_question", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE chat_sessions ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass  # column already exists
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_service_db.py::TestServiceDBSchema -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tablebuilder/service/db.py tests/test_service_db.py
git commit -m "feat: add session_events table and proposals_json column to schema"
```

### Task 2: Add `session_events` CRUD methods

**Files:**
- Modify: `src/tablebuilder/service/db.py` (add methods after the Chat Sessions section)
- Test: `tests/test_service_db.py`

- [ ] **Step 1: Write failing tests for `add_session_event()` and `get_session_events()`**

```python
# In tests/test_service_db.py, add new class:

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_db.py::TestServiceDBSessionEvents -v`
Expected: FAIL — `add_session_event` not defined

- [ ] **Step 3: Implement `add_session_event()` and `get_session_events()` in `db.py`**

Add after the `link_chat_to_job` method:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_db.py::TestServiceDBSessionEvents -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tablebuilder/service/db.py tests/test_service_db.py
git commit -m "feat: add session_events CRUD methods"
```

### Task 3: Add proposal CRUD methods

**Files:**
- Modify: `src/tablebuilder/service/db.py`
- Test: `tests/test_service_db.py`

- [ ] **Step 1: Write failing tests for proposal methods**

```python
# In tests/test_service_db.py, add new class:

class TestServiceDBProposals:
    def test_get_proposals_empty(self, db):
        """New session has empty proposals list."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        session_id = db.create_chat_session(user_id=user_id, messages_json="[]")
        proposals = db.get_proposals(session_id)
        assert proposals == []

    def test_add_proposal(self, db):
        """Add a proposal and retrieve it."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        session_id = db.create_chat_session(user_id=user_id, messages_json="[]")
        proposal = {
            "id": "p1",
            "dataset": "Census 2021",
            "rows": ["SEXP Sex"],
            "cols": [],
            "wafers": [],
            "match_confidence": 85,
            "clarity_confidence": 70,
            "rationale": "Good match for sex demographics",
            "status": "checked",
            "job_id": None,
        }
        db.add_proposal(session_id, proposal)
        proposals = db.get_proposals(session_id)
        assert len(proposals) == 1
        assert proposals[0]["dataset"] == "Census 2021"
        assert proposals[0]["status"] == "checked"

    def test_update_proposal_status(self, db):
        """Toggle a proposal's checked status."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        session_id = db.create_chat_session(user_id=user_id, messages_json="[]")
        proposal = {
            "id": "p1", "dataset": "D", "rows": ["R"], "cols": [], "wafers": [],
            "match_confidence": 80, "clarity_confidence": 70,
            "rationale": "test", "status": "checked", "job_id": None,
        }
        db.add_proposal(session_id, proposal)
        db.update_proposal_status(session_id, "p1", "unchecked")
        proposals = db.get_proposals(session_id)
        assert proposals[0]["status"] == "unchecked"

    def test_update_research_question(self, db):
        """Update the session's research question summary."""
        user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
        session_id = db.create_chat_session(user_id=user_id, messages_json="[]")
        db.update_research_question(session_id, "Income by region in Victoria")
        session = db.get_chat_session(session_id)
        assert session["research_question"] == "Income by region in Victoria"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_db.py::TestServiceDBProposals -v`
Expected: FAIL — methods not defined

- [ ] **Step 3: Implement proposal methods in `db.py`**

Add after the session events methods:

```python
    # -- Proposals --

    def get_proposals(self, session_id: str) -> list[dict]:
        conn = self._connect()
        row = conn.execute(
            "SELECT proposals_json FROM chat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        conn.close()
        if row is None or not row["proposals_json"]:
            return []
        return json.loads(row["proposals_json"])

    def add_proposal(self, session_id: str, proposal: dict) -> None:
        proposals = self.get_proposals(session_id)
        proposals.append(proposal)
        conn = self._connect()
        conn.execute(
            "UPDATE chat_sessions SET proposals_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(proposals), _now(), session_id),
        )
        conn.commit()
        conn.close()

    def update_proposal_status(
        self, session_id: str, proposal_id: str, status: str,
    ) -> None:
        proposals = self.get_proposals(session_id)
        for p in proposals:
            if p["id"] == proposal_id:
                p["status"] = status
                break
        conn = self._connect()
        conn.execute(
            "UPDATE chat_sessions SET proposals_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(proposals), _now(), session_id),
        )
        conn.commit()
        conn.close()

    def update_research_question(self, session_id: str, question: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE chat_sessions SET research_question = ?, updated_at = ? WHERE id = ?",
            (question, _now(), session_id),
        )
        conn.commit()
        conn.close()
```

**IMPORTANT:** First, add `import json` at the top of `db.py` — it's not there currently and `json.loads()`/`json.dumps()` will raise `NameError` without it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_db.py::TestServiceDBProposals -v`
Expected: PASS

- [ ] **Step 5: Run ALL db tests to confirm nothing is broken**

Run: `uv run pytest tests/test_service_db.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/tablebuilder/service/db.py tests/test_service_db.py
git commit -m "feat: add proposal and research_question CRUD methods"
```

---

## Chunk 2: Dictionary — `compare_datasets()` Function

### Task 4: Add `compare_datasets()` to `dictionary_db.py`

**Files:**
- Modify: `src/tablebuilder/dictionary_db.py` (add function after `get_variables_by_code`)
- Test: `tests/test_dictionary_db.py`

- [ ] **Step 1: Write failing tests**

```python
# In tests/test_dictionary_db.py, add new class:

from tablebuilder.dictionary_db import compare_datasets

class TestCompareDatasets:
    def test_compare_two_datasets(self, sample_cache, tmp_path):
        """compare_datasets returns variable overlap and differences."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        result = compare_datasets(
            db_path, ["Test Survey, 2021", "Business Data (BLADE), 2020"]
        )
        assert len(result) == 2
        assert result[0]["name"] == "Test Survey, 2021"
        assert result[1]["name"] == "Business Data (BLADE), 2020"
        # Each entry has variables list
        assert "variables" in result[0]
        assert any(v["label"] == "Sex" for v in result[0]["variables"])

    def test_compare_nonexistent_dataset(self, sample_cache, tmp_path):
        """compare_datasets returns None entry for missing dataset."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        result = compare_datasets(db_path, ["Test Survey, 2021", "Nonexistent"])
        assert len(result) == 2
        assert result[0]["name"] == "Test Survey, 2021"
        assert result[1] is None

    def test_compare_single_dataset(self, sample_cache, tmp_path):
        """compare_datasets works with a single dataset."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        result = compare_datasets(db_path, ["Test Survey, 2021"])
        assert len(result) == 1
        assert result[0]["name"] == "Test Survey, 2021"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dictionary_db.py::TestCompareDatasets -v`
Expected: FAIL — `compare_datasets` not importable

- [ ] **Step 3: Implement `compare_datasets()` in `dictionary_db.py`**

Add after `get_variables_by_code`:

```python
def compare_datasets(db_path: Path, dataset_names: list[str]) -> list[dict | None]:
    """Compare multiple datasets side-by-side.

    Returns a list (one per input name) of dicts with name, geographies,
    and variables. Returns None for datasets that don't exist.
    """
    results = []
    for name in dataset_names:
        ds = get_dataset(db_path, name)
        if ds is None:
            results.append(None)
            continue
        # Flatten variables from all groups
        variables = []
        for group in ds.get("groups", []):
            for var in group.get("variables", []):
                variables.append({
                    "code": var.get("code", ""),
                    "label": var["label"],
                    "group": group["path"],
                    "category_count": len(var.get("categories", [])),
                })
        results.append({
            "name": ds["name"],
            "geographies": ds.get("geographies", []),
            "variables": variables,
        })
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dictionary_db.py::TestCompareDatasets -v`
Expected: PASS

- [ ] **Step 5: Run ALL dictionary tests**

Run: `uv run pytest tests/test_dictionary_db.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/tablebuilder/dictionary_db.py tests/test_dictionary_db.py
git commit -m "feat: add compare_datasets() for side-by-side dataset comparison"
```

---

## Chunk 3: Chat Resolver — Persona, Tools, and Display Payloads

### Task 5: Replace system prompt with data scientist persona

**Files:**
- Modify: `src/tablebuilder/service/chat_resolver.py:13-28` (SYSTEM_PROMPT)
- Test: `tests/test_service_chat_resolver.py`

- [ ] **Step 1: Write failing test for persona prompt content**

```python
# In tests/test_service_chat_resolver.py, update existing test:

def test_build_system_prompt_has_persona(self):
    """System prompt establishes the data scientist persona."""
    resolver = ChatResolver(anthropic_api_key="test-key")
    prompt = resolver._build_system_prompt()
    assert "senior" in prompt.lower() or "research data scientist" in prompt.lower()
    assert "ABS" in prompt or "Australian Bureau of Statistics" in prompt
    # Must NOT contain the old JSON-only output instructions
    assert "respond with ONLY a JSON" not in prompt
    assert "respond with ONLY:" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_service_chat_resolver.py::TestChatResolver::test_build_system_prompt_has_persona -v`
Expected: FAIL — old prompt has "respond with ONLY"

- [ ] **Step 3: Replace `SYSTEM_PROMPT` in `chat_resolver.py`**

Replace the entire `SYSTEM_PROMPT` string with:

```python
SYSTEM_PROMPT = """You are a senior research data scientist with deep expertise in Australian Bureau of Statistics census and survey data. You've spent years working with the 96 datasets in ABS TableBuilder — you know the variables, the quirks, the gaps.

A researcher has come to you for help. Your job is to understand their research question and help them get the exact data they need. You're collegial, curious, and opinionated when it matters. You get excited when you spot a connection the researcher hasn't seen. You know when to suggest a better variable and when to just give them what they asked for.

You understand research methodology — you can advise on denominators, confounders, and geographic levels. You know that cross-tabulation needs compatible datasets and that geographic hierarchies matter.

You have tools to search and explore the ABS data dictionary. Use them proactively — when a researcher mentions a topic, search for it immediately. Show them what's available. Suggest combinations they might not have considered.

When you find relevant data, use the propose_table_request tool to add it to the researcher's data cart. Include your confidence assessment:
- match_confidence (0-100): how well the dataset's variables cover what the researcher is asking about
- clarity_confidence (0-100): has the researcher been specific enough that you're confident this data will answer their question?

If clarity_confidence would be below 70, ask a follow-up question before proposing. Use present_choices when a structured selection would be clearer than an open question (e.g., geographic levels, variable options).

When the researcher asks for a summary of the session, use show_session_summary.

Variable labels in proposals must EXACTLY match the labels from the dictionary. Do not modify or abbreviate them.

Stay focused on data. You're a data scientist in a consultation — if the conversation drifts off-topic, gently steer it back: "That's outside my wheelhouse — I'm here to help you find the right data. What are you working on?"
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_service_chat_resolver.py::TestChatResolver::test_build_system_prompt_has_persona -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tablebuilder/service/chat_resolver.py tests/test_service_chat_resolver.py
git commit -m "feat: replace transactional prompt with data scientist persona"
```

### Task 6: Add new tool definitions and display payload mechanism

**Files:**
- Modify: `src/tablebuilder/service/chat_resolver.py:30-64` (TOOLS list) and class methods
- Test: `tests/test_service_chat_resolver.py`

- [ ] **Step 1: Write failing tests for new tools and resolve return type**

```python
# In tests/test_service_chat_resolver.py, add:

class TestChatResolverTools:
    def test_tools_include_all_six(self):
        """Resolver has 6 tools: 3 research + 3 display."""
        from tablebuilder.service.chat_resolver import TOOLS
        tool_names = [t["name"] for t in TOOLS]
        assert "search_dictionary" in tool_names
        assert "get_dataset_variables" in tool_names
        assert "compare_datasets" in tool_names
        assert "propose_table_request" in tool_names
        assert "present_choices" in tool_names
        assert "show_session_summary" in tool_names

    def test_handle_propose_table_request(self):
        """propose_table_request tool stores proposal and returns confirmation."""
        resolver = ChatResolver(anthropic_api_key="test-key")
        # These are initialized in __init__ (see Step 3 note below)
        result = resolver._handle_tool_call("propose_table_request", {
            "dataset": "Census 2021",
            "rows": ["SEXP Sex"],
            "cols": [],
            "wafers": [],
            "match_confidence": 85,
            "clarity_confidence": 70,
            "rationale": "Good match for sex demographics",
        })
        assert "Proposal" in result
        assert len(resolver._display_payloads) == 1
        assert resolver._display_payloads[0]["type"] == "proposal"

    def test_handle_present_choices(self):
        """present_choices tool stores choices and returns confirmation."""
        resolver = ChatResolver(anthropic_api_key="test-key")
        resolver._display_payloads = []
        result = resolver._handle_tool_call("present_choices", {
            "question": "Which geographic level?",
            "options": [
                {"label": "SA2", "description": "Suburbs"},
                {"label": "SA3", "description": "Regional"},
            ],
            "allow_multiple": False,
        })
        assert "Choices presented" in result
        assert len(resolver._display_payloads) == 1
        assert resolver._display_payloads[0]["type"] == "choices"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_chat_resolver.py::TestChatResolverTools -v`
Expected: FAIL — tools and methods don't exist

- [ ] **Step 3: Add tool definitions and initialize instance attributes**

First, update `__init__` in `ChatResolver` to initialize the display payload state:

```python
    def __init__(self, anthropic_api_key: str):
        self.api_key = anthropic_api_key
        self._client = None
        self._display_payloads: list = []
        self._session_id: str | None = None
        self._db = None
```

Then replace the entire `TOOLS` list with:

```python
TOOLS = [
    {
        "name": "search_dictionary",
        "description": "Search the ABS data dictionary for datasets and variables matching a query. Returns ranked results with dataset name, variable code, label, and categories. Use this proactively when the researcher mentions any data topic.",
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
        "description": "Get the full variable tree for a specific dataset by exact name. Use to explore what variables and categories are available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_name": {
                    "type": "string",
                    "description": "Exact dataset name from search results",
                },
            },
            "required": ["dataset_name"],
        },
    },
    {
        "name": "compare_datasets",
        "description": "Compare 2-3 datasets side-by-side to see variable overlap and differences. Use when the researcher's question could be answered by multiple datasets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of exact dataset names to compare",
                },
            },
            "required": ["dataset_names"],
        },
    },
    {
        "name": "propose_table_request",
        "description": "Propose a data table for the researcher's cart. This adds a card to their shopping cart with the dataset, variables, and your confidence assessment. The researcher can accept or reject it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Exact dataset name"},
                "rows": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Variable labels for row axis",
                },
                "cols": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Variable labels for column axis",
                },
                "wafers": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Variable labels for wafer (layer) axis",
                },
                "match_confidence": {
                    "type": "integer",
                    "description": "0-100: how well this dataset covers the research question",
                },
                "clarity_confidence": {
                    "type": "integer",
                    "description": "0-100: how clearly the researcher has specified what they need",
                },
                "rationale": {
                    "type": "string",
                    "description": "Brief explanation of why this dataset and these variables",
                },
            },
            "required": ["dataset", "rows", "match_confidence", "clarity_confidence", "rationale"],
        },
    },
    {
        "name": "present_choices",
        "description": "Show the researcher a structured multiple-choice question. Use this when a selection from a fixed set of options would be clearer than an open question (e.g., geographic levels, variable options, axis assignments).",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask"},
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["label"],
                    },
                    "description": "List of options to present",
                },
                "allow_multiple": {
                    "type": "boolean",
                    "description": "Whether multiple selections are allowed",
                    "default": False,
                },
            },
            "required": ["question", "options"],
        },
    },
    {
        "name": "show_session_summary",
        "description": "Generate a summary of this research session — datasets explored, variables selected, proposals made, and jobs queued. Use when the researcher asks for a summary or when the conversation is wrapping up.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]
```

- [ ] **Step 4: Update `_handle_tool_call()` to handle new tools**

Replace the entire `_handle_tool_call` method:

```python
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
            if result is None:
                return json.dumps(None)
            # Truncate to avoid token overflow
            summary = {
                "name": result["name"],
                "geographies": result.get("geographies", []),
                "groups": [],
            }
            for group in result.get("groups", []):
                g = {"path": group["path"], "variables": []}
                for var in group.get("variables", []):
                    cats = var.get("categories", [])
                    g["variables"].append({
                        "code": var.get("code", ""),
                        "label": var["label"],
                        "category_count": len(cats),
                        "sample_categories": cats[:5],
                    })
                summary["groups"].append(g)
            return json.dumps(summary)

        elif tool_name == "compare_datasets":
            if not DEFAULT_DB_PATH.exists():
                return json.dumps([])
            result = compare_datasets(
                DEFAULT_DB_PATH, tool_input["dataset_names"],
            )
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
                "options": tool_input["options"],
                "allow_multiple": tool_input.get("allow_multiple", False),
            }
            self._display_payloads.append({"type": "choices", "data": choices})
            return "Choices presented, waiting for researcher's selection."

        elif tool_name == "show_session_summary":
            # Return session events for Claude to summarize
            events = []
            if self._db and self._session_id:
                events = self._db.get_session_events(self._session_id)
                proposals = self._db.get_proposals(self._session_id)
            else:
                proposals = []
            summary_data = {
                "events": events,
                "proposals": proposals,
            }
            self._display_payloads.append({"type": "summary", "data": summary_data})
            return json.dumps(summary_data)

        return json.dumps({"error": f"Unknown tool: {tool_name}"})
```

- [ ] **Step 5: Update imports at top of `chat_resolver.py`**

```python
from tablebuilder.dictionary_db import DEFAULT_DB_PATH, search, get_dataset, compare_datasets
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_chat_resolver.py::TestChatResolverTools -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/tablebuilder/service/chat_resolver.py tests/test_service_chat_resolver.py
git commit -m "feat: add 6 tools with display payload mechanism to resolver"
```

### Task 7: Update `resolve()` to return richer response with display payloads

**Files:**
- Modify: `src/tablebuilder/service/chat_resolver.py:155-206` (`resolve` method)
- Test: `tests/test_service_chat_resolver.py`

- [ ] **Step 1: Write failing test for new resolve return format**

```python
# In tests/test_service_chat_resolver.py, update TestChatResolver:

@patch("tablebuilder.service.chat_resolver.anthropic.Anthropic")
def test_resolve_returns_text_and_payloads(self, mock_anthropic_class):
    """Resolver returns dict with 'text' and 'display_payloads' keys."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_text = MagicMock(type="text", text="I found some interesting data for you.")
    mock_response.content = [mock_text]
    mock_client.messages.create.return_value = mock_response

    resolver = ChatResolver(anthropic_api_key="test-key")
    result = resolver.resolve("population by sex")
    assert "text" in result
    assert "display_payloads" in result
    assert isinstance(result["display_payloads"], list)
    assert result["text"] == "I found some interesting data for you."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_service_chat_resolver.py::TestChatResolver::test_resolve_returns_text_and_payloads -v`
Expected: FAIL — old resolve returns a flat dict

- [ ] **Step 3: Rewrite `resolve()` method**

Replace the entire `resolve` method with:

```python
    def resolve(
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
        session_id: str | None = None,
        db=None,
        cart_context: str = "",
    ) -> dict:
        """Resolve a natural language query.

        Returns a dict with:
            text: Claude's natural language response
            display_payloads: list of display objects for the UI
            messages: the full conversation history (for persistence)
        """
        self._display_payloads = []
        self._session_id = session_id
        self._db = db

        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": user_message})

        system_prompt = self._build_system_prompt()
        if cart_context:
            system_prompt += f"\n\nCurrent data cart:\n{cart_context}"

        for round_num in range(10):
            try:
                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2048,
                    system=system_prompt,
                    tools=TOOLS,
                    messages=messages,
                )
            except Exception as e:
                logger.error("Claude API error: %s", e)
                return {
                    "text": f"Sorry, I encountered an error: {e}",
                    "display_payloads": [],
                    "messages": messages,
                }

            logger.info(
                "Round %d: stop_reason=%s, content_types=%s",
                round_num + 1, response.stop_reason,
                [b.type for b in response.content],
            )

            # Serialize response content for history
            content_dicts = []
            for block in response.content:
                if block.type == "text":
                    content_dicts.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    content_dicts.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if tool_use_blocks:
                messages.append({"role": "assistant", "content": content_dicts})
                tool_results = []
                for block in tool_use_blocks:
                    logger.info("Tool call: %s(%s)", block.name, json.dumps(block.input)[:200])
                    result = self._handle_tool_call(block.name, block.input)
                    logger.info("Tool result: %s chars", len(result))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            text_blocks = [b for b in response.content if b.type == "text"]
            if text_blocks:
                text = text_blocks[0].text
                logger.info("Text response: %s", text[:200])
                messages.append({"role": "assistant", "content": content_dicts})
                return {
                    "text": text,
                    "display_payloads": self._display_payloads,
                    "messages": messages,
                }

        return {
            "text": "I wasn't able to fully process your request. Could you be more specific?",
            "display_payloads": self._display_payloads,
            "messages": messages,
        }
```

- [ ] **Step 4: Remove `_extract_json()` method** — no longer needed since we're not parsing JSON from Claude's text output

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_chat_resolver.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tablebuilder/service/chat_resolver.py tests/test_service_chat_resolver.py
git commit -m "feat: resolve() returns text + display_payloads + full message history"
```

---

## Chunk 4: Routes — Update Chat Routes for New Resolver Format

### Task 8: Update `routes_chat.py` for new resolve return format

**Files:**
- Modify: `src/tablebuilder/service/routes_chat.py`
- Test: `tests/test_service_routes_chat.py`

- [ ] **Step 1: Write failing test for new response format**

```python
# In tests/test_service_routes_chat.py, add:

@patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
def test_chat_returns_text_and_payloads(self, mock_resolve, registered_client):
    """Chat endpoint returns text and display_payloads from resolver."""
    mock_resolve.return_value = {
        "text": "I found some data for you.",
        "display_payloads": [
            {"type": "proposal", "data": {"id": "p1", "dataset": "Census 2021"}},
        ],
        "messages": [
            {"role": "user", "content": "test"},
            {"role": "assistant", "content": [{"type": "text", "text": "I found some data for you."}]},
        ],
    }
    client, api_key = registered_client
    resp = client.post(
        "/api/chat",
        json={"message": "test"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "text" in body["response"]
    assert "display_payloads" in body["response"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_service_routes_chat.py::TestChatRoutes::test_chat_returns_text_and_payloads -v`
Expected: FAIL — old route doesn't handle new format

- [ ] **Step 3: Update `routes_chat.py` to handle new resolver format**

Replace the `chat` endpoint:

```python
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
        session_id = session["id"]
    else:
        session_id = db.create_chat_session(
            user_id=user["id"], messages_json="[]"
        )
        history = []

    # Build cart context for Claude
    proposals = db.get_proposals(session_id)
    cart_context = ""
    if proposals:
        lines = []
        for p in proposals:
            status = "CHECKED" if p["status"] == "checked" else "unchecked"
            lines.append(f"- [{status}] {p['dataset']}: rows={p.get('rows', [])}")
        cart_context = "\n".join(lines)

    # Log user message event
    db.add_session_event(session_id, "user_message", body.message)

    result = resolver.resolve(
        body.message,
        conversation_history=history,
        session_id=session_id,
        db=db,
        cart_context=cart_context,
    )

    # Persist any proposals from display payloads
    for payload in result.get("display_payloads", []):
        if payload["type"] == "proposal":
            db.add_proposal(session_id, payload["data"])
            db.add_session_event(
                session_id, "proposal_created",
                f"Proposed: {payload['data']['dataset']}",
                metadata_json=json.dumps(payload["data"]),
            )

    # Log assistant response
    db.add_session_event(session_id, "assistant_message", result.get("text", ""))

    # Persist conversation history (full Anthropic message format)
    db.update_chat_session(session_id, json.dumps(result.get("messages", [])))

    return {
        "session_id": session_id,
        "response": {
            "text": result.get("text", ""),
            "display_payloads": result.get("display_payloads", []),
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_routes_chat.py -v`
Expected: PASS (some old tests may need the mock return value updated to new format)

- [ ] **Step 5: Update any remaining tests that use old resolver return format**

The `test_chat_creates_session` and `test_chat_confirm_creates_job` tests mock `resolve()` with the old format. Update both:

**`test_chat_creates_session`** — update mock return value:
```python
mock_resolve.return_value = {
    "text": "I found Census 2021 with variable SEXP Sex. Shall I fetch this?",
    "display_payloads": [],
    "messages": [],
}
```

**`test_chat_confirm_creates_job`** — this test must now seed proposals into `proposals_json` before confirming, and assert the new response shape:
```python
@patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
def test_chat_confirm_creates_job(self, mock_resolve, registered_client):
    mock_resolve.return_value = {
        "text": "Here's a dataset for you.",
        "display_payloads": [
            {"type": "proposal", "data": {
                "id": "p1", "dataset": "Census 2021", "rows": ["SEXP Sex"],
                "cols": [], "wafers": [], "match_confidence": 85,
                "clarity_confidence": 75, "rationale": "test",
                "status": "checked", "job_id": None,
            }},
        ],
        "messages": [],
    }
    client, api_key = registered_client
    headers = {"Authorization": f"Bearer {api_key}"}

    # Chat first (this persists the proposal via the updated route)
    resp = client.post("/api/chat", json={"message": "test"}, headers=headers)
    session_id = resp.json()["session_id"]

    # Confirm
    resp = client.post("/api/chat/confirm", json={"session_id": session_id}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "jobs" in body
    assert len(body["jobs"]) == 1
```

- [ ] **Step 6: Commit**

```bash
git add src/tablebuilder/service/routes_chat.py tests/test_service_routes_chat.py
git commit -m "feat: update chat routes for new resolver format with display payloads"
```

### Task 9: Update confirm endpoint for multi-proposal model

**Files:**
- Modify: `src/tablebuilder/service/routes_chat.py:68-93`
- Test: `tests/test_service_routes_chat.py`

- [ ] **Step 1: Write failing test for multi-proposal confirm**

```python
# In tests/test_service_routes_chat.py, add:

@patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
def test_confirm_queues_checked_proposals(self, mock_resolve, registered_client):
    """Confirm creates jobs for all checked proposals."""
    mock_resolve.return_value = {
        "text": "Here are two datasets for you.",
        "display_payloads": [
            {"type": "proposal", "data": {
                "id": "p1", "dataset": "Census 2021", "rows": ["SEXP Sex"],
                "cols": [], "wafers": [], "match_confidence": 85,
                "clarity_confidence": 75, "rationale": "test",
                "status": "checked", "job_id": None,
            }},
            {"type": "proposal", "data": {
                "id": "p2", "dataset": "Census 2021", "rows": ["AGEP Age"],
                "cols": [], "wafers": [], "match_confidence": 80,
                "clarity_confidence": 75, "rationale": "test",
                "status": "checked", "job_id": None,
            }},
        ],
        "messages": [],
    }
    client, api_key = registered_client
    headers = {"Authorization": f"Bearer {api_key}"}

    # Create session with proposals via chat
    resp = client.post("/api/chat", json={"message": "test"}, headers=headers)
    session_id = resp.json()["session_id"]

    # Confirm all checked proposals
    resp = client.post(
        "/api/chat/confirm",
        json={"session_id": session_id},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["jobs"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_service_routes_chat.py::TestChatRoutes::test_confirm_queues_checked_proposals -v`
Expected: FAIL — old confirm returns single job_id

- [ ] **Step 3: Rewrite the confirm endpoint**

```python
@router.post("/chat/confirm")
async def confirm_chat(
    body: ChatConfirm, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    session = db.get_chat_session(body.session_id)
    if session is None or session["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Chat session not found")

    proposals = db.get_proposals(body.session_id)
    checked = [p for p in proposals if p.get("status") == "checked"]
    if not checked:
        raise HTTPException(status_code=400, detail="No checked proposals to confirm")

    jobs = []
    for proposal in checked:
        request_json = json.dumps({
            "dataset": proposal["dataset"],
            "rows": proposal.get("rows", []),
            "cols": proposal.get("cols", []),
            "wafers": proposal.get("wafers", []),
        })
        job_id = db.create_job(user_id=user["id"], request_json=request_json)
        db.update_proposal_status(body.session_id, proposal["id"], "confirmed")
        proposal["job_id"] = job_id
        jobs.append({"job_id": job_id, "dataset": proposal["dataset"]})

    db.add_session_event(
        body.session_id, "jobs_queued",
        f"Queued {len(jobs)} job(s)",
        metadata_json=json.dumps(jobs),
    )

    return {
        "session_id": body.session_id,
        "jobs": jobs,
        "status": "queued",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_routes_chat.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tablebuilder/service/routes_chat.py tests/test_service_routes_chat.py
git commit -m "feat: confirm endpoint queues all checked proposals as jobs"
```

---

## Chunk 5: Web Routes — Cart Endpoints and Two-Panel UI

### Task 10: Add cart toggle and fetch endpoints to `routes_web.py`

**Files:**
- Modify: `src/tablebuilder/service/routes_web.py`
- Create: `tests/test_service_routes_web.py`

- [ ] **Step 1: Write failing tests for cart endpoints**

```python
# Create tests/test_service_routes_web.py

# ABOUTME: Tests for web UI routes including cart toggle and fetch endpoints.
# ABOUTME: Validates HTMX-based proposal management and job creation from cart.

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from tablebuilder.service.app import create_app
from tablebuilder.service.auth import generate_api_key, generate_encryption_key, hash_api_key


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
    client.cookies.set("tb_api_key", api_key)
    return client, api_key, app_env


class TestCartToggle:
    def test_toggle_unchecks_proposal(self, registered_client):
        """POST /web/cart/toggle/{id} toggles a checked proposal to unchecked."""
        client, api_key, app = registered_client
        db = app.state.db
        key_hash = hash_api_key(api_key)
        user = db.get_user_by_api_key_hash(key_hash)
        session_id = db.create_chat_session(user_id=user["id"], messages_json="[]")
        db.add_proposal(session_id, {
            "id": "p1", "dataset": "D", "rows": ["R"], "cols": [], "wafers": [],
            "match_confidence": 80, "clarity_confidence": 70,
            "rationale": "test", "status": "checked", "job_id": None,
        })
        resp = client.post(
            f"/web/cart/toggle/p1",
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        proposals = db.get_proposals(session_id)
        assert proposals[0]["status"] == "unchecked"

    def test_toggle_checks_unchecked_proposal(self, registered_client):
        """Toggle an unchecked proposal back to checked."""
        client, api_key, app = registered_client
        db = app.state.db
        key_hash = hash_api_key(api_key)
        user = db.get_user_by_api_key_hash(key_hash)
        session_id = db.create_chat_session(user_id=user["id"], messages_json="[]")
        db.add_proposal(session_id, {
            "id": "p1", "dataset": "D", "rows": ["R"], "cols": [], "wafers": [],
            "match_confidence": 80, "clarity_confidence": 70,
            "rationale": "test", "status": "unchecked", "job_id": None,
        })
        resp = client.post(
            f"/web/cart/toggle/p1",
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        proposals = db.get_proposals(session_id)
        assert proposals[0]["status"] == "checked"


class TestCartFetch:
    def test_fetch_creates_jobs_for_checked(self, registered_client):
        """POST /web/cart/fetch queues jobs for all checked proposals."""
        client, api_key, app = registered_client
        db = app.state.db
        key_hash = hash_api_key(api_key)
        user = db.get_user_by_api_key_hash(key_hash)
        session_id = db.create_chat_session(user_id=user["id"], messages_json="[]")
        db.add_proposal(session_id, {
            "id": "p1", "dataset": "Census 2021", "rows": ["SEXP Sex"],
            "cols": [], "wafers": [], "match_confidence": 85,
            "clarity_confidence": 75, "rationale": "test",
            "status": "checked", "job_id": None,
        })
        db.add_proposal(session_id, {
            "id": "p2", "dataset": "Census 2021", "rows": ["AGEP Age"],
            "cols": [], "wafers": [], "match_confidence": 80,
            "clarity_confidence": 70, "rationale": "test",
            "status": "unchecked", "job_id": None,
        })
        resp = client.post(
            "/web/cart/fetch",
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        # Only the checked proposal should have a job
        jobs = db.list_user_jobs(user["id"])
        assert len(jobs) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_routes_web.py -v`
Expected: FAIL — endpoints don't exist

- [ ] **Step 3: Add cart endpoints to `routes_web.py`**

Add after the `web_confirm` endpoint:

```python
@router.post("/web/cart/toggle/{proposal_id}", response_class=HTMLResponse)
async def web_cart_toggle(
    proposal_id: str,
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
    target = None
    for p in proposals:
        if p["id"] == proposal_id:
            target = p
            break

    if target is None:
        return HTMLResponse("<p>Proposal not found.</p>", status_code=404)

    new_status = "unchecked" if target["status"] == "checked" else "checked"
    db.update_proposal_status(session_id, proposal_id, new_status)
    db.add_session_event(
        session_id, "proposal_toggled",
        f"{proposal_id} -> {new_status}",
    )

    # Return updated card HTML
    target["status"] = new_status
    return HTMLResponse(_render_cart_card(target, session_id))


@router.post("/web/cart/fetch", response_class=HTMLResponse)
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
        session_id, "jobs_queued",
        f"Queued {len(job_ids)} job(s)",
        metadata_json=json.dumps(job_ids),
    )

    # Return updated cart HTML
    proposals = db.get_proposals(session_id)
    cart_html = _render_cart_contents(proposals, session_id)
    return HTMLResponse(cart_html)


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
                hx-target="#cart-card-{p['id']}"
                hx-swap="outerHTML"
                hx-include="[name='session_id']"
                name="session_id" value="{session_id}">
            <strong>{p['dataset']}</strong>{status_label}
        </label>
        <small style="display: block; margin-left: 1.5rem;">{axes}</small>
        <small style="display: block; margin-left: 1.5rem;">Match: {p.get('match_confidence', '?')}% | Clarity: {p.get('clarity_confidence', '?')}%</small>
        <small style="display: block; margin-left: 1.5rem; color: var(--pico-muted-color);">{p.get('rationale', '')}</small>
    </div>"""


def _render_cart_contents(proposals: list[dict], session_id: str) -> str:
    """Render the inner content of the cart (no wrapper div — callers add the container)."""
    if not proposals:
        return '<p style="color: var(--pico-muted-color);">No proposals yet. Start chatting to discover datasets.</p>'

    cards = "".join(_render_cart_card(p, session_id) for p in proposals)
    has_checked = any(p["status"] == "checked" for p in proposals)
    fetch_btn = ""
    if has_checked:
        fetch_btn = f"""<form hx-post="/web/cart/fetch" hx-target="#cart-items" hx-swap="innerHTML">
            <input type="hidden" name="session_id" value="{session_id}">
            <button type="submit" style="width: 100%;">Fetch Selected</button>
        </form>"""

    return f'{cards}{fetch_btn}'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_routes_web.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tablebuilder/service/routes_web.py tests/test_service_routes_web.py
git commit -m "feat: add cart toggle and fetch endpoints with HTML rendering"
```

### Task 11: Update `web_chat` endpoint for new resolver format and OOB swaps

**Files:**
- Modify: `src/tablebuilder/service/routes_web.py:68-123` (`web_chat` function)
- Test: `tests/test_service_routes_web.py`

- [ ] **Step 1: Write failing test**

```python
# In tests/test_service_routes_web.py, add:

class TestWebChat:
    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_web_chat_returns_oob_cart_update(self, mock_resolve, registered_client):
        """Web chat includes OOB swap for cart when proposals are returned."""
        mock_resolve.return_value = {
            "text": "I found income data for you.",
            "display_payloads": [
                {"type": "proposal", "data": {
                    "id": "p1", "dataset": "Census 2021", "rows": ["INCP Income"],
                    "cols": [], "wafers": [], "match_confidence": 85,
                    "clarity_confidence": 75, "rationale": "Income match",
                    "status": "checked", "job_id": None,
                }},
            ],
            "messages": [],
        }
        client, api_key, app = registered_client
        resp = client.post(
            "/web/chat",
            data={"message": "income data", "session_id": ""},
        )
        assert resp.status_code == 200
        html = resp.text
        # Should contain chat bubble
        assert "I found income data for you." in html
        # Should contain OOB cart update
        assert 'hx-swap-oob' in html
        assert "Census 2021" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_service_routes_web.py::TestWebChat -v`
Expected: FAIL — old web_chat doesn't produce OOB swaps

- [ ] **Step 3: Rewrite `web_chat` endpoint**

Replace the entire `web_chat` function:

```python
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

    # Set session_id for subsequent messages
    html += f'<script>document.getElementById("session_id").value = "{session_id}";</script>'

    # OOB swap for cart if proposals changed
    all_proposals = db.get_proposals(session_id)
    if all_proposals:
        cart_html = _render_cart(all_proposals, session_id)
        cart_inner = _render_cart_contents(all_proposals, session_id)
        html += f'<div id="cart-items" hx-swap-oob="innerHTML:#cart-items">{cart_inner}</div>'

    return HTMLResponse(html)


def _render_choices(choices_data: dict, session_id: str) -> str:
    """Render multiple-choice buttons for inline chat display."""
    question = choices_data["question"]
    options = choices_data["options"]
    allow_multiple = choices_data.get("allow_multiple", False)

    buttons = ""
    for opt in options:
        label = opt["label"]
        desc = opt.get("description", "")
        title_attr = f' title="{desc}"' if desc else ""
        buttons += f"""<button type="submit" name="message" value="{label}"{title_attr}
            style="margin: 0.25rem;" class="outline">{label}</button>"""

    return f"""<div style="margin-top: 0.5rem;">
        <form hx-post="/web/chat" hx-target="#chat-messages" hx-swap="beforeend">
            <input type="hidden" name="session_id" value="{session_id}">
            {buttons}
        </form>
    </div>"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_routes_web.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tablebuilder/service/routes_web.py tests/test_service_routes_web.py
git commit -m "feat: web_chat returns OOB cart swaps and inline choice buttons"
```

---

## Chunk 6: Templates — Two-Panel Layout

### Task 12: Update `base.html` for two-panel grid on chat page

**Files:**
- Modify: `src/tablebuilder/service/templates/base.html`

- [ ] **Step 1: Add two-panel CSS to `base.html`**

Add the following CSS rules inside the `<style>` block, after the existing `.filmstrip` rules:

```css
.two-panel { display: grid; grid-template-columns: 1fr 350px; gap: 1rem; max-width: 1200px; margin: 0 auto; }
.two-panel .chat-container { max-width: none; margin: 0; }
.cart-panel { position: sticky; top: 1rem; max-height: calc(100vh - 6rem); overflow-y: auto; }
.cart-panel h3 { margin-bottom: 0.5rem; }
@media (max-width: 768px) { .two-panel { grid-template-columns: 1fr; } .cart-panel { position: static; max-height: none; } }
```

- [ ] **Step 2: Verify manually** — no automated test for CSS. Visual verification during integration testing.

- [ ] **Step 3: Commit**

```bash
git add src/tablebuilder/service/templates/base.html
git commit -m "feat: add two-panel grid CSS for chat + cart layout"
```

### Task 13: Update `chat.html` for two-panel layout with cart

**Files:**
- Modify: `src/tablebuilder/service/templates/chat.html`

- [ ] **Step 1: Replace `chat.html` content**

```html
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

- [ ] **Step 2: Commit**

```bash
git add src/tablebuilder/service/templates/chat.html
git commit -m "feat: two-panel chat layout with data cart sidebar"
```

---

## Chunk 7: Integration Testing and Full Run Verification

### Task 14: Run all tests and fix any breakage

**Files:**
- All test files

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest --ignore=tests/test_integration.py --ignore=tests/test_http_integration.py --ignore=tests/test_chat_resolver_integration.py -v`
Expected: ALL PASS

- [ ] **Step 2: Fix any failing tests**

If tests fail, read the error output carefully and fix the root cause. Common issues:
- Old tests that mock `resolve()` with the old return format (flat dict with `clarification`/`confirmation` keys) need to be updated to the new format (`text` + `display_payloads` + `messages`)
- Old tests that check for `resolved_request_json` in session — this column is deprecated, proposals are now in `proposals_json`
- Import errors if `compare_datasets` isn't exported properly

- [ ] **Step 3: Run the full suite again to confirm**

Run: `uv run pytest --ignore=tests/test_integration.py --ignore=tests/test_http_integration.py --ignore=tests/test_chat_resolver_integration.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: update tests for new resolver format and cart model"
```

### Task 15: Manual smoke test with the web UI

- [ ] **Step 1: Start the service**

Run: `ANTHROPIC_API_KEY=$(cat ~/.anthropic/api_key) uv run uvicorn tablebuilder.service.app:app --reload`

- [ ] **Step 2: Open browser to `http://localhost:8000`**

- [ ] **Step 3: Register with ABS credentials**

- [ ] **Step 4: Test conversation flow**

Type: "I want to look at income distribution across different regions of Australia"

Verify:
- The bot responds conversationally (not with raw JSON)
- It proactively searches the dictionary
- Proposals appear in the cart sidebar
- Confidence scores are shown on cards
- Multiple-choice buttons appear when the bot uses `present_choices`

- [ ] **Step 5: Test cart interactions**

- Uncheck a proposal → card greys out
- Check it again → card restores
- Click "Fetch Selected" → jobs are queued
- Cart updates to show "Queued" status on confirmed proposals

- [ ] **Step 6: Verify logging**

Check the database for session events:
```bash
sqlite3 data/service.db "SELECT event_type, message FROM session_events ORDER BY timestamp LIMIT 20;"
```

- [ ] **Step 7: Commit any final fixes from smoke testing**

```bash
git add -A
git commit -m "fix: smoke test fixes for research assistant UI"
```
