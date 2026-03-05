# ABS Data Dictionary Explorer

Search and browse 131 ABS TableBuilder datasets — 36,000 variables and 317,000 categories — entirely in your browser.

## Features

- **Fuzzy search** — typo-tolerant typeahead powered by Fuse.js
- **Ranked search** — FTS5 full-text search via sql.js (SQLite in WASM)
- **Browse** — expandable dataset trees mirroring the ABS TableBuilder structure
- **Cross-reference** — see which datasets share the same variable codes

## How It Works

The entire 49MB SQLite database loads client-side via sql.js. First visit downloads the data (cached by browser after that). No backend, no API keys, no ABS account needed.

## Rebuilding

To regenerate the static assets from a fresh dictionary database:

```bash
uv run python scripts/build_pages.py
```

Requires `~/.tablebuilder/dictionary.db` (built via `uv run tablebuilder dictionary --rebuild-db`).
