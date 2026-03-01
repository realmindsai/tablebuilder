# TableBuilder CLI

Automates ABS TableBuilder (tablebuilder.abs.gov.au) to fetch microdata CSV via Playwright browser automation.

## Commands
- `uv sync` — install deps
- `uv run pytest` — run unit tests
- `uv run pytest -m integration` — run integration tests (needs ABS account)
- `uv run pytest -m "not integration"` — run unit tests only
- `uv run tablebuilder --help` — CLI help

## Architecture
- `src/tablebuilder/cli.py` — Click CLI commands
- `src/tablebuilder/config.py` — Credentials from ~/.tablebuilder/.env
- `src/tablebuilder/browser.py` — Playwright session management
- `src/tablebuilder/navigator.py` — Dataset/variable navigation
- `src/tablebuilder/table_builder.py` — Add variables to rows/cols/wafers
- `src/tablebuilder/downloader.py` — Queue, wait, download CSV
- `src/tablebuilder/models.py` — Data classes

## Credentials
Stored in `~/.tablebuilder/.env` — never commit real credentials.
