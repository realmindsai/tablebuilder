# ABS Data Dictionary Explorer — Design

**Goal:** A GitHub Pages app that lets researchers search and browse 131 ABS TableBuilder datasets (36K variables, 317K categories) entirely client-side, with no backend.

**Target audience:** ABS researchers/analysts finding variable codes, plus curious explorers browsing what Census data is available.

## Architecture

Single-page app, no framework. Two search engines:

1. **Fuse.js** — instant typeahead against a pre-built JSON index (~3MB). Typo-tolerant fuzzy matching.
2. **sql.js (FTS5)** — full ranked search against the SQLite DB (49MB). BM25 relevance ranking, boolean/phrase queries.

Data loads in two phases: Fuse.js index first (typeahead ready in <1s), then sql.js + dictionary.db in background (full search ready in 2-5s). Both cached by the browser after first visit.

## Views (single page, hash routing)

1. **Search view** (landing) — search box with typeahead dropdown, results list below
2. **Dataset view** — expandable variable tree for one dataset, mirrors ABS UI structure
3. **Variable detail** — full category list, cross-reference showing which datasets share this variable code

## Visual Design (RMAI Brand)

- Background: `#FAF9F7` (Off White)
- Body text: `#1A1B25` (Core Black), Epilogue font (Google Fonts)
- Headings/accents: `#A77ACD` (Signature Purple)
- Interactive elements: `#A77ACD`, active state `#F26541` (Orange)
- Cards/panels: white, `#E7E7EA` borders
- Expanded groups: `#F1E8D7` (Oat) background
- Tables: header `#FAF9F7`, zebra `#FAF9F7`, borders `#E7E7EA`
- RMAI logo top-left

## File Structure

```
docs/
├── index.html
├── css/
│   └── style.css
├── js/
│   ├── app.js            (routing, UI rendering)
│   ├── search.js          (Fuse.js + sql.js integration)
│   └── db.js              (sql.js wrapper, DB loading)
├── data/
│   ├── dictionary.db      (49MB SQLite)
│   └── variables_index.json (3MB fuzzy index)
├── assets/
│   └── rmai_logo.svg
└── vendor/
    ├── sql-wasm.js
    ├── sql-wasm.wasm
    └── fuse.min.js
```

## Build Script

Python script (`scripts/build_pages.py`) that:
1. Copies `~/.tablebuilder/dictionary.db` → `docs/data/dictionary.db`
2. Generates `variables_index.json` from the DB (dataset_name, group_path, code, label, truncated categories)
3. Copies vendor libs (sql.js from CDN/local, Fuse.js)

No npm, no bundler. Just `uv run python scripts/build_pages.py`.

## Data Flow

```
First visit:
  1. Page loads (~50KB HTML/CSS/JS)
  2. variables_index.json loads (~3MB) → Fuse.js typeahead ready
  3. sql-wasm.wasm + dictionary.db load in background (~50MB total)
  4. Progress bar shows DB loading status
  5. Full FTS5 search becomes available

Returning visit:
  Browser cache serves all files instantly
```

## Key Decisions

- **No framework** — vanilla JS, keeps it simple and small
- **sql.js + Fuse.js hybrid** — fuzzy typeahead for discovery, FTS5 for precision
- **49MB shipped as-is** — modern connections handle this fine, browser caches it
- **GitHub Pages from /docs** — no separate gh-pages branch needed
- **RMAI brand** — Epilogue font, purple/oat/off-white palette, logo
