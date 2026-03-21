# TableBuilder CLI

Automates ABS TableBuilder (https://tablebuilder.abs.gov.au) to fetch census data as CSV files via Playwright browser automation.

## Credentials

Stored in `~/.tablebuilder/.env`:
```
TABLEBUILDER_USER_ID=your_abs_user_id
TABLEBUILDER_PASSWORD=your_abs_password
```

Credential precedence: CLI flags > environment variables > `.env` file.

## Architecture

Pipeline: `CLI -> Browser Session -> Navigator -> Table Builder -> Downloader`

Self-healing layer: `find_element()` tries knowledge-preferred -> primary -> fallback selectors. `@retry` decorator wraps operations with exponential backoff. `KnowledgeBase` persists learnings to `~/.tablebuilder/knowledge.json`.

## File Purposes

| File | Purpose |
|------|---------|
| `cli.py` | Click CLI: fetch, datasets, variables, doctor subcommands |
| `config.py` | Credential loading from `~/.tablebuilder/.env`, env vars, or CLI flags |
| `models.py` | `Axis` enum (ROW, COL, WAFER), `TableRequest` dataclass |
| `browser.py` | Playwright session context manager, login flow, terms acceptance |
| `navigator.py` | Dataset listing, fuzzy matching, tree expansion, variable search |
| `table_builder.py` | Variable category selection, axis assignment via JSF form submit |
| `downloader.py` | CSV format selection, queue dialog, status polling, ZIP extraction |
| `selectors.py` | Registry of 19 `SelectorEntry` objects with primary + fallback selectors |
| `resilience.py` | `find_element()` and `find_all_elements()` with fallback chains, `@retry` decorator |
| `knowledge.py` | JSON knowledge base: selector preferences, timings, dataset quirks |
| `doctor.py` | Health report: credentials, selector status, timings, quirks summary |
| `logging_config.py` | `setup_logging()` with file handler (DEBUG) + console handler (WARNING or DEBUG) |

## Key Technical Details

### JSF Form Submission
Axis buttons (Add to Row, Add to Column, Add to Wafer) require a hidden input element + `form.submit()` to trigger the server-side JSF action. Regular `.click()` or `dispatch_event("click")` does NOT work. See `_submit_axis_button()` in `table_builder.py`.

### Tree Structure
The ABS variable tree uses `.treeNodeElement` containers, each containing:
- `.treeNodeExpander` (collapsed/expanded toggle; `.leaf` class = no children)
- `.label` (display text)

**Variable labels in the UI include a code prefix**: "SEXP Sex", "INDP Industry of Employment", "AGE10P Age in Ten Year Groups". The dictionary DB stores code and label separately. `_label_matches()` in `table_builder.py` handles both "Sex" and "SEXP Sex" formats.

**Category selection** walks sibling nodes after the variable node. For variables with nested sub-groups (e.g. Industry → Agriculture → sub-categories), intermediate group nodes are skipped — only leaf checkboxes are checked. Walking stops when the next variable-level node is detected (by the `CODE Label` naming pattern via `_is_variable_node()`).

**Tree expansion gotcha**: The fallback selector `[aria-expanded="false"]` matches 7-8 non-tree UI elements that can never be expanded. `_expand_all_collapsed()` has stale detection (breaks after 3 rounds of no progress) to avoid infinite loops. This stale loop costs ~6 minutes per variable search.

### Search Behavior
Searching shows group-level results only. After search, `_expand_all_collapsed()` must run to reveal individual categories within each group.

### Download Flow (corrected 2026-03-21)
**IMPORTANT**: `pageForm:retB` is the **Retrieve Data** button, NOT a Queue button. The correct flow:
1. Select CSV from the format dropdown (`downloadControl:downloadType`)
2. Click Retrieve Data (`pageForm:retB`) with `force=True` (blocked by `autoRetrieve` overlay)
3. Wait for table cells to populate with numeric data
4. Click "Download table" button (`input[value="Download table"]`) directly
5. Playwright `expect_download()` captures the file
6. Extract CSV from ZIP if needed

For large tables that can't download directly, there's a fallback queue flow using `downloadTableModeForm` dialog, but direct download works for most tables.

## Selector Registry

19 selectors in `src/tablebuilder/selectors.py`:

| Name | Primary | Fallbacks | Purpose |
|------|---------|-----------|---------|
| LOGIN_USERNAME | `#loginForm\:username2` | `input[name*="username"]`, `input[type="text"]` | Username input |
| LOGIN_PASSWORD | `#loginForm\:password2` | `input[name*="password"]`, `input[type="password"]` | Password input |
| LOGIN_BUTTON | `#loginForm\:login2` | `button:has-text("Login")`, `input[type="submit"]` | Login submit |
| TERMS_BUTTON | `#termsForm\:termsButton` | `button:has-text("Accept")`, `button:has-text("I Agree")` | Accept terms |
| TREE_NODE | `.treeNodeElement` | `.tree-node`, `[role="treeitem"]` | Tree node container |
| TREE_LABEL | `.label` | `.tree-label`, `.node-label` | Label text in tree node |
| TREE_EXPANDER | `.treeNodeExpander` | `.tree-expander`, `[aria-expanded]` | Expand/collapse toggle |
| TREE_EXPANDER_COLLAPSED | `.treeNodeExpander.collapsed` | `[aria-expanded="false"]` | Collapsed node |
| SEARCH_INPUT | `#searchPattern` | `input[placeholder*="search"]`, `input[type="search"]` | Variable search box |
| SEARCH_BUTTON | `#searchButton` | `button:has-text("Search")` | Search submit |
| CATEGORY_CHECKBOX | `input[type=checkbox]` | `[role="checkbox"]` | Category checkbox |
| FORMAT_DROPDOWN | `#downloadControl\:downloadType` | `select[name*="downloadType"]` | Download format |
| QUEUE_BUTTON | `#pageForm\:retB` | `button:has-text("Queue")` | **Retrieve Data** (NOT queue — name is legacy) |
| QUEUE_DIALOG | `#downloadTableModePanel_container` | `[role="dialog"]`, `.modal` | Queue modal |
| QUEUE_NAME_INPUT | `#downloadTableModeForm\:downloadTableNameTxt` | `input[name*="TableName"]` | Table name input |
| QUEUE_SUBMIT | `#downloadTableModeForm\:queueTableButton` | `button:has-text("Queue")` | Queue submit |
| AXIS_ROW_BUTTON | `#buttonForm\:addR` | `button:has-text("Add to Row")`, `input[value*="Row"]` | Assign to rows |
| AXIS_COL_BUTTON | `#buttonForm\:addC` | `button:has-text("Add to Column")`, `input[value*="Column"]` | Assign to columns |
| AXIS_WAFER_BUTTON | `#buttonForm\:addL` | `button:has-text("Add to Wafer")`, `input[value*="Layer"]` | Assign to wafers |

## Self-Healing System

### find_element() flow
1. Check knowledge base for a preferred selector (most recently successful)
2. Try primary CSS selector
3. Try each fallback selector in order
4. Record success/failure in the knowledge base for future runs

### @retry decorator
Wraps functions with exponential backoff. Default: 3 attempts, 2x backoff. Login and dataset navigation use this for transient `PlaywrightTimeout` errors.

### KnowledgeBase
Persists to `~/.tablebuilder/knowledge.json`. Tracks:
- **Selector preferences**: which selector last worked for each element
- **Timings**: running averages for login, queue_and_download
- **Dataset quirks**: per-dataset notes (slow loads, unusual structures)
- **Run count**: total invocations

## Failure Modes

| Failure | How It Is Handled |
|---------|-------------------|
| ABS UI redesign | Fallback selectors kick in; knowledge base promotes working selectors |
| Login timeout | Retry with exponential backoff (2 attempts) |
| Wrong credentials | Detected by checking if still on `login.xhtml`; clear error message |
| Queue timeout | Configurable via `--timeout` flag (default: 600s) |
| Tree loading delays | `_expand_all_collapsed()` loops until no collapsed nodes remain |
| Maintenance mode | Detected on login page; logs a warning, proceeds anyway |
| Missing categories | `_check_variable_categories()` raises `TableBuildError` if 0 found |
| ZIP download errors | Falls back to raw file copy if not a valid ZIP |

## Common Commands

```bash
# Install dependencies
uv sync
uv run playwright install chromium

# Fetch a table
uv run tablebuilder fetch --dataset "Census 2021" --rows "SEXP Sex" -o out.csv

# List datasets
uv run tablebuilder datasets

# Health check
uv run tablebuilder doctor

# Run all unit tests
uv run pytest

# Run integration tests (needs real ABS credentials)
uv run pytest -m integration

# Run specific test file
uv run pytest tests/test_browser.py -v
```

## Logging

- Log files: `~/.tablebuilder/logs/tablebuilder_YYYY-MM-DD.log`
- File handler: always at DEBUG level
- Console handler: WARNING by default, DEBUG with `-v` flag
- Each module uses `get_logger("tablebuilder.<module>")` for namespaced logging

## Testing Notes

- Unit tests use mocked Playwright pages and click's `CliRunner`
- Integration tests (`test_integration.py`) require real ABS credentials and a browser
- Integration tests are marked with `@pytest.mark.integration` and skipped by default
- Run `uv run pytest --ignore=tests/test_integration.py -q` for a quick check

## Known Issues & Improvement Opportunities

### Performance: Stale Expansion Loop (~6 min per variable)
The `[aria-expanded="false"]` fallback selector matches 7-8 non-tree UI elements. Each stale detection round wastes ~2 min clicking these phantom elements. Fix: scope the fallback selector to only match elements within the tree panel (e.g. `.treeNodeExpander[aria-expanded="false"]`), or just drop the `[aria-expanded="false"]` fallback entirely since the primary `.treeNodeExpander.collapsed` works fine.

### Resolver Returns Variable Codes Instead of Labels
The ChatResolver sometimes returns "OCCP" instead of "Occupation". The system prompt says labels must exactly match, but the LLM doesn't always comply. `_find_variable_node()` has a code-prefix fallback (pass 3) but ideally the resolver should be fixed to always return labels.

### Some Variables Fail Category Selection
"Age" (single years, 100+ categories) fails with "No categories found". The `_is_variable_node()` regex may incorrectly identify some intermediate nodes as variables, causing the walker to stop too early. Needs investigation with headed browser to see the actual tree structure for these variables.

### Context Destruction on Long Sessions
Queries 14, 18, 20 failed with "Execution context was destroyed" — the browser session times out or the page navigates during a long operation. Possible fix: add session health checks and re-login if needed.

### Dataset Name Fuzzy Matching
Query 17 failed because the resolver returned "Labour Force Survey, 2006 to 2025" but the actual dataset name uses different formatting. The fuzzy matcher should be more lenient with date ranges and punctuation.

### Batch Fetch Performance
Each fetch takes 8-28 minutes (avg ~15 min), dominated by tree expansion. Total batch of 20 queries took ~5.5 hours. To improve: reuse browser sessions across queries for the same dataset, or skip tree expansion when auto-retrieve is enabled (data populates automatically when variables are added).

## Data Dictionary Search

SQLite database at `~/.tablebuilder/dictionary.db` contains 96 ABS TableBuilder datasets
(28,561 variables, 256,578 categories) with FTS5 full-text search.

```bash
# CLI search
uv run tablebuilder search "employment industry"

# Direct SQLite (for Claude Code sessions)
sqlite3 ~/.tablebuilder/dictionary.db "SELECT dataset_name, label, categories_text FROM variables_fts WHERE variables_fts MATCH 'sex age' ORDER BY rank LIMIT 10;"

# Rebuild after new extractions
uv run tablebuilder dictionary --rebuild-db
```
