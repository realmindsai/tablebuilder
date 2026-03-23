# Session Recovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically re-login when ABS TableBuilder session expires during batch dictionary extraction.

**Architecture:** Add a `relogin` callback parameter to `extract_all_datasets()`. Detect session expiration via a new `SessionExpiredError` raised when the dataset catalogue returns 0 datasets. On detection, call the callback to re-authenticate and retry the current dataset.

**Tech Stack:** Python, Playwright, Click CLI

---

### Task 1: Add `SessionExpiredError` to navigator

**Files:**
- Modify: `src/tablebuilder/navigator.py:19-20`
- Test: `tests/test_navigator.py`

**Step 1: Write failing test for SessionExpiredError**

Add to `tests/test_navigator.py`:

```python
from tablebuilder.navigator import SessionExpiredError

class TestSessionExpiredError:
    def test_is_navigation_error_subclass(self):
        """SessionExpiredError is a subclass of NavigationError."""
        err = SessionExpiredError("session died")
        assert isinstance(err, NavigationError)

    def test_message(self):
        """SessionExpiredError carries its message."""
        err = SessionExpiredError("session died")
        assert str(err) == "session died"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_navigator.py::TestSessionExpiredError -v`
Expected: FAIL with `ImportError: cannot import name 'SessionExpiredError'`

**Step 3: Add SessionExpiredError class**

In `src/tablebuilder/navigator.py`, after `NavigationError` (line 20):

```python
class SessionExpiredError(NavigationError):
    """Raised when the ABS session appears to have expired."""
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_navigator.py::TestSessionExpiredError -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tablebuilder/navigator.py tests/test_navigator.py
git commit -m "feat: add SessionExpiredError exception class"
```

---

### Task 2: Raise `SessionExpiredError` when catalogue is empty

**Files:**
- Modify: `src/tablebuilder/navigator.py:109-113` (inside `open_dataset`)
- Test: `tests/test_navigator.py`

**Step 1: Write failing test for empty catalogue detection**

Add to `tests/test_navigator.py`:

```python
from unittest.mock import MagicMock, patch

class TestOpenDatasetSessionExpiry:
    @patch("tablebuilder.navigator.list_datasets")
    def test_empty_catalogue_raises_session_expired(self, mock_list):
        """When list_datasets returns empty, open_dataset raises SessionExpiredError."""
        mock_list.return_value = []
        page = MagicMock()
        with pytest.raises(SessionExpiredError, match="Session expired"):
            from tablebuilder.navigator import open_dataset
            open_dataset(page, "Census 2021")

    @patch("tablebuilder.navigator.list_datasets")
    def test_nonempty_catalogue_raises_navigation_error(self, mock_list):
        """When catalogue has datasets but query doesn't match, raises NavigationError (not SessionExpiredError)."""
        mock_list.return_value = ["Labour Force", "CPI"]
        page = MagicMock()
        with pytest.raises(NavigationError) as exc_info:
            from tablebuilder.navigator import open_dataset
            open_dataset(page, "Census 2021")
        assert not isinstance(exc_info.value, SessionExpiredError)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_navigator.py::TestOpenDatasetSessionExpiry -v`
Expected: FAIL -- `open_dataset` raises `NavigationError` for both cases, not `SessionExpiredError`

**Step 3: Add empty-catalogue check to open_dataset**

In `src/tablebuilder/navigator.py`, inside `open_dataset()`, after `available = list_datasets(page, knowledge)` (line 112), add:

```python
    if not available:
        raise SessionExpiredError(
            "Session expired -- catalogue returned 0 datasets"
        )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_navigator.py::TestOpenDatasetSessionExpiry -v`
Expected: PASS

**Step 5: Run all navigator tests**

Run: `uv run pytest tests/test_navigator.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/tablebuilder/navigator.py tests/test_navigator.py
git commit -m "feat: raise SessionExpiredError when catalogue is empty"
```

---

### Task 3: Add `relogin()` public method to TableBuilderSession

**Files:**
- Modify: `src/tablebuilder/browser.py:26-49`
- Test: `tests/test_browser.py`

**Step 1: Write failing test for relogin method**

Add to `tests/test_browser.py`:

```python
class TestTableBuilderSessionRelogin:
    def test_relogin_method_exists(self):
        """TableBuilderSession has a public relogin() method."""
        config = Config(user_id="fake", password="fake")
        session = TableBuilderSession(config, headless=True)
        assert hasattr(session, "relogin")
        assert callable(session.relogin)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_browser.py::TestTableBuilderSessionRelogin -v`
Expected: FAIL with `AssertionError` (no `relogin` attribute)

**Step 3: Add relogin method**

In `src/tablebuilder/browser.py`, add to `TableBuilderSession` class after `__exit__`:

```python
    def relogin(self):
        """Re-authenticate the current browser session."""
        logger.info("Re-login requested")
        self._login()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_browser.py::TestTableBuilderSessionRelogin -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tablebuilder/browser.py tests/test_browser.py
git commit -m "feat: add relogin() public method to TableBuilderSession"
```

---

### Task 4: Add session recovery to `extract_all_datasets`

**Files:**
- Modify: `src/tablebuilder/tree_extractor.py:428-495`
- Test: `tests/test_tree_extractor.py`

**Step 1: Write failing tests for session recovery**

Add to `tests/test_tree_extractor.py`:

```python
from tablebuilder.navigator import SessionExpiredError

class TestExtractAllDatasetsSessionRecovery:
    @patch("tablebuilder.tree_extractor.navigate_back_to_catalogue")
    @patch("tablebuilder.tree_extractor.extract_dataset_tree")
    @patch("tablebuilder.tree_extractor.open_dataset")
    @patch("tablebuilder.tree_extractor.list_datasets")
    def test_relogin_called_on_session_expired(
        self, mock_list, mock_open, mock_extract, mock_nav_back, tmp_path
    ):
        """When open_dataset raises SessionExpiredError, relogin is called and dataset is retried."""
        mock_list.return_value = ["Dataset A", "Dataset B"]

        # First call to open_dataset raises SessionExpiredError, second succeeds
        mock_open.side_effect = [
            SessionExpiredError("session expired"),
            None,  # retry succeeds
            None,  # Dataset B succeeds
        ]
        mock_extract.return_value = DatasetTree(
            dataset_name="test", geographies=[], groups=[]
        )

        relogin = MagicMock()
        page = MagicMock()

        with patch("tablebuilder.tree_extractor.DEFAULT_CACHE_DIR", tmp_path / "cache"):
            with patch("tablebuilder.tree_extractor.DEFAULT_PROGRESS_PATH", tmp_path / "progress.json"):
                from tablebuilder.tree_extractor import extract_all_datasets
                extract_all_datasets(
                    page,
                    datasets=["Dataset A", "Dataset B"],
                    relogin=relogin,
                    resume=False,
                )

        relogin.assert_called_once()

    @patch("tablebuilder.tree_extractor.navigate_back_to_catalogue")
    @patch("tablebuilder.tree_extractor.extract_dataset_tree")
    @patch("tablebuilder.tree_extractor.open_dataset")
    @patch("tablebuilder.tree_extractor.list_datasets")
    def test_no_relogin_without_callback(
        self, mock_list, mock_open, mock_extract, mock_nav_back, tmp_path
    ):
        """When relogin is None, SessionExpiredError is handled as a regular failure."""
        mock_list.return_value = ["Dataset A"]
        mock_open.side_effect = SessionExpiredError("session expired")

        page = MagicMock()

        with patch("tablebuilder.tree_extractor.DEFAULT_CACHE_DIR", tmp_path / "cache"):
            with patch("tablebuilder.tree_extractor.DEFAULT_PROGRESS_PATH", tmp_path / "progress.json"):
                from tablebuilder.tree_extractor import extract_all_datasets
                result = extract_all_datasets(
                    page,
                    datasets=["Dataset A"],
                    relogin=None,
                    resume=False,
                )

        # Should not crash, dataset recorded as failed

    @patch("tablebuilder.tree_extractor.navigate_back_to_catalogue")
    @patch("tablebuilder.tree_extractor.extract_dataset_tree")
    @patch("tablebuilder.tree_extractor.open_dataset")
    @patch("tablebuilder.tree_extractor.list_datasets")
    def test_relogin_capped_at_max_attempts(
        self, mock_list, mock_open, mock_extract, mock_nav_back, tmp_path
    ):
        """Relogin is not attempted more than MAX_RELOGINS times."""
        mock_list.return_value = ["A", "B", "C", "D"]
        # Every open_dataset raises SessionExpiredError
        mock_open.side_effect = SessionExpiredError("session expired")

        relogin = MagicMock()
        page = MagicMock()

        with patch("tablebuilder.tree_extractor.DEFAULT_CACHE_DIR", tmp_path / "cache"):
            with patch("tablebuilder.tree_extractor.DEFAULT_PROGRESS_PATH", tmp_path / "progress.json"):
                from tablebuilder.tree_extractor import extract_all_datasets
                extract_all_datasets(
                    page,
                    datasets=["A", "B", "C", "D"],
                    relogin=relogin,
                    resume=False,
                )

        # Should cap at MAX_RELOGINS (2)
        assert relogin.call_count <= 2
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tree_extractor.py::TestExtractAllDatasetsSessionRecovery -v`
Expected: FAIL -- `extract_all_datasets` doesn't accept `relogin` parameter

**Step 3: Implement session recovery in extract_all_datasets**

In `src/tablebuilder/tree_extractor.py`:

1. Add import at top:
```python
from collections.abc import Callable
from tablebuilder.navigator import SessionExpiredError
```

2. Add constant:
```python
MAX_RELOGINS = 2
```

3. Modify `extract_all_datasets` signature to add `relogin`:
```python
def extract_all_datasets(
    page: Page,
    datasets: list[str] | None = None,
    exclude_census: bool = True,
    resume: bool = True,
    knowledge=None,
    relogin: Callable[[], None] | None = None,
) -> list[DatasetTree]:
```

4. Add `relogin_attempts = 0` before the loop.

5. Replace the try/except block inside the for loop with:
```python
        try:
            open_dataset(page, name, knowledge)
            tree = extract_dataset_tree(page, name, knowledge)
            _save_tree_cache(tree, cache_dir)
            trees.append(tree)
            progress["completed"].append(name)
            _save_progress(progress, progress_path)
            logger.info("Successfully extracted '%s'", name)
        except SessionExpiredError:
            if relogin and relogin_attempts < MAX_RELOGINS:
                relogin_attempts += 1
                logger.warning(
                    "Session expired, re-logging in (attempt %d/%d)",
                    relogin_attempts,
                    MAX_RELOGINS,
                )
                relogin()
                # Retry this dataset after relogin
                try:
                    open_dataset(page, name, knowledge)
                    tree = extract_dataset_tree(page, name, knowledge)
                    _save_tree_cache(tree, cache_dir)
                    trees.append(tree)
                    progress["completed"].append(name)
                    _save_progress(progress, progress_path)
                    logger.info("Successfully extracted '%s' after relogin", name)
                except Exception as exc2:
                    logger.warning("Failed to extract '%s' after relogin: %s", name, exc2)
                    progress["failed"][name] = str(exc2)
                    _save_progress(progress, progress_path)
            else:
                logger.warning("Failed to extract '%s': session expired (no relogin available or max attempts reached)", name)
                progress["failed"][name] = "Session expired"
                _save_progress(progress, progress_path)
        except Exception as exc:
            logger.warning("Failed to extract '%s': %s", name, exc)
            progress["failed"][name] = str(exc)
            _save_progress(progress, progress_path)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tree_extractor.py::TestExtractAllDatasetsSessionRecovery -v`
Expected: PASS

**Step 5: Run all tree_extractor tests**

Run: `uv run pytest tests/test_tree_extractor.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/tablebuilder/tree_extractor.py tests/test_tree_extractor.py
git commit -m "feat: add session recovery to extract_all_datasets"
```

---

### Task 5: Wire up relogin callback in CLI

**Files:**
- Modify: `src/tablebuilder/cli.py:196-226`
- Test: `tests/test_cli.py`

**Step 1: Write failing test**

The CLI wiring is thin -- just passing the callback. A unit test confirms the session object is used correctly:

Add to `tests/test_cli.py`:

```python
from unittest.mock import patch, MagicMock

class TestCliDictionaryRelogin:
    @patch("tablebuilder.cli.load_config")
    @patch("tablebuilder.cli.TableBuilderSession")
    @patch("tablebuilder.cli.extract_all_datasets")
    @patch("tablebuilder.cli.format_data_dictionary", return_value="# Dict")
    def test_dictionary_batch_passes_relogin(
        self, mock_fmt, mock_extract, mock_session_cls, mock_config
    ):
        """Batch dictionary extraction passes session.relogin to extract_all_datasets."""
        mock_config.return_value = MagicMock()
        mock_session = MagicMock()
        mock_page = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_page)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_cls.return_value = mock_session
        mock_extract.return_value = []

        runner = CliRunner()
        result = runner.invoke(cli, ["dictionary", "-o", "/tmp/test_dict.md"])

        mock_extract.assert_called_once()
        call_kwargs = mock_extract.call_args
        assert call_kwargs.kwargs.get("relogin") == mock_session.relogin or \
               (len(call_kwargs.args) > 0 or "relogin" in str(call_kwargs))
```

Note: This test requires adjusting the imports in `cli.py` to be at the top level for patching to work. Since the current code does lazy imports inside the function, we need to patch at the module level where they're used. The test patches `tablebuilder.cli.TableBuilderSession` etc.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::TestCliDictionaryRelogin -v`
Expected: FAIL -- imports are inside the function, patching may not work as expected. Adjust patches to match the lazy import pattern.

**Step 3: Update CLI to pass relogin callback**

In `src/tablebuilder/cli.py`, modify the `dictionary` command's batch mode section (around line 213-221):

Change:
```python
            else:
                # Batch mode
                click.echo("Extracting data dictionary for all datasets...")
                trees = extract_all_datasets(
                    page,
                    exclude_census=exclude_census,
                    resume=resume,
                    knowledge=knowledge,
                )
```

To (also change `with` to store the session):
```python
    try:
        session = TableBuilderSession(config, headless=not headed, knowledge=knowledge)
        with session as page:
            click.echo("Logged in to TableBuilder.")

            if dataset:
                # Single dataset mode (unchanged)
                ...
            else:
                # Batch mode
                click.echo("Extracting data dictionary for all datasets...")
                trees = extract_all_datasets(
                    page,
                    exclude_census=exclude_census,
                    resume=resume,
                    knowledge=knowledge,
                    relogin=session.relogin,
                )
```

**Step 4: Run all CLI tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/tablebuilder/cli.py tests/test_cli.py
git commit -m "feat: wire relogin callback into dictionary batch extraction"
```

---

### Task 6: Run full test suite and verify

**Files:** None (verification only)

**Step 1: Run full test suite**

Run: `uv run pytest --ignore=tests/test_integration.py -v`
Expected: All PASS (140+ tests)

**Step 2: Verify no regressions**

Run: `uv run pytest --ignore=tests/test_integration.py -q`
Expected: All pass, 0 failures

**Step 3: Final commit if any cleanup needed**

```bash
git status
```
