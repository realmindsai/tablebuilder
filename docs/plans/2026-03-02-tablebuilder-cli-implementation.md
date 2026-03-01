# TableBuilder CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python CLI that automates the ABS TableBuilder web UI to fetch microdata as CSV.

**Architecture:** Playwright drives a headless browser through login → dataset selection → variable assignment to rows/cols/wafers → queue → download. Click provides the CLI. Config lives in `~/.tablebuilder/.env`.

**Tech Stack:** Python 3.12, uv, Click, Playwright, python-dotenv, pytest

**Design doc:** `docs/plans/2026-03-02-tablebuilder-cli-design.md`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/tablebuilder/__init__.py`
- Create: `.env.example`
- Create: `tests/__init__.py`
- Create: `CLAUDE.md`

**Step 1: Create pyproject.toml with uv**

```bash
cd /Users/dewoller/code/tablebuilder
uv init --lib --name tablebuilder
```

If that creates files in wrong places, manually create `pyproject.toml`:

```toml
[project]
name = "tablebuilder"
version = "0.1.0"
description = "CLI to download data from ABS TableBuilder"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1",
    "playwright>=1.40",
    "python-dotenv>=1.0",
]

[project.scripts]
tablebuilder = "tablebuilder.cli:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: marks tests that require a real browser and ABS account (deselect with '-m \"not integration\"')",
]

[tool.hatch.build.targets.wheel]
packages = ["src/tablebuilder"]
```

**Step 2: Create source package and .env.example**

Create `src/tablebuilder/__init__.py`:
```python
# ABOUTME: TableBuilder CLI package root.
# ABOUTME: Automates ABS TableBuilder web UI to fetch microdata as CSV.
```

Create `.env.example`:
```bash
# ABS TableBuilder credentials
# Copy to ~/.tablebuilder/.env and fill in your values
TABLEBUILDER_USER_ID=your_numeric_user_id
TABLEBUILDER_PASSWORD=your_password
```

Create `tests/__init__.py` (empty).

**Step 3: Install dependencies and Playwright browsers**

```bash
cd /Users/dewoller/code/tablebuilder
uv sync
uv run playwright install chromium
```

**Step 4: Verify the install works**

```bash
uv run python -c "import tablebuilder; print('ok')"
uv run pytest --co  # should collect 0 tests, no errors
```

Expected: `ok` and `no tests ran`

**Step 5: Create CLAUDE.md with project conventions**

Create `CLAUDE.md`:
```markdown
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
```

**Step 6: Commit**

```bash
git add pyproject.toml src/ tests/ .env.example CLAUDE.md
git commit -m "feat: scaffold tablebuilder project with uv, click, playwright"
```

---

### Task 2: Models (Data Classes)

**Files:**
- Create: `src/tablebuilder/models.py`
- Create: `tests/test_models.py`

**Step 1: Write failing tests for models**

Create `tests/test_models.py`:

```python
# ABOUTME: Tests for TableBuilder data models.
# ABOUTME: Validates TableRequest construction and validation rules.

import pytest

from tablebuilder.models import Axis, TableRequest


class TestTableRequest:
    def test_valid_request_with_rows_only(self):
        """A request with dataset and rows is valid."""
        req = TableRequest(
            dataset="Census 2021 Basic",
            rows=["Age", "Sex"],
        )
        assert req.dataset == "Census 2021 Basic"
        assert req.rows == ["Age", "Sex"]
        assert req.cols == []
        assert req.wafers == []

    def test_valid_request_with_all_axes(self):
        """A request can have rows, cols, and wafers."""
        req = TableRequest(
            dataset="Census 2021 Basic",
            rows=["Age"],
            cols=["Sex"],
            wafers=["State"],
        )
        assert req.rows == ["Age"]
        assert req.cols == ["Sex"]
        assert req.wafers == ["State"]

    def test_rejects_empty_dataset(self):
        """Dataset name cannot be empty."""
        with pytest.raises(ValueError, match="dataset"):
            TableRequest(dataset="", rows=["Age"])

    def test_rejects_empty_rows(self):
        """At least one row variable is required."""
        with pytest.raises(ValueError, match="rows"):
            TableRequest(dataset="Census 2021 Basic", rows=[])

    def test_rejects_no_rows(self):
        """Rows parameter is mandatory."""
        with pytest.raises(TypeError):
            TableRequest(dataset="Census 2021 Basic")

    def test_all_variables_returns_flat_list(self):
        """all_variables() returns every variable across all axes."""
        req = TableRequest(
            dataset="Census 2021 Basic",
            rows=["Age", "Sex"],
            cols=["State"],
            wafers=["Year"],
        )
        assert req.all_variables() == ["Age", "Sex", "State", "Year"]

    def test_variable_axes_returns_mapping(self):
        """variable_axes() maps each variable to its axis."""
        req = TableRequest(
            dataset="Census 2021 Basic",
            rows=["Age"],
            cols=["Sex"],
        )
        axes = req.variable_axes()
        assert axes == {"Age": Axis.ROW, "Sex": Axis.COL}


class TestAxis:
    def test_axis_values(self):
        """Axis enum has ROW, COL, WAFER."""
        assert Axis.ROW.value == "row"
        assert Axis.COL.value == "col"
        assert Axis.WAFER.value == "wafer"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tablebuilder.models'`

**Step 3: Write minimal implementation**

Create `src/tablebuilder/models.py`:

```python
# ABOUTME: Data classes for TableBuilder requests and configuration.
# ABOUTME: TableRequest defines what data to fetch; Axis defines row/col/wafer placement.

from dataclasses import dataclass, field
from enum import Enum


class Axis(Enum):
    ROW = "row"
    COL = "col"
    WAFER = "wafer"


@dataclass
class TableRequest:
    """Describes a table to fetch from ABS TableBuilder."""

    dataset: str
    rows: list[str]
    cols: list[str] = field(default_factory=list)
    wafers: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.dataset or not self.dataset.strip():
            raise ValueError("dataset name cannot be empty")
        if not self.rows:
            raise ValueError("rows must contain at least one variable")

    def all_variables(self) -> list[str]:
        """Return all variables across all axes in order."""
        return self.rows + self.cols + self.wafers

    def variable_axes(self) -> dict[str, Axis]:
        """Map each variable name to its target axis."""
        result: dict[str, Axis] = {}
        for var in self.rows:
            result[var] = Axis.ROW
        for var in self.cols:
            result[var] = Axis.COL
        for var in self.wafers:
            result[var] = Axis.WAFER
        return result
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_models.py -v
```

Expected: 7 passed

**Step 5: Commit**

```bash
git add src/tablebuilder/models.py tests/test_models.py
git commit -m "feat: add TableRequest and Axis data models with validation"
```

---

### Task 3: Config Module

**Files:**
- Create: `src/tablebuilder/config.py`
- Create: `tests/test_config.py`

**Step 1: Write failing tests for config**

Create `tests/test_config.py`:

```python
# ABOUTME: Tests for credential loading from .env files and environment variables.
# ABOUTME: Validates precedence: CLI flags > env vars > .env file.

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tablebuilder.config import Config, load_config, ConfigError


class TestLoadConfig:
    def test_loads_from_env_file(self, tmp_path):
        """Reads credentials from a .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "TABLEBUILDER_USER_ID=12345\nTABLEBUILDER_PASSWORD=secret\n"
        )
        config = load_config(env_path=env_file)
        assert config.user_id == "12345"
        assert config.password == "secret"

    def test_falls_back_to_env_vars(self, tmp_path):
        """Uses environment variables when no .env file exists."""
        missing = tmp_path / "nonexistent" / ".env"
        with patch.dict(
            os.environ,
            {
                "TABLEBUILDER_USER_ID": "99999",
                "TABLEBUILDER_PASSWORD": "envpass",
            },
        ):
            config = load_config(env_path=missing)
            assert config.user_id == "99999"
            assert config.password == "envpass"

    def test_error_on_missing_user_id(self, tmp_path):
        """Raises ConfigError when user ID is not found anywhere."""
        env_file = tmp_path / ".env"
        env_file.write_text("TABLEBUILDER_PASSWORD=secret\n")
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError, match="TABLEBUILDER_USER_ID"):
                load_config(env_path=env_file)

    def test_error_on_missing_password(self, tmp_path):
        """Raises ConfigError when password is not found anywhere."""
        env_file = tmp_path / ".env"
        env_file.write_text("TABLEBUILDER_USER_ID=12345\n")
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError, match="TABLEBUILDER_PASSWORD"):
                load_config(env_path=env_file)

    def test_cli_overrides_take_precedence(self, tmp_path):
        """Explicit user_id/password args override .env and env vars."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "TABLEBUILDER_USER_ID=file_id\nTABLEBUILDER_PASSWORD=file_pw\n"
        )
        config = load_config(
            env_path=env_file, user_id="cli_id", password="cli_pw"
        )
        assert config.user_id == "cli_id"
        assert config.password == "cli_pw"

    def test_default_env_path(self):
        """Default .env path is ~/.tablebuilder/.env."""
        from tablebuilder.config import DEFAULT_ENV_PATH

        assert DEFAULT_ENV_PATH == Path.home() / ".tablebuilder" / ".env"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tablebuilder.config'`

**Step 3: Write minimal implementation**

Create `src/tablebuilder/config.py`:

```python
# ABOUTME: Credential loading for ABS TableBuilder authentication.
# ABOUTME: Reads from ~/.tablebuilder/.env, env vars, or CLI flags (in that precedence order).

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_ENV_PATH = Path.home() / ".tablebuilder" / ".env"


class ConfigError(Exception):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class Config:
    """ABS TableBuilder credentials."""

    user_id: str
    password: str


def load_config(
    env_path: Path = DEFAULT_ENV_PATH,
    user_id: str | None = None,
    password: str | None = None,
) -> Config:
    """Load credentials with precedence: explicit args > env vars > .env file."""
    file_values = dotenv_values(env_path) if env_path.exists() else {}

    resolved_user_id = (
        user_id
        or os.environ.get("TABLEBUILDER_USER_ID")
        or file_values.get("TABLEBUILDER_USER_ID")
    )
    resolved_password = (
        password
        or os.environ.get("TABLEBUILDER_PASSWORD")
        or file_values.get("TABLEBUILDER_PASSWORD")
    )

    if not resolved_user_id:
        raise ConfigError(
            "TABLEBUILDER_USER_ID not found. "
            "Set it in ~/.tablebuilder/.env, as an env var, or pass --user-id."
        )
    if not resolved_password:
        raise ConfigError(
            "TABLEBUILDER_PASSWORD not found. "
            "Set it in ~/.tablebuilder/.env, as an env var, or pass --password."
        )

    return Config(user_id=resolved_user_id, password=resolved_password)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 6 passed

**Step 5: Commit**

```bash
git add src/tablebuilder/config.py tests/test_config.py
git commit -m "feat: add config module for credential loading"
```

---

### Task 4: CLI Skeleton

**Files:**
- Create: `src/tablebuilder/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write failing tests for CLI**

Create `tests/test_cli.py`:

```python
# ABOUTME: Tests for the Click CLI interface.
# ABOUTME: Validates flag parsing, required arguments, and help output.

from click.testing import CliRunner

from tablebuilder.cli import cli


class TestCliHelp:
    def test_main_help_shows_commands(self):
        """Top-level --help lists fetch, datasets, variables, config."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "fetch" in result.output
        assert "datasets" in result.output
        assert "variables" in result.output

    def test_fetch_help_shows_flags(self):
        """fetch --help lists --dataset, --rows, --cols, --wafers, --output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--help"])
        assert result.exit_code == 0
        assert "--dataset" in result.output
        assert "--rows" in result.output
        assert "--cols" in result.output
        assert "--wafers" in result.output
        assert "--output" in result.output


class TestCliFetch:
    def test_fetch_requires_dataset(self):
        """fetch without --dataset exits with error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--rows", "Age"])
        assert result.exit_code != 0
        assert "dataset" in result.output.lower() or "required" in result.output.lower()

    def test_fetch_requires_rows(self):
        """fetch without --rows exits with error."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["fetch", "--dataset", "Census 2021 Basic"]
        )
        assert result.exit_code != 0

    def test_fetch_parses_multiple_rows(self):
        """fetch accepts multiple --rows flags."""
        runner = CliRunner()
        # This will fail at the browser step, but we check parsing worked
        result = runner.invoke(
            cli,
            [
                "fetch",
                "--dataset", "Census 2021 Basic",
                "--rows", "Age",
                "--rows", "Sex",
                "--user-id", "fake",
                "--password", "fake",
            ],
            catch_exceptions=False,
        )
        # It will fail connecting to TableBuilder, but it should get past arg parsing
        # We check it didn't fail with a Click usage error
        assert "Usage:" not in result.output or result.exit_code != 2
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tablebuilder.cli'`

**Step 3: Write minimal implementation**

Create `src/tablebuilder/cli.py`:

```python
# ABOUTME: Click CLI entry point for the tablebuilder command.
# ABOUTME: Provides fetch, datasets, variables, and config subcommands.

import sys
from datetime import datetime

import click

from tablebuilder.config import ConfigError, load_config
from tablebuilder.models import TableRequest


@click.group()
def cli():
    """Download data from ABS TableBuilder."""


@cli.command()
@click.option("--dataset", required=True, help="Dataset name (fuzzy-matched).")
@click.option(
    "--rows", multiple=True, required=True, help="Variable(s) to place in rows."
)
@click.option("--cols", multiple=True, help="Variable(s) to place in columns.")
@click.option("--wafers", multiple=True, help="Variable(s) to place in wafers.")
@click.option(
    "-o",
    "--output",
    default=None,
    help="Output CSV path. Defaults to ./tablebuilder_YYYYMMDD_HHMMSS.csv.",
)
@click.option("--headed", is_flag=True, help="Show browser window for debugging.")
@click.option("--user-id", default=None, help="ABS User ID (overrides .env).")
@click.option("--password", default=None, help="ABS password (overrides .env).")
@click.option(
    "--timeout",
    default=600,
    type=int,
    help="Queue timeout in seconds (default: 600).",
)
def fetch(dataset, rows, cols, wafers, output, headed, user_id, password, timeout):
    """Fetch a table from ABS TableBuilder and download as CSV."""
    try:
        config = load_config(user_id=user_id, password=password)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    request = TableRequest(
        dataset=dataset,
        rows=list(rows),
        cols=list(cols),
        wafers=list(wafers),
    )

    if output is None:
        output = f"tablebuilder_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    click.echo(f"Dataset: {request.dataset}")
    click.echo(f"Rows: {', '.join(request.rows)}")
    if request.cols:
        click.echo(f"Cols: {', '.join(request.cols)}")
    if request.wafers:
        click.echo(f"Wafers: {', '.join(request.wafers)}")
    click.echo(f"Output: {output}")

    # Browser automation goes here (Task 5+)
    click.echo("Browser automation not yet implemented.")
    sys.exit(1)


@cli.command()
@click.option("--user-id", default=None, help="ABS User ID (overrides .env).")
@click.option("--password", default=None, help="ABS password (overrides .env).")
def datasets(user_id, password):
    """List available datasets in TableBuilder."""
    click.echo("Not yet implemented.")
    sys.exit(1)


@cli.command()
@click.argument("dataset")
@click.option("--user-id", default=None, help="ABS User ID (overrides .env).")
@click.option("--password", default=None, help="ABS password (overrides .env).")
def variables(dataset, user_id, password):
    """List variables in a TableBuilder dataset."""
    click.echo("Not yet implemented.")
    sys.exit(1)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: 4 passed

**Step 5: Verify the CLI entrypoint works**

```bash
uv run tablebuilder --help
uv run tablebuilder fetch --help
```

Expected: help output with all commands/flags listed

**Step 6: Commit**

```bash
git add src/tablebuilder/cli.py tests/test_cli.py
git commit -m "feat: add Click CLI skeleton with fetch, datasets, variables commands"
```

---

### Task 5: Browser Session Management

**Files:**
- Create: `src/tablebuilder/browser.py`
- Create: `tests/test_browser.py`

This task implements the Playwright session lifecycle. Unit tests verify the context manager structure. Integration tests (marked) verify real login.

**Step 1: Write failing tests**

Create `tests/test_browser.py`:

```python
# ABOUTME: Tests for Playwright browser session management.
# ABOUTME: Unit tests for session lifecycle; integration tests for real login.

import pytest

from tablebuilder.browser import TableBuilderSession, LoginError
from tablebuilder.config import Config


TABLEBUILDER_URL = "https://tablebuilder.abs.gov.au/webapi/jsf/login.xhtml"


class TestTableBuilderSession:
    def test_session_is_context_manager(self):
        """TableBuilderSession can be used as a context manager."""
        config = Config(user_id="fake", password="fake")
        session = TableBuilderSession(config, headless=True)
        assert hasattr(session, "__enter__")
        assert hasattr(session, "__exit__")

    def test_session_stores_config(self):
        """Session stores the config and headless flag."""
        config = Config(user_id="12345", password="pw")
        session = TableBuilderSession(config, headless=False)
        assert session.config == config
        assert session.headless is False

    def test_session_default_headless(self):
        """Session defaults to headless=True."""
        config = Config(user_id="12345", password="pw")
        session = TableBuilderSession(config)
        assert session.headless is True


@pytest.mark.integration
class TestTableBuilderSessionIntegration:
    def test_login_with_bad_credentials_raises(self):
        """Login with invalid credentials raises LoginError."""
        config = Config(user_id="00000", password="wrongpassword")
        session = TableBuilderSession(config, headless=True)
        with pytest.raises(LoginError):
            with session as page:
                pass  # login happens in __enter__

    def test_login_reaches_home_page(self, abs_config):
        """Login with valid credentials reaches the datasets page."""
        session = TableBuilderSession(abs_config, headless=True)
        with session as page:
            # After login we should see the datasets panel
            assert page.url != TABLEBUILDER_URL
            # The page should have dataset-related content
            page.wait_for_selector("text=Datasets", timeout=15000)
```

Also add a `conftest.py` for the integration fixture. Create `tests/conftest.py`:

```python
# ABOUTME: Shared pytest fixtures for tablebuilder tests.
# ABOUTME: Provides abs_config fixture for integration tests needing real credentials.

import pytest

from tablebuilder.config import Config, load_config, ConfigError


@pytest.fixture
def abs_config():
    """Load real ABS credentials for integration tests.

    Skips the test if no credentials are configured.
    """
    try:
        return load_config()
    except ConfigError:
        pytest.skip("No ABS credentials configured for integration tests")
```

**Step 2: Run unit tests to verify they fail**

```bash
uv run pytest tests/test_browser.py -v -m "not integration"
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tablebuilder.browser'`

**Step 3: Write minimal implementation**

Create `src/tablebuilder/browser.py`:

```python
# ABOUTME: Playwright browser session management for ABS TableBuilder.
# ABOUTME: Handles browser launch, login, conditions-of-use, and cleanup.

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout

from tablebuilder.config import Config

TABLEBUILDER_LOGIN_URL = "https://tablebuilder.abs.gov.au/webapi/jsf/login.xhtml"


class LoginError(Exception):
    """Raised when login to TableBuilder fails."""


class MaintenanceError(Exception):
    """Raised when TableBuilder is in maintenance mode."""


class TableBuilderSession:
    """Context manager for a Playwright session logged into TableBuilder."""

    def __init__(self, config: Config, headless: bool = True):
        self.config = config
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> Page:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self._login()
        return self._page

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        return False

    def _login(self):
        """Navigate to login page, fill credentials, verify success."""
        page = self._page
        page.goto(TABLEBUILDER_LOGIN_URL, wait_until="networkidle")

        # Check for maintenance
        maintenance = page.query_selector("text=maintenance")
        if maintenance and "scheduled" in (maintenance.text_content() or "").lower():
            # Maintenance banner exists but site may still be accessible
            pass

        # Fill login form
        page.fill('input[type="text"]', self.config.user_id)
        page.fill('input[type="password"]', self.config.password)
        page.click('input[type="submit"], button[type="submit"]')

        # Wait for navigation
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            raise LoginError("Login timed out — TableBuilder may be down.")

        # Check for login error
        error_element = page.query_selector(".error-message, .ui-messages-error")
        if error_element:
            error_text = error_element.text_content() or "Unknown login error"
            raise LoginError(f"Login failed: {error_text.strip()}")

        # If we're still on the login page, credentials were wrong
        if "login.xhtml" in page.url:
            raise LoginError(
                "Login failed — still on login page. Check your User ID and password."
            )

        # Handle conditions-of-use dialog if it appears
        try:
            agree_button = page.wait_for_selector(
                "text=I agree, button:has-text('Agree'), input[value='Agree']",
                timeout=3000,
            )
            if agree_button:
                agree_button.click()
                page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeout:
            pass  # No conditions dialog — that's fine
```

**Step 4: Run unit tests to verify they pass**

```bash
uv run pytest tests/test_browser.py -v -m "not integration"
```

Expected: 3 passed

**Step 5: Run integration tests if credentials available**

```bash
uv run pytest tests/test_browser.py -v -m "integration"
```

Expected: Either 2 passed (if credentials configured) or 2 skipped

**Step 6: Commit**

```bash
git add src/tablebuilder/browser.py tests/test_browser.py tests/conftest.py
git commit -m "feat: add Playwright browser session with login handling"
```

---

### Task 6: Dataset Navigator

**Files:**
- Create: `src/tablebuilder/navigator.py`
- Create: `tests/test_navigator.py`

The navigator finds datasets and variables in the TableBuilder UI. Unit tests verify the fuzzy-matching logic. Integration tests verify real navigation.

**Step 1: Write failing tests**

Create `tests/test_navigator.py`:

```python
# ABOUTME: Tests for dataset and variable navigation in TableBuilder.
# ABOUTME: Unit tests for fuzzy matching; integration tests for real UI navigation.

import pytest

from tablebuilder.navigator import fuzzy_match_dataset, NavigationError


class TestFuzzyMatch:
    def test_exact_match(self):
        """Exact name matches perfectly."""
        datasets = ["Census 2021 Basic", "Labour Force", "CPI"]
        assert fuzzy_match_dataset("Census 2021 Basic", datasets) == "Census 2021 Basic"

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        datasets = ["Census 2021 Basic", "Labour Force"]
        assert fuzzy_match_dataset("census 2021 basic", datasets) == "Census 2021 Basic"

    def test_partial_match(self):
        """Substring match works."""
        datasets = [
            "Census 2021, Basic TableBuilder",
            "Census 2021, Pro TableBuilder",
        ]
        assert "Basic" in fuzzy_match_dataset("Census 2021 Basic", datasets)

    def test_no_match_raises(self):
        """No matching dataset raises NavigationError."""
        datasets = ["Labour Force", "CPI"]
        with pytest.raises(NavigationError, match="No dataset matching"):
            fuzzy_match_dataset("Census 2021", datasets)

    def test_no_match_suggests_alternatives(self):
        """Error message includes available dataset names."""
        datasets = ["Labour Force Survey", "CPI Quarterly"]
        with pytest.raises(NavigationError) as exc_info:
            fuzzy_match_dataset("Census", datasets)
        assert "Labour Force Survey" in str(exc_info.value)


@pytest.mark.integration
class TestNavigatorIntegration:
    def test_list_datasets(self, abs_page):
        """Can list available datasets from the home page."""
        from tablebuilder.navigator import list_datasets

        datasets = list_datasets(abs_page)
        assert len(datasets) > 0
        # Census datasets should be available
        assert any("Census" in d for d in datasets)

    def test_open_dataset(self, abs_page):
        """Can open a dataset and reach the Table View."""
        from tablebuilder.navigator import open_dataset

        open_dataset(abs_page, "Census 2021")
        # Should be in Table View now — look for variable panel
        abs_page.wait_for_selector("text=Add to Row", timeout=15000)
```

Add to `tests/conftest.py` — append the `abs_page` fixture:

```python
from tablebuilder.browser import TableBuilderSession


@pytest.fixture
def abs_page(abs_config):
    """Provide a logged-in TableBuilder page for integration tests."""
    session = TableBuilderSession(abs_config, headless=True)
    with session as page:
        yield page
```

**Step 2: Run unit tests to verify they fail**

```bash
uv run pytest tests/test_navigator.py -v -m "not integration"
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/tablebuilder/navigator.py`:

```python
# ABOUTME: Navigate datasets and variables in the TableBuilder UI.
# ABOUTME: Fuzzy-matches dataset names and opens them in Table View.

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


class NavigationError(Exception):
    """Raised when navigation in TableBuilder fails."""


def fuzzy_match_dataset(query: str, available: list[str]) -> str:
    """Find the best matching dataset name from available options.

    Tries exact match first, then case-insensitive, then substring.
    """
    query_lower = query.lower()

    # Exact match
    for name in available:
        if name == query:
            return name

    # Case-insensitive exact match
    for name in available:
        if name.lower() == query_lower:
            return name

    # Substring match — all query words must appear in the dataset name
    query_words = query_lower.split()
    for name in available:
        name_lower = name.lower()
        if all(word in name_lower for word in query_words):
            return name

    raise NavigationError(
        f"No dataset matching '{query}'. Available datasets:\n"
        + "\n".join(f"  - {name}" for name in available)
    )


def list_datasets(page: Page) -> list[str]:
    """Read available dataset names from the TableBuilder home page."""
    # Expand all dataset folders by clicking triangles
    triangles = page.query_selector_all(
        ".tree-toggle, .ui-tree-toggler, [class*='toggle']"
    )
    for triangle in triangles:
        try:
            triangle.click()
            page.wait_for_timeout(500)
        except Exception:
            continue

    # Collect dataset names (leaf nodes with cube icons or dataset class)
    dataset_elements = page.query_selector_all(
        ".dataset-name, .cube-icon + span, [class*='dataset'] span"
    )
    names = []
    for el in dataset_elements:
        text = (el.text_content() or "").strip()
        if text:
            names.append(text)

    if not names:
        # Fallback: grab all tree node labels
        tree_nodes = page.query_selector_all(
            ".ui-treenode-label, .tree-label, [role='treeitem']"
        )
        for node in tree_nodes:
            text = (node.text_content() or "").strip()
            if text and len(text) > 3:
                names.append(text)

    return names


def open_dataset(page: Page, dataset_query: str) -> None:
    """Find and open a dataset in TableBuilder, reaching Table View."""
    available = list_datasets(page)
    matched_name = fuzzy_match_dataset(dataset_query, available)

    # Double-click the matched dataset to open it
    dataset_el = page.get_by_text(matched_name, exact=True).first
    if not dataset_el:
        raise NavigationError(f"Found '{matched_name}' but cannot locate it in the UI.")

    dataset_el.dblclick()

    # Wait for Table View to load
    try:
        page.wait_for_selector(
            "text=Add to Row, text=Add to Column",
            timeout=15000,
        )
    except PlaywrightTimeout:
        raise NavigationError(
            f"Opened '{matched_name}' but Table View did not load. "
            "The dataset may be unavailable."
        )


def search_variable(page: Page, variable_name: str) -> None:
    """Use the dataset search box to find and highlight a variable."""
    search_input = page.query_selector(
        "input[placeholder*='Search'], input[class*='search']"
    )
    if not search_input:
        raise NavigationError("Cannot find the search box in the dataset panel.")

    search_input.fill("")
    search_input.fill(variable_name)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1000)
```

**Step 4: Run unit tests to verify they pass**

```bash
uv run pytest tests/test_navigator.py -v -m "not integration"
```

Expected: 5 passed

**Step 5: Commit**

```bash
git add src/tablebuilder/navigator.py tests/test_navigator.py tests/conftest.py
git commit -m "feat: add dataset navigator with fuzzy matching"
```

---

### Task 7: Table Builder (Variable Assignment)

**Files:**
- Create: `src/tablebuilder/table_builder.py`
- Create: `tests/test_table_builder.py`

This module adds variables to rows/cols/wafers in the TableBuilder UI. The complex part is interacting with the variable tree and the Add-to-axis buttons. Unit tests are limited here — most value comes from integration tests.

**Step 1: Write failing integration-only tests**

Create `tests/test_table_builder.py`:

```python
# ABOUTME: Tests for table construction (adding variables to rows/cols/wafers).
# ABOUTME: Primarily integration tests that drive the real TableBuilder UI.

import pytest

from tablebuilder.table_builder import add_variable, build_table, TableBuildError
from tablebuilder.models import Axis, TableRequest


class TestTableBuildError:
    def test_error_is_exception(self):
        """TableBuildError is a proper exception."""
        err = TableBuildError("test")
        assert str(err) == "test"
        assert isinstance(err, Exception)


@pytest.mark.integration
class TestAddVariableIntegration:
    def test_add_variable_to_row(self, abs_page_with_dataset):
        """Can add a variable to rows."""
        add_variable(abs_page_with_dataset, "Age", Axis.ROW)
        # Verify the variable appears in the row area
        assert abs_page_with_dataset.query_selector("text=Age")

    def test_add_variable_to_column(self, abs_page_with_dataset):
        """Can add a variable to columns."""
        add_variable(abs_page_with_dataset, "Sex", Axis.COL)
        assert abs_page_with_dataset.query_selector("text=Sex")


@pytest.mark.integration
class TestBuildTableIntegration:
    def test_build_simple_table(self, abs_page_with_dataset):
        """Can build a table with rows and columns."""
        request = TableRequest(
            dataset="Census 2021 Basic",
            rows=["Age"],
            cols=["Sex"],
        )
        build_table(abs_page_with_dataset, request)
```

Add to `tests/conftest.py` — append fixture:

```python
from tablebuilder.navigator import open_dataset


@pytest.fixture
def abs_page_with_dataset(abs_page):
    """Provide a page with a Census dataset already open."""
    open_dataset(abs_page, "Census 2021")
    yield abs_page
```

**Step 2: Write the implementation**

Create `src/tablebuilder/table_builder.py`:

```python
# ABOUTME: Table construction — add variables to rows, columns, and wafers.
# ABOUTME: Drives the TableBuilder UI to search variables, select categories, and assign axes.

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from tablebuilder.models import Axis, TableRequest
from tablebuilder.navigator import search_variable


class TableBuildError(Exception):
    """Raised when table construction fails."""


AXIS_BUTTON_TEXT = {
    Axis.ROW: "Add to Row",
    Axis.COL: "Add to Column",
    Axis.WAFER: "Add to Wafer",
}


def add_variable(page: Page, variable_name: str, axis: Axis) -> None:
    """Search for a variable, select all its categories, and add to the given axis."""
    search_variable(page, variable_name)

    # Find the variable in the tree and click to expand it
    var_node = page.get_by_text(variable_name).first
    if not var_node:
        raise TableBuildError(f"Variable '{variable_name}' not found in dataset.")

    var_node.click()
    page.wait_for_timeout(500)

    # Select all categories — look for a "Select all" checkbox or check all boxes
    select_all = page.query_selector(
        "input[type='checkbox'][title*='Select all'], "
        "input[type='checkbox'][aria-label*='Select all']"
    )
    if select_all:
        select_all.check()
    else:
        # Check individual category checkboxes
        checkboxes = page.query_selector_all(
            ".category-checkbox, input[type='checkbox']"
        )
        for cb in checkboxes:
            if not cb.is_checked():
                cb.check()

    page.wait_for_timeout(300)

    # Click the "Add to Row/Column/Wafer" button
    button_text = AXIS_BUTTON_TEXT[axis]
    try:
        button = page.get_by_text(button_text).first
        if not button:
            raise TableBuildError(f"Cannot find '{button_text}' button.")
        button.click()
        page.wait_for_timeout(1000)
    except PlaywrightTimeout:
        raise TableBuildError(
            f"Timed out clicking '{button_text}' for variable '{variable_name}'."
        )


def build_table(page: Page, request: TableRequest) -> None:
    """Add all variables from a TableRequest to their respective axes."""
    for var in request.rows:
        add_variable(page, var, Axis.ROW)

    for var in request.cols:
        add_variable(page, var, Axis.COL)

    for var in request.wafers:
        add_variable(page, var, Axis.WAFER)
```

**Step 3: Run unit tests**

```bash
uv run pytest tests/test_table_builder.py -v -m "not integration"
```

Expected: 1 passed (TestTableBuildError)

**Step 4: Run integration tests if available**

```bash
uv run pytest tests/test_table_builder.py -v -m "integration"
```

Expected: Either passed or skipped

**Step 5: Commit**

```bash
git add src/tablebuilder/table_builder.py tests/test_table_builder.py tests/conftest.py
git commit -m "feat: add table builder for assigning variables to axes"
```

---

### Task 8: Downloader (Queue, Wait, Download)

**Files:**
- Create: `src/tablebuilder/downloader.py`
- Create: `tests/test_downloader.py`

**Step 1: Write failing tests**

Create `tests/test_downloader.py`:

```python
# ABOUTME: Tests for table queue, status polling, and CSV download.
# ABOUTME: Unit tests for naming/timing; integration tests for real download flow.

from datetime import datetime

import pytest

from tablebuilder.downloader import generate_table_name, DownloadError


class TestGenerateTableName:
    def test_generates_timestamped_name(self):
        """Table names contain a timestamp."""
        name = generate_table_name()
        # Should start with "tb_" prefix
        assert name.startswith("tb_")
        # Should contain today's date
        today = datetime.now().strftime("%Y%m%d")
        assert today in name

    def test_names_are_unique(self):
        """Two calls produce different names."""
        name1 = generate_table_name()
        name2 = generate_table_name()
        assert name1 != name2


class TestDownloadError:
    def test_error_is_exception(self):
        """DownloadError is a proper exception."""
        err = DownloadError("timeout")
        assert str(err) == "timeout"


@pytest.mark.integration
class TestDownloaderIntegration:
    def test_queue_and_download(self, abs_page_with_table, tmp_path):
        """Can queue a table, wait for completion, and download CSV."""
        from tablebuilder.downloader import queue_and_download

        output = tmp_path / "test_output.csv"
        queue_and_download(abs_page_with_table, str(output), timeout=300)
        assert output.exists()
        content = output.read_text()
        assert len(content) > 0
```

Add to `tests/conftest.py` — append fixture:

```python
from tablebuilder.table_builder import build_table
from tablebuilder.models import TableRequest


@pytest.fixture
def abs_page_with_table(abs_page_with_dataset):
    """Provide a page with a simple table already built."""
    request = TableRequest(
        dataset="Census 2021 Basic",
        rows=["Sex"],
    )
    build_table(abs_page_with_dataset, request)
    yield abs_page_with_dataset
```

**Step 2: Run unit tests to verify they fail**

```bash
uv run pytest tests/test_downloader.py -v -m "not integration"
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/tablebuilder/downloader.py`:

```python
# ABOUTME: Queue tables, poll for completion, and download CSV results.
# ABOUTME: Handles format selection, queue submission, status polling, and zip extraction.

import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


class DownloadError(Exception):
    """Raised when table download fails."""


def generate_table_name() -> str:
    """Generate a unique table name with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = uuid4().hex[:6]
    return f"tb_{timestamp}_{short_id}"


def queue_and_download(
    page: Page,
    output_path: str,
    timeout: int = 600,
) -> None:
    """Select CSV format, queue the table, wait for completion, download."""
    table_name = generate_table_name()

    # Select CSV format from the dropdown
    format_dropdown = page.query_selector(
        "select[class*='format'], select[id*='format']"
    )
    if format_dropdown:
        format_dropdown.select_option(label="Comma Separated Value (.csv)")
    else:
        # Try clicking a format option directly
        csv_option = page.query_selector("text=CSV, text=Comma Separated")
        if csv_option:
            csv_option.click()

    page.wait_for_timeout(500)

    # Click "Queue table" button
    queue_button = page.get_by_text("Queue table").first
    if not queue_button:
        # Alternative text
        queue_button = page.get_by_text("Retrieve data").first
    if not queue_button:
        raise DownloadError("Cannot find the Queue/Retrieve button.")

    queue_button.click()
    page.wait_for_timeout(1000)

    # Enter table name in the dialog
    name_input = page.query_selector(
        "input[type='text']:visible, input[class*='table-name']"
    )
    if name_input:
        name_input.fill(table_name)

    # Confirm/OK
    ok_button = page.query_selector(
        "button:has-text('OK'), button:has-text('Save'), input[value='OK']"
    )
    if ok_button:
        ok_button.click()
    page.wait_for_timeout(2000)

    # Navigate to Saved and queued tables
    saved_link = page.query_selector(
        "text=Saved and queued tables, a:has-text('Saved')"
    )
    if saved_link:
        saved_link.click()
        page.wait_for_load_state("networkidle", timeout=10000)

    # Poll for completion
    poll_interval_ms = 5000
    elapsed_ms = 0
    max_ms = timeout * 1000

    while elapsed_ms < max_ms:
        # Look for "Completed" status next to our table name
        completed = page.query_selector(
            f"text=Completed >> .. >> text=download, "
            f"a:has-text('download')"
        )
        if completed:
            break

        page.wait_for_timeout(poll_interval_ms)
        elapsed_ms += poll_interval_ms
        page.reload()
        page.wait_for_load_state("networkidle", timeout=10000)
    else:
        raise DownloadError(
            f"Table did not complete within {timeout} seconds. "
            "Check 'Saved and queued tables' in TableBuilder manually."
        )

    # Download the file
    with page.expect_download(timeout=30000) as download_info:
        completed.click()

    download = download_info.value
    download_path = Path(download.path())

    # Extract if zip, otherwise copy directly
    output = Path(output_path)
    if zipfile.is_zipfile(download_path):
        with zipfile.ZipFile(download_path) as zf:
            csv_files = [f for f in zf.namelist() if f.endswith(".csv")]
            if not csv_files:
                raise DownloadError("Downloaded zip contains no CSV files.")
            zf.extract(csv_files[0], output.parent)
            extracted = output.parent / csv_files[0]
            extracted.rename(output)
    else:
        shutil.copy2(download_path, output)


def cleanup_saved_table(page: Page, table_name: str) -> None:
    """Delete a saved table from the queue to keep things tidy."""
    try:
        # Find the table row with our name and click delete
        table_row = page.get_by_text(table_name).first
        if table_row:
            delete_btn = table_row.locator(".. >> button:has-text('Delete')")
            if delete_btn.count() > 0:
                delete_btn.click()
                # Confirm deletion
                confirm = page.query_selector(
                    "button:has-text('OK'), button:has-text('Yes')"
                )
                if confirm:
                    confirm.click()
    except Exception:
        pass  # Cleanup failure is not critical
```

**Step 4: Run unit tests to verify they pass**

```bash
uv run pytest tests/test_downloader.py -v -m "not integration"
```

Expected: 3 passed

**Step 5: Commit**

```bash
git add src/tablebuilder/downloader.py tests/test_downloader.py tests/conftest.py
git commit -m "feat: add downloader with queue, poll, and CSV extraction"
```

---

### Task 9: Wire Everything Together in CLI

**Files:**
- Modify: `src/tablebuilder/cli.py`
- Create: `tests/test_integration.py`

**Step 1: Write the end-to-end integration test**

Create `tests/test_integration.py`:

```python
# ABOUTME: End-to-end integration tests for the full CLI flow.
# ABOUTME: Tests real browser automation against ABS TableBuilder.

import pytest
from click.testing import CliRunner

from tablebuilder.cli import cli


@pytest.mark.integration
class TestEndToEnd:
    def test_fetch_produces_csv(self, tmp_path, abs_config):
        """Full fetch command produces a CSV file."""
        output = tmp_path / "result.csv"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "fetch",
                "--dataset", "Census 2021",
                "--rows", "Sex",
                "--user-id", abs_config.user_id,
                "--password", abs_config.password,
                "-o", str(output),
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert output.exists()
        content = output.read_text()
        assert len(content) > 0

    def test_datasets_command(self, abs_config):
        """datasets command lists available datasets."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "datasets",
                "--user-id", abs_config.user_id,
                "--password", abs_config.password,
            ],
        )
        assert result.exit_code == 0
        assert "Census" in result.output
```

**Step 2: Update cli.py fetch command to wire everything together**

Modify `src/tablebuilder/cli.py` — replace the `fetch` function body (after parsing) and implement `datasets`:

```python
# The fetch function body becomes:
    from tablebuilder.browser import TableBuilderSession, LoginError
    from tablebuilder.navigator import open_dataset, NavigationError
    from tablebuilder.table_builder import build_table, TableBuildError
    from tablebuilder.downloader import queue_and_download, cleanup_saved_table, DownloadError

    try:
        with TableBuilderSession(config, headless=not headed) as page:
            click.echo("Logged in to TableBuilder.")

            click.echo(f"Opening dataset: {request.dataset}")
            open_dataset(page, request.dataset)

            click.echo("Building table...")
            build_table(page, request)

            click.echo(f"Queuing and downloading to {output}...")
            queue_and_download(page, output, timeout=timeout)

            click.echo(f"Done! CSV saved to {output}")

    except LoginError as e:
        click.echo(f"Login error: {e}", err=True)
        sys.exit(1)
    except NavigationError as e:
        click.echo(f"Navigation error: {e}", err=True)
        sys.exit(1)
    except TableBuildError as e:
        click.echo(f"Table build error: {e}", err=True)
        sys.exit(1)
    except DownloadError as e:
        click.echo(f"Download error: {e}", err=True)
        sys.exit(1)
```

**Step 3: Implement the datasets command**

```python
# The datasets function body becomes:
    try:
        config = load_config(user_id=user_id, password=password)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    from tablebuilder.browser import TableBuilderSession, LoginError
    from tablebuilder.navigator import list_datasets

    try:
        with TableBuilderSession(config, headless=True) as page:
            datasets_list = list_datasets(page)
            for name in sorted(datasets_list):
                click.echo(name)
    except LoginError as e:
        click.echo(f"Login error: {e}", err=True)
        sys.exit(1)
```

**Step 4: Run all unit tests**

```bash
uv run pytest -v -m "not integration"
```

Expected: All unit tests pass

**Step 5: Run integration tests if credentials available**

```bash
uv run pytest -v -m "integration" --timeout=120
```

Expected: Tests pass or skip

**Step 6: Commit**

```bash
git add src/tablebuilder/cli.py tests/test_integration.py
git commit -m "feat: wire all modules together in CLI fetch and datasets commands"
```

---

### Task 10: Integration Testing & Selector Tuning

**Files:**
- Modify: `src/tablebuilder/browser.py` (selectors as needed)
- Modify: `src/tablebuilder/navigator.py` (selectors as needed)
- Modify: `src/tablebuilder/table_builder.py` (selectors as needed)
- Modify: `src/tablebuilder/downloader.py` (selectors as needed)

This is the "make it actually work" task. The selectors in Tasks 5-8 are educated guesses based on ABS documentation. This task runs the tool with `--headed` to see the real UI and fixes selectors.

**Step 1: Set up credentials**

```bash
mkdir -p ~/.tablebuilder
cat > ~/.tablebuilder/.env << 'EOF'
TABLEBUILDER_USER_ID=YOUR_ID_HERE
TABLEBUILDER_PASSWORD=YOUR_PASSWORD_HERE
EOF
```

**Step 2: Run with --headed to observe the login flow**

```bash
uv run tablebuilder fetch --dataset "Census 2021" --rows "Sex" --headed -o /tmp/test.csv
```

Watch the browser. Note which selectors fail. Fix them in `browser.py`.

**Step 3: Fix selectors iteratively**

For each module, observe the actual DOM elements and update selectors:
- `browser.py`: Login form field selectors, submit button, error messages
- `navigator.py`: Dataset tree structure, folder expand triggers, dataset names
- `table_builder.py`: Variable tree, category checkboxes, Add-to-axis buttons
- `downloader.py`: Format dropdown, Queue button, table name input, download link

Use Playwright's `page.pause()` in headed mode to inspect elements interactively:
```python
# Temporarily add this to debug:
page.pause()  # Opens Playwright Inspector
```

**Step 4: Run the full integration test suite**

```bash
uv run pytest -v -m "integration"
```

**Step 5: Commit working selectors**

```bash
git add -A
git commit -m "fix: tune selectors for real ABS TableBuilder UI"
```

---

## Execution Notes

- **Tasks 1-4** are fully testable without ABS credentials (pure unit tests)
- **Tasks 5-8** have unit tests that work offline + integration tests needing credentials
- **Task 9** wires everything together
- **Task 10** is hands-on tuning that requires a real ABS account and visual inspection
- Run unit tests frequently: `uv run pytest -m "not integration" -v`
- Run integration tests when ready: `uv run pytest -m "integration" -v`
- Use `--headed` flag liberally during Task 10 for debugging
