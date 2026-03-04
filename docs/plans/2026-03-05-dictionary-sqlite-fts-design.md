# Design: ABS Data Dictionary SQLite + FTS5 Search

## Problem

We have 96 non-Census ABS TableBuilder datasets extracted as JSON (28,561 variables, 256,578 categories). Currently stored as markdown and JSON cache files. Need a searchable index so Claude Code can find relevant datasets/variables when Doctor Dee asks questions about ABS data.

## Approach: SQLite + FTS5 + Generated Summaries

No embedding model or external API. Use SQLite's built-in FTS5 full-text search with programmatically generated natural-language summaries that provide synonym coverage.

## Database Schema

```sql
-- Core normalized tables
CREATE TABLE datasets (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    geographies_json TEXT DEFAULT '[]'
);

CREATE TABLE groups (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id),
    label TEXT NOT NULL,
    path TEXT NOT NULL  -- full hierarchy e.g. "Business > Characteristics"
);

CREATE TABLE variables (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    code TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL
);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    variable_id INTEGER NOT NULL REFERENCES variables(id),
    label TEXT NOT NULL
);

-- FTS5 search indexes
CREATE VIRTUAL TABLE datasets_fts USING fts5(
    name, summary, content='datasets', content_rowid='id'
);

CREATE VIRTUAL TABLE variables_fts USING fts5(
    dataset_name, group_path, code, label, categories_text, summary
);
```

## Summary Generation

Generated programmatically from structured JSON — no LLM call needed.

**Dataset summary** example:
> "Businesses in Australia (BLADE), 2001-02 to 2023-24. Covers business demographics, industry classification (ANZSIC 2006), employee headcount, financial metrics including revenue, GST, capital purchases, exports. 307 variables across 112 groups."

**Variable summary** example:
> "Age of Business (Derived) — business characteristic with 10 categories: 0 Years, 1 Year, 2 Years, ... 16+ Years. Part of Business > Characteristics group in BLADE dataset."

Category labels provide natural synonym coverage (e.g., "Melbourne" in geographic categories, "Revenue" in financial categories).

## Query Interface

Module: `src/tablebuilder/dictionary_db.py`

Functions:
- `build_db(cache_dir, db_path)` — load JSON cache, create tables, generate summaries, populate FTS5
- `search(db_path, query, limit=20)` — FTS5 search returning ranked results
- `get_dataset(db_path, name)` — full dataset details
- `get_variables_by_code(db_path, code)` — structured lookup

Database location: `~/.tablebuilder/dictionary.db`

## Data Flow

```
JSON cache (~/.tablebuilder/dict_cache/*.json)
    ↓ build_db()
SQLite (~/.tablebuilder/dictionary.db)
    ↓ search()
Ranked results → Claude Code context
```

Rebuild is idempotent — drops and recreates all tables from JSON cache. Takes <5 seconds. Triggered by:
- `tablebuilder dictionary --rebuild-db` flag
- Automatically after batch extraction completes

## CLI Integration

- `tablebuilder search "business income Melbourne"` — new CLI command wrapping search()
- `tablebuilder dictionary --rebuild-db` — new flag on existing command

## Claude Code Usage

In future sessions, search via:
```bash
sqlite3 ~/.tablebuilder/dictionary.db "SELECT * FROM variables_fts WHERE variables_fts MATCH 'business income' LIMIT 10;"
```

No MCP server, no embeddings, no external dependencies. Just sqlite3.

## Data Volume

- 96 datasets, 5,123 groups, 28,561 variables, 256,578 categories
- JSON cache: 22.7 MB
- Expected SQLite size: ~5-10 MB
