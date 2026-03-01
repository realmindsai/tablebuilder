# TableBuilder CLI — Design Document

**Date:** 2026-03-02
**Status:** Approved

## Problem

ABS TableBuilder provides access to Australian microdata through a web UI at
`tablebuilder.abs.gov.au`. There is no public API. Fetching custom
cross-tabulations requires manual interaction with a JSF/WingArc web
application: login, navigate datasets, add variables to rows/columns, queue
the table, wait, and download.

We want a CLI tool that automates this entire flow so you can type one command
and get a CSV.

## Solution

A Python CLI tool (`tablebuilder`) that uses Playwright to drive a headless
browser through the TableBuilder web UI.

### Tech Stack

- Python (managed with uv)
- Click (CLI framework)
- Playwright (browser automation)
- python-dotenv (credentials)

### CLI Interface

```bash
# Fetch data — all variables default to rows (long/tidy format)
tablebuilder fetch \
  --dataset "Census 2021, Basic TableBuilder" \
  --rows Age --rows Sex --rows SA2 \
  -o output.csv

# Mixed: some rows, some columns
tablebuilder fetch \
  --dataset "Census 2021 Basic" \
  --rows Age --rows SA2 \
  --cols Sex \
  -o output.csv

# With wafers (third dimension)
tablebuilder fetch \
  --dataset "Census 2021 Basic" \
  --rows Age \
  --cols Sex --cols State \
  --wafers Year \
  -o output.csv

# List available datasets
tablebuilder datasets

# List variables in a dataset
tablebuilder variables "Census 2021 Basic"

# Configure credentials
tablebuilder config
```

**Flags:**
- `--dataset` (required): Dataset name, fuzzy-matched
- `--rows` (required, repeatable): Variables to place in rows
- `--cols` (optional, repeatable): Variables to place in columns
- `--wafers` (optional, repeatable): Variables to place in wafers
- `-o / --output` (optional): Output CSV path. Defaults to `./tablebuilder_YYYYMMDD_HHMMSS.csv`
- `--headed` (optional): Show the browser window for debugging

### Architecture

```
tablebuilder/
├── src/
│   └── tablebuilder/
│       ├── __init__.py
│       ├── cli.py              # Click CLI entry point
│       ├── config.py           # Credentials + settings management
│       ├── browser.py          # Playwright session management
│       ├── navigator.py        # Dataset/variable navigation
│       ├── table_builder.py    # Table construction
│       ├── downloader.py       # Queue, wait, download CSV
│       └── models.py           # Data classes
├── tests/
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_models.py
│   └── test_integration.py
├── pyproject.toml
└── .env.example
```

### Authentication

- Credentials stored in `~/.tablebuilder/.env` as `TABLEBUILDER_USER_ID` and
  `TABLEBUILDER_PASSWORD`
- Can also be passed as CLI flags or environment variables
- Fresh login per command (no session caching) — simple and reliable
- 30-minute session timeout is not a concern with single-command flow

### Core Flow

1. **Login** (`browser.py`): Launch headless Chromium, navigate to login page,
   fill credentials, handle conditions-of-use acceptance, verify home page.

2. **Open dataset** (`navigator.py`): Expand dataset folders, fuzzy-match the
   requested dataset name, double-click to open Table View.

3. **Add variables** (`table_builder.py`): For each variable in --rows,
   --cols, --wafers: use the search box to find it, check all categories,
   click the appropriate "Add to Row/Column/Wafer" button.

4. **Queue and download** (`downloader.py`): Select CSV format from dropdown,
   click "Queue table", enter a timestamp-based name, navigate to "Saved and
   queued tables", poll until Completed (every 5s, 10min timeout), click
   download, unzip, move CSV to output path.

5. **Cleanup**: Delete the saved table, close browser, report success.

### Functions

| Module | Function | Purpose |
|--------|----------|---------|
| cli | `fetch()` | Main entry point. Parses flags, orchestrates full flow. |
| cli | `datasets()` | Lists available datasets by reading the dataset panel. |
| cli | `variables(dataset)` | Lists variables for a given dataset. |
| config | `load_config()` | Reads ~/.tablebuilder/.env, falls back to env vars. |
| browser | `create_session()` | Launches Playwright, returns context manager for page + browser. |
| browser | `login(page, config)` | Fills login form, handles conditions-of-use, verifies home page. |
| navigator | `open_dataset(page, name)` | Fuzzy-matches dataset name in tree, opens Table View. |
| navigator | `search_variable(page, name)` | Uses dataset search box to find a variable. |
| table_builder | `add_variable(page, var, axis)` | Checks categories, clicks Add to Row/Column/Wafer. |
| table_builder | `build_table(page, request)` | Adds all variables to their requested axes. |
| downloader | `queue_table(page, name)` | Selects CSV, clicks Queue, enters table name. |
| downloader | `wait_for_completion(page, name)` | Polls status until Completed or timeout. |
| downloader | `download_and_extract(page, output)` | Downloads zip, extracts CSV to output path. |
| downloader | `cleanup_saved_table(page, name)` | Deletes queued table from saved tables. |

### Error Handling

- **Bad credentials**: Detect login error message, exit with clear message
- **Maintenance window**: Detect maintenance banner, report when service resumes
- **Variable not found**: List similar variables, suggest corrections
- **Queue timeout**: Report after 10 minutes, suggest checking manually
- **Download failure**: Retry once, then fail with instructions

### Tests

| Test | Validates |
|------|-----------|
| `test_config_loads_from_env_file` | Config reads creds from .env file |
| `test_config_falls_back_to_env_vars` | Config uses env vars as fallback |
| `test_config_error_on_missing_creds` | Clear error when no creds found |
| `test_table_request_validation` | TableRequest needs dataset + rows |
| `test_table_request_rejects_empty_rows` | Cannot create request with zero rows |
| `test_cli_fetch_requires_dataset` | CLI errors without --dataset |
| `test_cli_fetch_requires_rows` | CLI errors without --rows |
| `test_cli_datasets_lists_available` | Integration: datasets returns list |
| `test_full_fetch_flow` | Integration: end-to-end fetch produces CSV |
| `test_login_failure_gives_clear_error` | Integration: bad creds give message |

### Risks

- **UI changes**: ABS could redesign the TableBuilder UI, breaking selectors.
  Mitigation: use semantic selectors (labels, roles) over CSS classes.
- **Rate limiting**: Unknown if ABS throttles automated access. Mitigation:
  add delays between actions, respect their terms of use.
- **Large tables**: Queue times can be hours. Mitigation: 10-minute default
  timeout with `--timeout` override flag.
