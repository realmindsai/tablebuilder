# GitHub Pages Dictionary Explorer — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a static GitHub Pages app that lets researchers search and browse 131 ABS TableBuilder datasets (36K variables, 317K categories) entirely client-side.

**Architecture:** Single-page vanilla JS app with hash routing. Fuse.js provides fuzzy typeahead against a 6MB JSON index. sql.js loads the 49MB SQLite dictionary.db for FTS5 ranked search. Both cached by browser after first visit. RMAI branded.

**Tech Stack:** Vanilla JS, sql.js (WASM SQLite), Fuse.js, Epilogue font (Google Fonts), no build toolchain

---

### Task 1: Build script — generate static assets from dictionary DB

**Files:**
- Create: `scripts/build_pages.py`
- Test: manual verification

This script is the foundation — it produces the `docs/` directory that GitHub Pages serves.

**Step 1: Create the build script**

```python
# ABOUTME: Build script for the GitHub Pages dictionary explorer.
# ABOUTME: Generates static assets from the SQLite dictionary database.

import json
import shutil
import sqlite3
from pathlib import Path

import click


REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs" / "explorer"
DATA_DIR = DOCS_DIR / "data"
VENDOR_DIR = DOCS_DIR / "vendor"
ASSETS_DIR = DOCS_DIR / "assets"
DB_SOURCE = Path.home() / ".tablebuilder" / "dictionary.db"
LOGO_SOURCE = Path.home() / ".claude" / "skills" / "rmai-brand-guidelines" / "assets" / "final_logo.svg"


@click.command()
@click.option("--db", default=str(DB_SOURCE), help="Path to dictionary.db")
def build(db):
    """Build the GitHub Pages explorer from the dictionary database."""
    db_path = Path(db)
    if not db_path.exists():
        click.echo(f"Error: database not found at {db_path}", err=True)
        raise SystemExit(1)

    # Create directory structure
    for d in [DATA_DIR, VENDOR_DIR, ASSETS_DIR, DOCS_DIR / "css", DOCS_DIR / "js"]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy database
    click.echo(f"Copying dictionary.db ({db_path.stat().st_size // 1024 // 1024}MB)...")
    shutil.copy2(db_path, DATA_DIR / "dictionary.db")

    # Generate Fuse.js index
    click.echo("Generating variables index for fuzzy search...")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT dataset_name, group_path, code, label, "
        "substr(categories_text, 1, 200) as categories_preview "
        "FROM variables_fts"
    ).fetchall()
    index = [dict(r) for r in rows]
    conn.close()

    index_path = DATA_DIR / "variables_index.json"
    index_path.write_text(json.dumps(index, separators=(",", ":")))
    index_size = index_path.stat().st_size / 1024 / 1024
    click.echo(f"  {len(index)} variables, {index_size:.1f}MB")

    # Generate datasets list (small, for browse view)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    datasets = conn.execute(
        "SELECT name, geographies_json, summary FROM datasets ORDER BY name"
    ).fetchall()
    ds_list = []
    for ds in datasets:
        ds_list.append({
            "name": ds["name"],
            "geographies": json.loads(ds["geographies_json"]),
            "summary": ds["summary"],
        })
    conn.close()
    (DATA_DIR / "datasets.json").write_text(json.dumps(ds_list, separators=(",", ":")))
    click.echo(f"  {len(ds_list)} datasets")

    # Copy logo
    if LOGO_SOURCE.exists():
        shutil.copy2(LOGO_SOURCE, ASSETS_DIR / "rmai_logo.svg")
        click.echo("Copied RMAI logo")
    else:
        click.echo(f"Warning: logo not found at {LOGO_SOURCE}", err=True)

    click.echo(f"Done! Static site ready at {DOCS_DIR}")


if __name__ == "__main__":
    build()
```

**Step 2: Run the build script**

Run: `uv run python scripts/build_pages.py`
Expected: `docs/explorer/data/dictionary.db`, `docs/explorer/data/variables_index.json`, `docs/explorer/data/datasets.json`, `docs/explorer/assets/rmai_logo.svg` all created.

**Step 3: Verify outputs**

Run: `ls -lh docs/explorer/data/ && wc -c docs/explorer/data/variables_index.json`
Expected: dictionary.db ~49MB, variables_index.json ~6MB, datasets.json ~100KB

**Step 4: Commit**

```bash
git add scripts/build_pages.py
git commit -m "feat: add build script for GitHub Pages explorer"
```

---

### Task 2: Vendor dependencies — sql.js and Fuse.js

**Files:**
- Modify: `scripts/build_pages.py`

Download sql.js and Fuse.js into `docs/explorer/vendor/` during build.

**Step 1: Add vendor download to build script**

Add before the "Done!" message in `build()`:

```python
    # Download vendor dependencies
    import urllib.request

    vendors = {
        "sql-wasm.js": "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.11.0/sql-wasm.js",
        "sql-wasm.wasm": "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.11.0/sql-wasm.wasm",
        "fuse.min.js": "https://cdnjs.cloudflare.com/ajax/libs/fuse.js/7.0.0/fuse.min.js",
    }

    for filename, url in vendors.items():
        dest = VENDOR_DIR / filename
        if not dest.exists():
            click.echo(f"Downloading {filename}...")
            urllib.request.urlretrieve(url, dest)
        else:
            click.echo(f"  {filename} already exists, skipping")
```

**Step 2: Run build again**

Run: `uv run python scripts/build_pages.py`
Expected: vendor files downloaded to `docs/explorer/vendor/`

**Step 3: Verify**

Run: `ls -lh docs/explorer/vendor/`
Expected: `sql-wasm.js` (~80KB), `sql-wasm.wasm` (~1MB), `fuse.min.js` (~25KB)

**Step 4: Commit**

```bash
git add scripts/build_pages.py
git commit -m "feat: add vendor dependency download to build script"
```

---

### Task 3: HTML skeleton and CSS — RMAI branded layout

**Files:**
- Create: `docs/explorer/index.html`
- Create: `docs/explorer/css/style.css`

**Step 1: Create index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ABS Data Dictionary Explorer</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Epilogue:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <header>
        <div class="header-inner">
            <a href="#" class="logo-link">
                <img src="assets/rmai_logo.svg" alt="RMAI" class="logo">
            </a>
            <div class="header-text">
                <h1>ABS Data Dictionary Explorer</h1>
                <p class="subtitle">Search 131 datasets, 36,000 variables, 317,000 categories</p>
            </div>
        </div>
    </header>

    <main>
        <section id="search-section">
            <div class="search-container">
                <input type="text" id="search-input"
                       placeholder="Search variables, codes, categories..."
                       autocomplete="off" autofocus>
                <div id="typeahead-dropdown" class="typeahead-dropdown hidden"></div>
            </div>
            <div id="search-status" class="search-status"></div>
            <div id="search-results" class="results-list"></div>
        </section>

        <section id="dataset-section" class="hidden">
            <button id="back-btn" class="back-btn">&larr; Back to search</button>
            <div id="dataset-detail"></div>
        </section>

        <section id="variable-section" class="hidden">
            <button id="var-back-btn" class="back-btn">&larr; Back</button>
            <div id="variable-detail"></div>
        </section>
    </main>

    <footer>
        <p>Data extracted from <a href="https://tablebuilder.abs.gov.au" target="_blank" rel="noopener">ABS TableBuilder</a>. Not affiliated with the Australian Bureau of Statistics.</p>
        <p class="footer-brand">Built by Real Minds Artificial Intelligence</p>
    </footer>

    <div id="loading-overlay" class="loading-overlay">
        <div class="loading-content">
            <p>Loading dictionary database...</p>
            <div class="progress-bar"><div id="progress-fill" class="progress-fill"></div></div>
            <p id="loading-status" class="loading-status">Preparing search index...</p>
        </div>
    </div>

    <script src="vendor/fuse.min.js"></script>
    <script src="vendor/sql-wasm.js"></script>
    <script src="js/db.js"></script>
    <script src="js/search.js"></script>
    <script src="js/app.js"></script>
</body>
</html>
```

**Step 2: Create style.css**

```css
/* ABOUTME: RMAI-branded styles for the ABS Dictionary Explorer. */
/* ABOUTME: Uses Epilogue font, purple/oat/off-white palette. */

:root {
    --core-black: #1A1B25;
    --slate-black: #373841;
    --purple: #A77ACD;
    --purple-light: #C9A8E4;
    --orange: #F26541;
    --off-white: #FAF9F7;
    --oat: #F1E8D7;
    --border: #E7E7EA;
    --slate-gray: #8D8D92;
    --white: #FFFFFF;
    --font: 'Epilogue', Inter, 'SF Pro', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: var(--font);
    color: var(--core-black);
    background: var(--off-white);
    line-height: 1.45;
    font-size: 15px;
}

/* Header */
header {
    background: var(--white);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
}
.header-inner {
    max-width: 960px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    gap: 16px;
}
.logo-link { display: flex; }
.logo { height: 40px; width: auto; }
.header-text h1 {
    font-size: 22px;
    font-weight: 700;
    color: var(--core-black);
}
.subtitle {
    font-size: 13px;
    color: var(--slate-gray);
    margin-top: 2px;
}

/* Main content */
main {
    max-width: 960px;
    margin: 0 auto;
    padding: 24px;
    min-height: calc(100vh - 200px);
}

/* Search */
.search-container { position: relative; }
#search-input {
    width: 100%;
    padding: 14px 18px;
    font-size: 16px;
    font-family: var(--font);
    border: 2px solid var(--border);
    border-radius: 8px;
    background: var(--white);
    color: var(--core-black);
    outline: none;
    transition: border-color 0.15s;
}
#search-input:focus { border-color: var(--purple); }
#search-input::placeholder { color: var(--slate-gray); }

.search-status {
    padding: 8px 0;
    font-size: 13px;
    color: var(--slate-gray);
}

/* Typeahead */
.typeahead-dropdown {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: var(--white);
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 8px 8px;
    max-height: 320px;
    overflow-y: auto;
    z-index: 10;
    box-shadow: 0 4px 12px rgba(26, 27, 37, 0.08);
}
.typeahead-item {
    padding: 10px 18px;
    cursor: pointer;
    border-bottom: 1px solid var(--border);
    font-size: 14px;
}
.typeahead-item:last-child { border-bottom: none; }
.typeahead-item:hover, .typeahead-item.active { background: var(--oat); }
.typeahead-item .item-label { font-weight: 600; }
.typeahead-item .item-code {
    color: var(--purple);
    font-size: 12px;
    margin-left: 6px;
}
.typeahead-item .item-dataset {
    font-size: 12px;
    color: var(--slate-gray);
    display: block;
    margin-top: 2px;
}

/* Results */
.results-list { margin-top: 8px; }
.result-card {
    background: var(--white);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 8px;
    cursor: pointer;
    transition: border-color 0.15s;
}
.result-card:hover { border-color: var(--purple); }
.result-label { font-weight: 600; font-size: 15px; }
.result-code { color: var(--purple); font-size: 13px; margin-left: 6px; }
.result-dataset { font-size: 13px; color: var(--slate-gray); margin-top: 4px; }
.result-group { font-size: 12px; color: var(--slate-gray); }
.result-categories {
    font-size: 12px;
    color: var(--slate-black);
    margin-top: 6px;
    line-height: 1.35;
}

/* Dataset view */
.dataset-header {
    margin-bottom: 20px;
}
.dataset-header h2 {
    font-size: 20px;
    font-weight: 700;
    color: var(--core-black);
}
.dataset-summary {
    font-size: 13px;
    color: var(--slate-gray);
    margin-top: 6px;
}
.dataset-geographies {
    margin-top: 8px;
    font-size: 13px;
}
.dataset-geographies span {
    display: inline-block;
    background: var(--oat);
    padding: 2px 8px;
    border-radius: 4px;
    margin: 2px 4px 2px 0;
    font-size: 12px;
}
.group-section {
    margin-bottom: 12px;
}
.group-header {
    padding: 10px 14px;
    background: var(--oat);
    border-radius: 6px;
    cursor: pointer;
    font-weight: 600;
    font-size: 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    user-select: none;
}
.group-header:hover { background: #EBE0CC; }
.group-header .toggle { font-size: 12px; color: var(--slate-gray); }
.group-body { padding: 8px 0 0 14px; }
.variable-row {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    font-size: 14px;
    transition: background 0.1s;
}
.variable-row:hover { background: var(--off-white); }
.variable-row:last-child { border-bottom: none; }
.variable-row .var-code { color: var(--purple); font-size: 12px; margin-right: 8px; }

/* Variable detail view */
.var-detail-header h2 { font-size: 20px; font-weight: 700; }
.var-detail-header .var-detail-code { color: var(--purple); font-weight: 600; }
.var-detail-meta { font-size: 13px; color: var(--slate-gray); margin-top: 4px; }
.categories-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 6px;
    margin-top: 12px;
}
.category-chip {
    background: var(--white);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 13px;
}
.cross-ref {
    margin-top: 20px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
}
.cross-ref h3 { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.cross-ref-item {
    padding: 6px 0;
    font-size: 13px;
    color: var(--purple);
    cursor: pointer;
}
.cross-ref-item:hover { text-decoration: underline; }

/* Back button */
.back-btn {
    font-family: var(--font);
    font-size: 14px;
    color: var(--purple);
    background: none;
    border: none;
    cursor: pointer;
    padding: 8px 0;
    margin-bottom: 12px;
}
.back-btn:hover { text-decoration: underline; }

/* Browse section (dataset list on landing page) */
.browse-header {
    margin-top: 32px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
}
.browse-header h2 {
    font-size: 18px;
    font-weight: 700;
    margin-bottom: 12px;
}
.dataset-list-item {
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: 6px;
    margin-bottom: 6px;
    background: var(--white);
    cursor: pointer;
    font-size: 14px;
    transition: border-color 0.15s;
}
.dataset-list-item:hover { border-color: var(--purple); }
.dataset-list-item .ds-name { font-weight: 600; }
.dataset-list-item .ds-summary {
    font-size: 12px;
    color: var(--slate-gray);
    margin-top: 3px;
}

/* Loading overlay */
.loading-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(250, 249, 247, 0.95);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
}
.loading-content { text-align: center; }
.loading-content p { font-size: 15px; margin-bottom: 12px; }
.progress-bar {
    width: 300px;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
    margin: 0 auto;
}
.progress-fill {
    height: 100%;
    background: var(--purple);
    border-radius: 3px;
    width: 0%;
    transition: width 0.3s;
}
.loading-status { font-size: 12px; color: var(--slate-gray); }

/* Utilities */
.hidden { display: none !important; }

/* Footer */
footer {
    max-width: 960px;
    margin: 0 auto;
    padding: 20px 24px;
    border-top: 1px solid var(--border);
    font-size: 12px;
    color: var(--slate-gray);
}
footer a { color: var(--purple); }
.footer-brand { margin-top: 4px; }

/* Responsive */
@media (max-width: 640px) {
    .header-inner { flex-direction: column; align-items: flex-start; gap: 8px; }
    .header-text h1 { font-size: 18px; }
    main { padding: 16px; }
    #search-input { font-size: 15px; padding: 12px 14px; }
    .categories-grid { grid-template-columns: 1fr; }
}
```

**Step 3: Verify the page loads**

Run: `open docs/explorer/index.html` (or use a local server)
Expected: RMAI-branded page with search box, loading overlay visible, no JS errors.

**Step 4: Commit**

```bash
git add docs/explorer/index.html docs/explorer/css/style.css
git commit -m "feat: add HTML skeleton and RMAI-branded CSS"
```

---

### Task 4: db.js — SQLite database loader with progress

**Files:**
- Create: `docs/explorer/js/db.js`

Wraps sql.js. Loads the 49MB database with XMLHttpRequest for progress events. Exposes a promise-based query API.

**Step 1: Create db.js**

```javascript
// ABOUTME: SQLite database loader using sql.js (WASM).
// ABOUTME: Loads dictionary.db with progress tracking, exposes query API.

const DictDB = (() => {
    let db = null;
    let ready = false;

    async function load(onProgress) {
        const sqlPromise = initSqlJs({
            locateFile: file => `vendor/${file}`
        });

        const dbData = await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open("GET", "data/dictionary.db", true);
            xhr.responseType = "arraybuffer";
            xhr.onprogress = (e) => {
                if (e.lengthComputable && onProgress) {
                    onProgress(e.loaded / e.total);
                }
            };
            xhr.onload = () => {
                if (xhr.status === 200) resolve(new Uint8Array(xhr.response));
                else reject(new Error(`Failed to load DB: ${xhr.status}`));
            };
            xhr.onerror = () => reject(new Error("Network error loading DB"));
            xhr.send();
        });

        const SQL = await sqlPromise;
        db = new SQL.Database(dbData);
        ready = true;
    }

    function isReady() { return ready; }

    function query(sql, params) {
        if (!db) throw new Error("Database not loaded");
        const stmt = db.prepare(sql);
        if (params) stmt.bind(params);
        const results = [];
        while (stmt.step()) {
            results.push(stmt.getAsObject());
        }
        stmt.free();
        return results;
    }

    function searchFTS(queryText, limit = 30) {
        if (!db) return [];
        try {
            return query(
                `SELECT dataset_name, group_path, code, label, categories_text
                 FROM variables_fts
                 WHERE variables_fts MATCH ?
                 ORDER BY rank LIMIT ?`,
                [queryText, limit]
            );
        } catch (e) {
            // FTS5 syntax error (unbalanced quotes, etc) — fall back to prefix
            const escaped = queryText.replace(/['"]/g, "");
            if (!escaped) return [];
            try {
                return query(
                    `SELECT dataset_name, group_path, code, label, categories_text
                     FROM variables_fts
                     WHERE variables_fts MATCH ?
                     ORDER BY rank LIMIT ?`,
                    [`"${escaped}"*`, limit]
                );
            } catch (_) {
                return [];
            }
        }
    }

    function getDataset(name) {
        if (!db) return null;
        const ds = query(
            "SELECT id, name, geographies_json, summary FROM datasets WHERE name = ?",
            [name]
        );
        if (!ds.length) return null;

        const d = ds[0];
        const groups = query(
            "SELECT id, path FROM groups WHERE dataset_id = ? ORDER BY path",
            [d.id]
        );

        const result = {
            name: d.name,
            geographies: JSON.parse(d.geographies_json || "[]"),
            summary: d.summary,
            groups: []
        };

        for (const grp of groups) {
            const vars = query(
                "SELECT id, code, label FROM variables WHERE group_id = ? ORDER BY label",
                [grp.id]
            );
            const groupData = { path: grp.path, variables: [] };
            for (const v of vars) {
                const cats = query(
                    "SELECT label FROM categories WHERE variable_id = ? ORDER BY label",
                    [v.id]
                );
                groupData.variables.push({
                    id: v.id,
                    code: v.code,
                    label: v.label,
                    categories: cats.map(c => c.label)
                });
            }
            result.groups.push(groupData);
        }
        return result;
    }

    function getVariablesByCode(code) {
        if (!db) return [];
        return query(
            `SELECT v.id, v.code, v.label, d.name as dataset_name, g.path as group_path
             FROM variables v
             JOIN groups g ON v.group_id = g.id
             JOIN datasets d ON g.dataset_id = d.id
             WHERE v.code = ? ORDER BY d.name`,
            [code]
        );
    }

    return { load, isReady, query, searchFTS, getDataset, getVariablesByCode };
})();
```

**Step 2: Verify it loads**

Open browser console on `index.html`, run:
```javascript
DictDB.load(p => console.log(Math.round(p * 100) + '%')).then(() => console.log('ready', DictDB.searchFTS('sex')))
```
Expected: Progress percentages, then "ready" with search results array.

**Step 3: Commit**

```bash
git add docs/explorer/js/db.js
git commit -m "feat: add sql.js database loader with progress"
```

---

### Task 5: search.js — Fuse.js typeahead + FTS5 integration

**Files:**
- Create: `docs/explorer/js/search.js`

Manages both search engines: Fuse.js for instant typeahead, FTS5 for ranked results.

**Step 1: Create search.js**

```javascript
// ABOUTME: Dual search engine — Fuse.js for fuzzy typeahead, sql.js FTS5 for ranked results.
// ABOUTME: Loads variables_index.json for Fuse, delegates to DictDB for FTS5.

const Search = (() => {
    let fuse = null;
    let indexReady = false;

    async function loadIndex() {
        const resp = await fetch("data/variables_index.json");
        const data = await resp.json();
        fuse = new Fuse(data, {
            keys: [
                { name: "label", weight: 3 },
                { name: "code", weight: 2 },
                { name: "dataset_name", weight: 1 },
                { name: "categories_preview", weight: 0.5 },
                { name: "group_path", weight: 0.5 }
            ],
            threshold: 0.35,
            distance: 100,
            includeScore: true,
            minMatchCharLength: 2,
            limit: 10
        });
        indexReady = true;
    }

    function isIndexReady() { return indexReady; }

    function fuzzySearch(query, limit = 8) {
        if (!fuse || !query || query.length < 2) return [];
        return fuse.search(query, { limit }).map(r => r.item);
    }

    function fullSearch(query, limit = 30) {
        if (DictDB.isReady()) {
            return DictDB.searchFTS(query, limit);
        }
        // Fallback to Fuse if DB not loaded yet
        if (fuse) {
            return fuse.search(query, { limit }).map(r => r.item);
        }
        return [];
    }

    return { loadIndex, isIndexReady, fuzzySearch, fullSearch };
})();
```

**Step 2: Verify**

Console test:
```javascript
Search.loadIndex().then(() => console.log(Search.fuzzySearch('remotness')))
```
Expected: Results including "Remoteness Areas" despite the typo.

**Step 3: Commit**

```bash
git add docs/explorer/js/search.js
git commit -m "feat: add Fuse.js + FTS5 dual search engine"
```

---

### Task 6: app.js — Main application logic and routing

**Files:**
- Create: `docs/explorer/js/app.js`

Ties everything together: hash routing, event handlers, view rendering, loading sequence.

**Step 1: Create app.js**

```javascript
// ABOUTME: Main application logic for the ABS Dictionary Explorer.
// ABOUTME: Handles routing, UI rendering, search interaction, and data loading.

const App = (() => {
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    let datasets = [];
    let debounceTimer = null;
    let selectedTypeaheadIdx = -1;

    // --- Loading ---
    async function init() {
        // Phase 1: Load Fuse index (fast, enables typeahead)
        updateLoadingStatus("Loading search index...");
        try {
            await Search.loadIndex();
            updateLoadingStatus("Search ready! Loading full database...");
        } catch (e) {
            updateLoadingStatus("Warning: fuzzy search unavailable");
        }

        // Load datasets list for browse view
        try {
            const resp = await fetch("data/datasets.json");
            datasets = await resp.json();
        } catch (_) {}

        // Phase 2: Load full SQLite DB (slow, enables FTS5)
        try {
            await DictDB.load((progress) => {
                const pct = Math.round(progress * 100);
                $("#progress-fill").style.width = pct + "%";
                updateLoadingStatus(`Loading database... ${pct}%`);
            });
            updateLoadingStatus("Ready!");
        } catch (e) {
            updateLoadingStatus("Database load failed — using fuzzy search only");
        }

        // Hide loading overlay
        setTimeout(() => {
            $("#loading-overlay").classList.add("hidden");
        }, 300);

        // Set up event listeners
        setupSearch();
        setupRouting();

        // Render initial view
        handleRoute();
        renderBrowseList();
    }

    function updateLoadingStatus(msg) {
        const el = $("#loading-status");
        if (el) el.textContent = msg;
    }

    // --- Routing ---
    function setupRouting() {
        window.addEventListener("hashchange", handleRoute);
    }

    function handleRoute() {
        const hash = location.hash || "#";
        if (hash.startsWith("#dataset/")) {
            const name = decodeURIComponent(hash.slice(9));
            showDatasetView(name);
        } else if (hash.startsWith("#variable/")) {
            const parts = hash.slice(10).split("/");
            const code = decodeURIComponent(parts[0]);
            const dataset = parts[1] ? decodeURIComponent(parts[1]) : null;
            showVariableView(code, dataset);
        } else {
            showSearchView();
        }
    }

    function showSearchView() {
        $("#search-section").classList.remove("hidden");
        $("#dataset-section").classList.add("hidden");
        $("#variable-section").classList.add("hidden");
    }

    function showDatasetView(name) {
        $("#search-section").classList.add("hidden");
        $("#dataset-section").classList.remove("hidden");
        $("#variable-section").classList.add("hidden");
        renderDataset(name);
    }

    function showVariableView(code, dataset) {
        $("#search-section").classList.add("hidden");
        $("#dataset-section").classList.add("hidden");
        $("#variable-section").classList.remove("hidden");
        renderVariable(code, dataset);
    }

    // --- Search ---
    function setupSearch() {
        const input = $("#search-input");
        const dropdown = $("#typeahead-dropdown");

        input.addEventListener("input", () => {
            clearTimeout(debounceTimer);
            const q = input.value.trim();
            if (q.length < 2) {
                hideTypeahead();
                clearResults();
                return;
            }
            // Instant typeahead
            showTypeahead(Search.fuzzySearch(q));
            // Debounced full search
            debounceTimer = setTimeout(() => {
                renderSearchResults(Search.fullSearch(q));
            }, 300);
        });

        input.addEventListener("keydown", (e) => {
            const items = $$(".typeahead-item");
            if (e.key === "ArrowDown") {
                e.preventDefault();
                selectedTypeaheadIdx = Math.min(selectedTypeaheadIdx + 1, items.length - 1);
                updateTypeaheadSelection(items);
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                selectedTypeaheadIdx = Math.max(selectedTypeaheadIdx - 1, -1);
                updateTypeaheadSelection(items);
            } else if (e.key === "Enter") {
                e.preventDefault();
                if (selectedTypeaheadIdx >= 0 && items[selectedTypeaheadIdx]) {
                    items[selectedTypeaheadIdx].click();
                } else {
                    hideTypeahead();
                    renderSearchResults(Search.fullSearch(input.value.trim()));
                }
            } else if (e.key === "Escape") {
                hideTypeahead();
            }
        });

        // Close typeahead when clicking outside
        document.addEventListener("click", (e) => {
            if (!e.target.closest(".search-container")) hideTypeahead();
        });

        // Back buttons
        $("#back-btn").addEventListener("click", () => { location.hash = "#"; });
        $("#var-back-btn").addEventListener("click", () => { history.back(); });
    }

    function showTypeahead(results) {
        const dropdown = $("#typeahead-dropdown");
        selectedTypeaheadIdx = -1;
        if (!results.length) {
            hideTypeahead();
            return;
        }
        dropdown.innerHTML = results.map((r, i) => `
            <div class="typeahead-item" data-index="${i}"
                 data-code="${esc(r.code)}" data-dataset="${esc(r.dataset_name)}">
                <span class="item-label">${esc(r.label)}</span>
                ${r.code ? `<span class="item-code">${esc(r.code)}</span>` : ""}
                <span class="item-dataset">${esc(r.dataset_name)} &rsaquo; ${esc(r.group_path)}</span>
            </div>
        `).join("");
        dropdown.classList.remove("hidden");

        dropdown.querySelectorAll(".typeahead-item").forEach(item => {
            item.addEventListener("click", () => {
                const code = item.dataset.code;
                const dataset = item.dataset.dataset;
                if (code) {
                    location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(dataset)}`;
                } else {
                    location.hash = `#dataset/${encodeURIComponent(dataset)}`;
                }
                hideTypeahead();
            });
        });
    }

    function hideTypeahead() {
        $("#typeahead-dropdown").classList.add("hidden");
        selectedTypeaheadIdx = -1;
    }

    function updateTypeaheadSelection(items) {
        items.forEach((el, i) => {
            el.classList.toggle("active", i === selectedTypeaheadIdx);
        });
    }

    function clearResults() {
        $("#search-results").innerHTML = "";
        $("#search-status").textContent = "";
    }

    // --- Rendering ---
    function renderSearchResults(results) {
        const container = $("#search-results");
        const status = $("#search-status");

        if (!results.length) {
            status.textContent = "No results found.";
            container.innerHTML = "";
            return;
        }

        status.textContent = `${results.length} result${results.length === 1 ? "" : "s"}`;
        container.innerHTML = results.map(r => `
            <div class="result-card" data-code="${esc(r.code)}" data-dataset="${esc(r.dataset_name)}">
                <div>
                    <span class="result-label">${esc(r.label)}</span>
                    ${r.code ? `<span class="result-code">${esc(r.code)}</span>` : ""}
                </div>
                <div class="result-dataset">${esc(r.dataset_name)}</div>
                <div class="result-group">${esc(r.group_path)}</div>
                ${r.categories_text ? `<div class="result-categories">${esc(truncate(r.categories_text, 150))}</div>` : ""}
            </div>
        `).join("");

        container.querySelectorAll(".result-card").forEach(card => {
            card.addEventListener("click", () => {
                const code = card.dataset.code;
                const dataset = card.dataset.dataset;
                if (code) {
                    location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(dataset)}`;
                } else {
                    location.hash = `#dataset/${encodeURIComponent(dataset)}`;
                }
            });
        });
    }

    function renderBrowseList() {
        // Add browse section below search results
        const main = $("main");
        let browseSection = $("#browse-section");
        if (!browseSection) {
            browseSection = document.createElement("section");
            browseSection.id = "browse-section";
            browseSection.className = "browse-header";
            main.appendChild(browseSection);
        }

        browseSection.innerHTML = `
            <h2>Browse All Datasets (${datasets.length})</h2>
            ${datasets.map(ds => `
                <div class="dataset-list-item" data-name="${esc(ds.name)}">
                    <div class="ds-name">${esc(ds.name)}</div>
                    <div class="ds-summary">${esc(truncate(ds.summary, 120))}</div>
                </div>
            `).join("")}
        `;

        browseSection.querySelectorAll(".dataset-list-item").forEach(item => {
            item.addEventListener("click", () => {
                location.hash = `#dataset/${encodeURIComponent(item.dataset.name)}`;
            });
        });
    }

    function renderDataset(name) {
        const container = $("#dataset-detail");
        const ds = DictDB.isReady() ? DictDB.getDataset(name) : null;

        if (!ds) {
            container.innerHTML = `<p>Dataset "${esc(name)}" not found. Database may still be loading.</p>`;
            return;
        }

        const geoHtml = ds.geographies.length
            ? `<div class="dataset-geographies">
                 <strong>Geographies:</strong>
                 ${ds.geographies.map(g => `<span>${esc(g)}</span>`).join("")}
               </div>`
            : "";

        container.innerHTML = `
            <div class="dataset-header">
                <h2>${esc(ds.name)}</h2>
                <div class="dataset-summary">${esc(ds.summary)}</div>
                ${geoHtml}
            </div>
            ${ds.groups.map(grp => `
                <div class="group-section">
                    <div class="group-header" data-expanded="false">
                        <span>${esc(grp.path)} (${grp.variables.length})</span>
                        <span class="toggle">&#x25B6;</span>
                    </div>
                    <div class="group-body hidden">
                        ${grp.variables.map(v => `
                            <div class="variable-row"
                                 data-code="${esc(v.code)}" data-dataset="${esc(name)}">
                                ${v.code ? `<span class="var-code">${esc(v.code)}</span>` : ""}
                                ${esc(v.label)}
                                <span style="color:var(--slate-gray);font-size:12px;margin-left:4px;">(${v.categories.length})</span>
                            </div>
                        `).join("")}
                    </div>
                </div>
            `).join("")}
        `;

        // Group expand/collapse
        container.querySelectorAll(".group-header").forEach(header => {
            header.addEventListener("click", () => {
                const body = header.nextElementSibling;
                const toggle = header.querySelector(".toggle");
                const expanded = header.dataset.expanded === "true";
                body.classList.toggle("hidden", expanded);
                header.dataset.expanded = expanded ? "false" : "true";
                toggle.innerHTML = expanded ? "&#x25B6;" : "&#x25BC;";
            });
        });

        // Variable click
        container.querySelectorAll(".variable-row").forEach(row => {
            row.addEventListener("click", () => {
                const code = row.dataset.code;
                const dataset = row.dataset.dataset;
                if (code) {
                    location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(dataset)}`;
                }
            });
        });
    }

    function renderVariable(code, datasetName) {
        const container = $("#variable-detail");

        if (!DictDB.isReady()) {
            container.innerHTML = "<p>Database still loading...</p>";
            return;
        }

        // Get the specific variable from the dataset context
        let variable = null;
        if (datasetName) {
            const ds = DictDB.getDataset(datasetName);
            if (ds) {
                for (const grp of ds.groups) {
                    for (const v of grp.variables) {
                        if (v.code === code) {
                            variable = { ...v, group_path: grp.path, dataset_name: datasetName };
                            break;
                        }
                    }
                    if (variable) break;
                }
            }
        }

        // Cross-reference: find same code in other datasets
        const crossRefs = DictDB.getVariablesByCode(code);

        if (!variable && crossRefs.length) {
            variable = crossRefs[0];
            // Load categories for this variable
            const cats = DictDB.query(
                "SELECT label FROM categories WHERE variable_id = ? ORDER BY label",
                [variable.id]
            );
            variable.categories = cats.map(c => c.label);
        }

        if (!variable) {
            container.innerHTML = `<p>Variable "${esc(code)}" not found.</p>`;
            return;
        }

        const crossRefHtml = crossRefs.length > 1
            ? `<div class="cross-ref">
                 <h3>Also appears in (${crossRefs.length} datasets)</h3>
                 ${crossRefs.map(cr => `
                     <div class="cross-ref-item" data-dataset="${esc(cr.dataset_name)}">
                         ${esc(cr.dataset_name)} &rsaquo; ${esc(cr.group_path)}
                     </div>
                 `).join("")}
               </div>`
            : "";

        container.innerHTML = `
            <div class="var-detail-header">
                <h2>${esc(variable.label)}</h2>
                ${variable.code ? `<div class="var-detail-code">${esc(variable.code)}</div>` : ""}
                <div class="var-detail-meta">
                    ${esc(variable.dataset_name || datasetName)} &rsaquo; ${esc(variable.group_path)}
                </div>
            </div>
            <h3 style="margin-top:16px;font-size:15px;font-weight:600;">
                Categories (${variable.categories ? variable.categories.length : 0})
            </h3>
            <div class="categories-grid">
                ${(variable.categories || []).map(c => `
                    <div class="category-chip">${esc(c)}</div>
                `).join("")}
            </div>
            ${crossRefHtml}
        `;

        // Cross-ref click
        container.querySelectorAll(".cross-ref-item").forEach(item => {
            item.addEventListener("click", () => {
                location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(item.dataset.dataset)}`;
            });
        });
    }

    // --- Helpers ---
    function esc(str) {
        if (!str) return "";
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function truncate(str, len) {
        if (!str || str.length <= len) return str || "";
        return str.slice(0, len) + "...";
    }

    // --- Start ---
    document.addEventListener("DOMContentLoaded", init);

    return { init };
})();
```

**Step 2: Test the full app locally**

Run: `cd docs/explorer && python3 -m http.server 8080`
Then open `http://localhost:8080` in a browser.

Expected:
- Loading overlay with progress bar
- Search box works (typeahead after 2 chars)
- Full results appear below search box
- Browse list shows all 131 datasets
- Clicking a dataset shows expandable variable tree
- Clicking a variable shows categories + cross-references
- Hash routing works (back button, direct links)

**Step 3: Commit**

```bash
git add docs/explorer/js/app.js
git commit -m "feat: add main app logic with routing and rendering"
```

---

### Task 7: Run build, verify, and commit generated assets

**Step 1: Run the full build**

Run: `uv run python scripts/build_pages.py`

**Step 2: Test locally**

Run: `cd docs/explorer && python3 -m http.server 8080`
Verify all features work in browser.

**Step 3: Add .gitattributes for large file**

The `dictionary.db` is 49MB. GitHub has a 100MB file limit, so it fits, but add a note:

```
# docs/explorer/.gitattributes
*.db binary
```

**Step 4: Commit everything**

```bash
git add docs/explorer/
git commit -m "feat: add GitHub Pages ABS Dictionary Explorer

Complete static site with:
- Fuzzy typeahead search (Fuse.js)
- Ranked FTS5 search (sql.js/WASM)
- Dataset browser with expandable variable trees
- Variable detail with cross-references
- RMAI branding (Epilogue, purple/oat palette)"
```

---

### Task 8: Configure GitHub Pages and README

**Files:**
- Modify: repository settings (manual step)
- Create: `docs/explorer/README.md`

**Step 1: Add a README for the explorer**

```markdown
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

\`\`\`bash
uv run python scripts/build_pages.py
\`\`\`

Requires `~/.tablebuilder/dictionary.db` (built via `uv run tablebuilder dictionary --rebuild-db`).
```

**Step 2: Enable GitHub Pages**

Manual step: Go to repo Settings → Pages → Source: "Deploy from a branch" → Branch: `main`, folder: `/docs/explorer`.

Or if using a custom domain, configure accordingly.

**Step 3: Commit**

```bash
git add docs/explorer/README.md
git commit -m "docs: add README for GitHub Pages explorer"
```
