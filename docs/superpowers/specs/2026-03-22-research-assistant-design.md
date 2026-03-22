# Research Assistant Bot — Design Spec

**Date**: 2026-03-22
**Status**: Approved
**Replaces**: Current `chat_resolver.py` transactional resolver

## Overview

Replace the transactional chat resolver with an AI-driven research assistant that acts as a senior data scientist helping researchers find and request ABS TableBuilder data. The Python layer becomes a thin tool executor; Claude drives the conversation using a rich persona and extended tool set.

The value proposition: **"Talk to someone who's read every variable in every ABS dataset."** No human has memorized 28,000 variables across 96 datasets. This thing has.

## Target User

Researchers who know what data is and are looking for ABS census/survey data. Not random people — they understand cross-tabulation, geographic levels, and research methodology. The bot meets them at their level.

## Persona

The system prompt defines a character, not a workflow:

- Senior research data scientist with deep ABS expertise
- Collegial, curious, opinionated when it matters
- Gets excited when spotting connections the researcher hasn't seen
- Knows when to suggest a better variable and when to just deliver
- Understands research methodology — can advise on denominators, confounders, geographic levels
- Stays on topic by character, not by rules: "That's outside my wheelhouse — I'm here to help you find the right data."
- Proactively searches when a topic is mentioned — doesn't wait to be told

### Guardrails

No prohibition lists. The persona IS the guardrail. A senior data scientist in a consultation doesn't give recipes, write poetry, or discuss the weather — not because there's a rule against it, but because that's not who they are. If the conversation drifts, the character gently steers it back.

## Tool Set

Claude gets 6 tools in two categories. It decides when and how to use them.

### Research Tools

| Tool | Input | Output | Purpose |
|------|-------|--------|---------|
| `search_dictionary` | `query: str, limit: int` | Ranked results: dataset, variable code, label, categories, summary | FTS5 search across 96 datasets, 28k+ variables. Already exists. |
| `get_dataset_variables` | `dataset_name: str` | Full variable tree: groups, variables, category counts, samples | Explore a specific dataset's structure. Already exists. |
| `compare_datasets` | `dataset_names: list[str]` | Side-by-side: which variables each has, overlap, gaps | Help when a research question could be answered by multiple datasets. New tool. |

### Display Tools

Display tools produce structured payloads that the UI renders. Claude gets a text confirmation back; the researcher sees a rich UI element.

| Tool | Input | Output to Claude | Output to UI | Purpose |
|------|-------|------------------|--------------|---------|
| `propose_table_request` | `dataset, rows, cols, wafers, match_confidence, clarity_confidence, rationale` | "Proposal #N stored, showing to researcher" | Card added to shopping cart | Propose a data pull with confidence scores |
| `present_choices` | `question, options: [{label, description}], allow_multiple: bool` | "Choices presented, waiting for selection" | Clickable buttons or radio/checkbox list | Structured multiple choice question |
| `show_session_summary` | (no input — reads session events) | Full event log as source material | Claude writes a polished research brief from the data | Generate exportable summary |

### Design decisions

- **No `queue_job` tool** — the shopping cart replaces this. The researcher controls when to fetch, not Claude.
- **No `send_message` tool** — Claude's natural text output IS the message.
- **No `set_confidence` tool** — confidence is a parameter on `propose_table_request`.
- **No `end_conversation` tool** — conversations end naturally.

## Confidence Scoring

Two-axis scoring on every proposal:

- **Dataset match (0-100)**: How well do the variables in this dataset cover what the researcher is asking about? Mechanical — based on search results and variable coverage.
- **Question clarity (0-100)**: Has the researcher been specific enough that we're confident this data will answer their question? Conversational — based on how much the researcher has specified.

Claude's instruction: if clarity is below 70, ask a follow-up before proposing. This naturally drives the conversation toward specificity.

Both scores displayed on the shopping cart card.

## UI: Two-Panel Layout

### Left Panel — Chat

The research conversation. Researcher and data scientist talking, exploring, searching. Rendered as chat bubbles. Multiple choice options rendered as clickable buttons inline. Session summary rendered as a formatted document.

### Right Panel — Shopping Cart

Every `propose_table_request` call adds a card:

```
┌───────────────────────────────────┐
│ [✓] Census 2021 — Income by SA2   │
│     Rows: INCP Total Income        │
│     Cols: STATE State/Territory     │
│     Match: 88%  Clarity: 75%       │
│                                     │
│ [✓] Census 2021 — Dwelling Costs   │
│     Rows: RNTD Weekly Rent         │
│     Cols: STATE State/Territory     │
│     Match: 82%  Clarity: 75%       │
│                                     │
│ [ ] Labour Force — Employment      │
│     (greyed out — unchecked)        │
│                                     │
│          [ Fetch Selected ]         │
└───────────────────────────────────┘
```

### Cart behavior

- Proposals land **checked by default** — Claude proposed it because it thinks it's useful
- Researcher can **uncheck** — card stays (greyed out), can be re-enabled
- Cards collapse to one-line summaries when the cart gets long, expand on click
- Cart scrolls independently from chat
- **"Fetch Selected"** queues all checked proposals as jobs in one batch
- Cart state (checked/unchecked) is visible to Claude as context — it can react to researcher's selections

## Session Model

### Multi-job conversations

A single session can produce multiple proposals and multiple jobs. The conversation is a funnel that accumulates data requests, not a one-shot resolve.

### Session state

| Field | Purpose |
|-------|---------|
| `conversation_history` | Full message list (exists as `messages_json`) |
| `proposals_json` | Array of proposals: id, table request, confidence scores, status (proposed/confirmed/rejected) |
| `research_question` | Claude's evolving understanding of the research intent |
| `job_ids` | List of job IDs linked to confirmed proposals |

### Flow example

1. Researcher: "I want to look at income and housing costs in regional Victoria"
2. Claude searches, finds variables, calls `propose_table_request` for income → card appears in cart (match: 82%, clarity: 55%)
3. Claude calls `present_choices`: "What geographic level?" → SA2 / SA3 / LGA buttons
4. Researcher clicks SA2
5. Claude updates thinking, calls `propose_table_request` for housing → second card (clarity now 85% for both)
6. Researcher checks both, clicks "Fetch Selected" → two jobs queued
7. Claude: "Both queued! Want me to put together a summary?"
8. Claude calls `show_session_summary` → polished brief

## Logging & Audit Trail

### session_events table

Every interaction produces a log entry:

| Event type | Captured data |
|------------|---------------|
| `user_message` | Raw text |
| `tool_call` | Tool name, full input parameters, timestamp |
| `tool_result` | Full result data, execution time |
| `assistant_message` | Claude's natural language response |
| `proposal_created` | Proposal ID, table request, confidence scores |
| `proposal_toggled` | Proposal ID, new checked state |
| `choices_presented` | Question, options |
| `choice_selected` | Selected option(s) |
| `jobs_queued` | List of job IDs, linked proposal IDs |

Same pattern as existing `job_events` table. Ordered by timestamp. Full session is replayable.

### Researcher export

`show_session_summary` feeds Claude the raw event log. Claude produces a polished brief:

- Research question as understood
- Datasets explored (why each was considered/rejected)
- Searches performed
- Variables selected and axis assignments
- Confidence scores at confirmation time
- Jobs queued with status

This is the "take-away document" — what the researcher walks away with.

### Analytics value

- Which datasets get requested most
- Where researchers get stuck (low clarity scores, many turns)
- How many turns to resolution
- Which search queries find nothing (gaps in the dictionary)

## Architecture

```
Researcher  ←→  Web UI (HTMX)  ←→  Routes  ←→  ChatResolver  ←→  Claude API
                 [chat | cart]         ↕              ↕
                                  ServiceDB      Tool Executor
                                  (sessions,     (dictionary.db,
                                   events,        proposals,
                                   jobs)          jobs)
```

### The resolve loop

1. Researcher sends message
2. Routes layer: log `user_message` event, append to history, call `resolver.resolve()`
3. Resolver loop (up to 10 rounds):
   - Send messages + tools to Claude
   - If tool_call → log it, execute, log result
   - If display tool → also collect display payload for UI
   - Feed result back to Claude, continue loop
   - If text response → log it, break
4. Routes layer: return Claude's text + any display payloads (proposals, choices)
5. UI renders text as chat, proposals as cart cards, choices as buttons

### Display tool dual return

When Claude calls a display tool:
1. Tool executor stores the data (proposal in session, etc.)
2. Returns text confirmation to Claude ("Proposal #1 stored")
3. Also flags a **display payload** sent to the UI

Claude doesn't render HTML. The UI gets structured objects to render.

## Files Changed

| File | Change |
|------|--------|
| `chat_resolver.py` | New system prompt, 3 new tools, display payload collection |
| `routes_chat.py` | Handle display payloads, multi-proposal confirm, cart state |
| `routes_web.py` | Render proposals as cards, choices as buttons, cart panel |
| `db.py` | Add `session_events` table, `proposals_json` + `research_question` columns on `chat_sessions` |
| `templates/chat.html` | Two-panel layout, cart component, choice buttons, summary renderer |

No new Python files. Everything extends what exists.

## End State

A successful conversation ends with:
- A shopping cart of checked proposals, each with high confidence scores
- A "Fetch Selected" click that queues all jobs
- An optional session summary the researcher can export
- A full audit trail replayable for debugging and demos
