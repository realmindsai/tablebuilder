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

Category selection walks sibling nodes after the variable node, checking leaf checkboxes until hitting a non-leaf node.

### Search Behavior
Searching shows group-level results only. After search, `_expand_all_collapsed()` must run to reveal individual categories within each group.

### Queue Flow
1. Select CSV from the format dropdown (`downloadControl:downloadType`)
2. Click Queue button (`pageForm:retB`) on the table view
3. Fill the name field in the dialog (`downloadTableModeForm:downloadTableNameTxt`)
4. Submit the dialog (`downloadTableModeForm:queueTableButton`)
5. Navigate to saved tables page
6. Poll for "click here to download" link matching the table name
7. Click to download ZIP, extract the CSV file

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
| QUEUE_BUTTON | `#pageForm\:retB` | `button:has-text("Queue")` | Open queue dialog |
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
