# Census Geography Selection - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `--geography` and `--geo-filter` flags to the `fetch` command so Census geography (remoteness areas, states, etc.) can be selected without custom scripts.

**Architecture:** Two new optional fields on `TableRequest`, a new `select_geography()` function in `table_builder.py` that navigates the Census geography tree (expand group, click level, expand state, check categories, submit axis), and updated CLI validation. Geography is processed before variables in `build_table()`.

**Tech Stack:** Python, Click CLI, Playwright (browser automation), pytest

---

### Task 1: Model - Add geography fields and tests

**Files:**
- Modify: `src/tablebuilder/models.py:14-27`
- Test: `tests/test_models.py`

**Step 1: Write the failing tests**

Add to `tests/test_models.py`:

```python
class TestTableRequestGeography:
    def test_geography_only_valid(self):
        """A request with dataset and geography (no rows) is valid."""
        req = TableRequest(
            dataset="Census 2021",
            rows=[],
            geography="Remoteness Areas",
        )
        assert req.geography == "Remoteness Areas"
        assert req.geo_filter is None

    def test_geo_filter_without_geography_raises(self):
        """geo_filter without geography raises ValueError."""
        with pytest.raises(ValueError, match="geo_filter"):
            TableRequest(
                dataset="Census 2021",
                rows=["Age"],
                geo_filter="South Australia",
            )

    def test_no_rows_no_geography_raises(self):
        """Neither rows nor geography raises ValueError."""
        with pytest.raises(ValueError, match="rows.*geography"):
            TableRequest(
                dataset="Census 2021",
                rows=[],
            )
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py::TestTableRequestGeography -v`
Expected: FAIL — `TypeError` because `geography` field doesn't exist yet.

**Step 3: Update the model**

In `src/tablebuilder/models.py`, change `TableRequest` to:

```python
@dataclass
class TableRequest:
    """Describes a table to fetch from ABS TableBuilder."""

    dataset: str
    rows: list[str] = field(default_factory=list)
    cols: list[str] = field(default_factory=list)
    wafers: list[str] = field(default_factory=list)
    geography: str | None = None
    geo_filter: str | None = None

    def __post_init__(self):
        if not self.dataset or not self.dataset.strip():
            raise ValueError("dataset name cannot be empty")
        if self.geo_filter and not self.geography:
            raise ValueError("geo_filter requires geography to be set")
        if not self.rows and not self.geography:
            raise ValueError("rows must contain at least one variable, or geography must be set")
```

Note: `rows` default changes from no-default to `field(default_factory=list)` so geography-only requests work.

**Step 4: Fix existing test that expects TypeError for missing rows**

In `tests/test_models.py`, update `test_rejects_no_rows`:

```python
def test_rejects_no_rows(self):
    """Missing rows without geography raises ValueError."""
    with pytest.raises(ValueError, match="rows.*geography"):
        TableRequest(dataset="Census 2021 Basic", rows=[])
```

And `test_rejects_empty_rows` should now match the new message too:

```python
def test_rejects_empty_rows(self):
    """Empty rows without geography raises ValueError."""
    with pytest.raises(ValueError, match="rows.*geography"):
        TableRequest(dataset="Census 2021 Basic", rows=[])
```

Note: `test_rejects_no_rows` previously expected `TypeError` from missing positional arg. Now `rows` has a default, so it becomes a `ValueError` from validation. Merge it with `test_rejects_empty_rows` or update both.

**Step 5: Run all model tests**

Run: `uv run pytest tests/test_models.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/tablebuilder/models.py tests/test_models.py
git commit -m "feat: add geography and geo_filter fields to TableRequest"
```

---

### Task 2: Geography selection logic - Core function with error cases

**Files:**
- Modify: `src/tablebuilder/table_builder.py`
- Test: `tests/test_table_builder.py`

**Step 1: Write the failing tests**

Add to `tests/test_table_builder.py`. These tests mock the Playwright page object to simulate the Census geography tree DOM. The mock needs to simulate:
- `query_selector_all('.treeNodeElement .label')` returning label elements
- Label elements having `.text_content()` and `.evaluate_handle()` methods
- Expander elements with `get_attribute('class')` and `.click()`
- Checkbox elements with `is_checked()` and `.click()`

```python
from unittest.mock import MagicMock, patch

from tablebuilder.table_builder import select_geography, TableBuildError


def _make_tree_node(label_text, is_leaf=False, has_checkbox=False, collapsed=False, children=None):
    """Helper: build a mock tree node element."""
    node = MagicMock()
    label = MagicMock()
    label.text_content.return_value = label_text
    node.query_selector.side_effect = lambda sel: {
        '.label': label,
        '.treeNodeExpander': _make_expander(is_leaf, collapsed),
        'input[type=checkbox]': _make_checkbox() if has_checkbox else None,
    }.get(sel)
    return node


def _make_expander(is_leaf=False, collapsed=False):
    exp = MagicMock()
    cls = 'treeNodeExpander'
    if is_leaf:
        cls += ' leaf'
    if collapsed:
        cls += ' collapsed'
    exp.get_attribute.return_value = cls
    exp.click = MagicMock()
    return exp


def _make_checkbox(checked=False):
    cb = MagicMock()
    cb.is_checked.return_value = checked
    cb.click = MagicMock()
    return cb


class TestSelectGeographyErrors:
    def test_missing_group_raises(self):
        """TableBuildError when no 'Geographical Areas' group in tree."""
        page = MagicMock()
        page.query_selector_all.return_value = []
        page.wait_for_timeout = MagicMock()

        with pytest.raises(TableBuildError, match="No geography group found"):
            select_geography(page, "Remoteness Areas")

    def test_missing_level_raises(self):
        """TableBuildError when geography level not found under group."""
        page = MagicMock()
        # Return a geography group label but no children matching the level
        geo_label = MagicMock()
        geo_label.text_content.return_value = "Geographical Areas (Usual Residence)"
        other_label = MagicMock()
        other_label.text_content.return_value = "Age and Sex"

        page.query_selector_all.return_value = [geo_label, other_label]
        page.wait_for_timeout = MagicMock()

        # After expanding, no children match "Remoteness Areas"
        geo_node = MagicMock()
        geo_label.evaluate_handle.return_value = geo_node
        geo_node.as_element.return_value = geo_node
        expander = MagicMock()
        expander.get_attribute.return_value = 'treeNodeExpander collapsed'
        geo_node.query_selector.return_value = expander

        with pytest.raises(TableBuildError, match="geography level"):
            select_geography(page, "Nonexistent Level")

    def test_missing_filter_raises(self):
        """TableBuildError when geo_filter state not found."""
        page = MagicMock()
        page.wait_for_timeout = MagicMock()

        # Simulate: geo group found, level found and clicked, but no matching state
        geo_label = MagicMock()
        geo_label.text_content.return_value = "Geographical Areas (Usual Residence)"
        level_label = MagicMock()
        level_label.text_content.return_value = "Remoteness Areas (UR)"

        page.query_selector_all.return_value = [geo_label, level_label]

        with pytest.raises(TableBuildError, match="state.*not found"):
            select_geography(page, "Remoteness Areas", geo_filter="Nonexistent State")
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_table_builder.py::TestSelectGeographyErrors -v`
Expected: FAIL — `ImportError` because `select_geography` doesn't exist yet.

**Step 3: Write the select_geography function**

Add to `src/tablebuilder/table_builder.py`:

```python
def _find_geography_group(page):
    """Find and expand the 'Geographical Areas...' top-level group.

    Returns the list of child label elements after expansion.
    Raises TableBuildError if no geography group found.
    """
    labels = page.query_selector_all('.treeNodeElement .label')
    geo_label = None
    for lbl in labels:
        text = (lbl.text_content() or '').strip()
        if text.startswith("Geographical Areas"):
            geo_label = lbl
            break

    if not geo_label:
        raise TableBuildError(
            "No geography group found. This dataset may not support geography selection."
        )

    # Expand the geography group if collapsed
    node = geo_label.evaluate_handle('el => el.closest(".treeNodeElement")')
    expander = node.as_element().query_selector('.treeNodeExpander')
    if expander and 'collapsed' in (expander.get_attribute('class') or ''):
        expander.click()
        page.wait_for_timeout(3000)

    logger.debug("Geography group expanded")
    return geo_label


def _find_geography_level(page, level_name):
    """Find and click a geography level label (e.g., 'Remoteness Areas').

    Fuzzy-matches: the level label must contain level_name as a substring.
    Returns the matched label element.
    Raises TableBuildError if not found, listing available levels.
    """
    labels = page.query_selector_all('.treeNodeElement .label')
    available_levels = []
    matched_label = None

    for lbl in labels:
        text = (lbl.text_content() or '').strip()
        if text.startswith("Geographical Areas"):
            continue
        # Geography levels are children of the geo group, before variable groups
        # They have suffixes like "(UR)" or "(POE)"
        if '(' in text and text.endswith(')'):
            available_levels.append(text)
            if level_name.lower() in text.lower() and matched_label is None:
                matched_label = lbl

    if not matched_label:
        level_list = "\n".join(f"  - {l}" for l in available_levels)
        raise TableBuildError(
            f"Geography level '{level_name}' not found. "
            f"Available levels:\n{level_list}"
        )

    # Click the level to populate state nodes
    matched_label.click()
    page.wait_for_timeout(5000)
    logger.debug("Geography level '%s' selected", level_name)
    return matched_label


def _find_and_check_states(page, geo_filter=None):
    """Expand state nodes and check their leaf category checkboxes.

    If geo_filter is set, only expand and check that state.
    Otherwise, expand all states and check all categories.
    Returns total number of checked checkboxes.
    Raises TableBuildError if geo_filter state not found or zero checked.
    """
    nodes = page.query_selector_all('.treeNodeElement')
    all_nodes = list(nodes)

    # Find state nodes: non-leaf nodes with checkboxes
    state_nodes = []
    for node in all_nodes:
        label_el = node.query_selector('.label')
        expander = node.query_selector('.treeNodeExpander')
        cb = node.query_selector('input[type=checkbox]')
        if not label_el or not expander or not cb:
            continue
        if 'leaf' in (expander.get_attribute('class') or ''):
            continue
        label_text = (label_el.text_content() or '').strip()
        if label_text:
            state_nodes.append((label_text, node, expander))

    if geo_filter:
        # Find the matching state
        matched = None
        for label_text, node, expander in state_nodes:
            if geo_filter.lower() in label_text.lower():
                matched = (label_text, node, expander)
                break
        if not matched:
            state_list = "\n".join(f"  - {s[0]}" for s in state_nodes)
            raise TableBuildError(
                f"Geography state/region '{geo_filter}' not found. "
                f"Available:\n{state_list}"
            )
        states_to_expand = [matched]
    else:
        states_to_expand = state_nodes

    total_checked = 0
    for label_text, node, expander in states_to_expand:
        if 'collapsed' in (expander.get_attribute('class') or ''):
            expander.click()
            page.wait_for_timeout(2000)
        logger.debug("Expanded state: %s", label_text)

    # Re-query after expansion to get updated DOM
    nodes = page.query_selector_all('.treeNodeElement')
    for node in nodes:
        expander = node.query_selector('.treeNodeExpander')
        if not expander or 'leaf' not in (expander.get_attribute('class') or ''):
            continue
        cb = node.query_selector('input[type=checkbox]')
        if cb and not cb.is_checked():
            cb.click()
            page.wait_for_timeout(200)
        if cb:
            total_checked += 1

    if total_checked == 0:
        raise TableBuildError("No geography categories found to check.")

    logger.debug("Checked %d geography categories", total_checked)
    return total_checked


def select_geography(page, geography, geo_filter=None, knowledge=None):
    """Select a Census geography level and check its categories.

    Expands the 'Geographical Areas' group, clicks the geography level,
    optionally filters to a state, checks leaf checkboxes, and submits
    to the row axis.
    """
    logger.info(
        "Selecting geography '%s'%s",
        geography,
        f" filtered to '{geo_filter}'" if geo_filter else "",
    )

    _find_geography_group(page)
    _find_geography_level(page, geography)
    checked = _find_and_check_states(page, geo_filter)

    # Submit to rows
    _submit_axis_button(page, Axis.ROW)

    logger.info("Geography added to rows (%d categories)", checked)
```

**Step 4: Run the error tests**

Run: `uv run pytest tests/test_table_builder.py::TestSelectGeographyErrors -v`
Expected: Tests may need mock adjustments. Iterate until the 3 error tests pass.

**Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: ALL PASS (existing tests unaffected)

**Step 6: Commit**

```bash
git add src/tablebuilder/table_builder.py tests/test_table_builder.py
git commit -m "feat: add select_geography() for Census geography selection"
```

---

### Task 3: Integrate geography into build_table()

**Files:**
- Modify: `src/tablebuilder/table_builder.py:141-153`
- Test: `tests/test_table_builder.py`

**Step 1: Write the failing test**

Add to `tests/test_table_builder.py`:

```python
class TestBuildTableWithGeography:
    @patch('tablebuilder.table_builder.select_geography')
    @patch('tablebuilder.table_builder.add_variable')
    def test_geography_called_before_variables(self, mock_add_var, mock_select_geo):
        """build_table calls select_geography before add_variable."""
        call_order = []
        mock_select_geo.side_effect = lambda *a, **kw: call_order.append('geo')
        mock_add_var.side_effect = lambda *a, **kw: call_order.append('var')

        page = MagicMock()
        request = TableRequest(
            dataset="Census 2021",
            rows=["SEXP Sex"],
            geography="Remoteness Areas",
            geo_filter="South Australia",
        )
        build_table(page, request)

        assert call_order == ['geo', 'var']
        mock_select_geo.assert_called_once_with(
            page, "Remoteness Areas", "South Australia", None
        )

    @patch('tablebuilder.table_builder.select_geography')
    def test_geography_only_no_variables(self, mock_select_geo):
        """build_table works with geography and no row variables."""
        page = MagicMock()
        request = TableRequest(
            dataset="Census 2021",
            geography="Remoteness Areas",
        )
        build_table(page, request)
        mock_select_geo.assert_called_once()

    @patch('tablebuilder.table_builder.add_variable')
    def test_no_geography_skips_select(self, mock_add_var):
        """build_table without geography doesn't call select_geography."""
        page = MagicMock()
        request = TableRequest(
            dataset="Census 2021",
            rows=["SEXP Sex"],
        )
        build_table(page, request)
        mock_add_var.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_table_builder.py::TestBuildTableWithGeography -v`
Expected: FAIL — `build_table` doesn't call `select_geography` yet.

**Step 3: Update build_table()**

In `src/tablebuilder/table_builder.py`, change `build_table` to:

```python
def build_table(page: Page, request: TableRequest, knowledge=None) -> None:
    """Add all variables from a TableRequest to their respective axes."""
    logger.info("Building table for dataset '%s'", request.dataset)

    if request.geography:
        select_geography(page, request.geography, request.geo_filter, knowledge)

    for var in request.rows:
        add_variable(page, var, Axis.ROW, knowledge)

    for var in request.cols:
        add_variable(page, var, Axis.COL, knowledge)

    for var in request.wafers:
        add_variable(page, var, Axis.WAFER, knowledge)

    logger.info("Table build complete")
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_table_builder.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/tablebuilder/table_builder.py tests/test_table_builder.py
git commit -m "feat: integrate select_geography into build_table pipeline"
```

---

### Task 4: CLI - Add --geography and --geo-filter flags

**Files:**
- Modify: `src/tablebuilder/cli.py:25-68`
- Test: `tests/test_cli.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestCliFetchGeography:
    def test_fetch_help_shows_geography(self):
        """fetch --help lists --geography and --geo-filter."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--help"])
        assert result.exit_code == 0
        assert "--geography" in result.output
        assert "--geo-filter" in result.output

    def test_geo_filter_without_geography_errors(self):
        """--geo-filter without --geography shows error."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "fetch",
            "--dataset", "Census 2021",
            "--geo-filter", "South Australia",
        ])
        assert result.exit_code != 0
        assert "geography" in result.output.lower() or "geography" in (result.exception and str(result.exception) or "").lower()

    def test_geography_without_rows_accepted(self):
        """--geography without --rows is accepted (no CLI error)."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--help"])
        # Verify --rows is not marked as required in help text
        # (actual execution would need mocked browser)
        assert "--rows" in result.output
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestCliFetchGeography -v`
Expected: FAIL — `--geography` not in help output.

**Step 3: Update the CLI**

In `src/tablebuilder/cli.py`, modify the `fetch` command:

```python
@cli.command()
@click.option("--dataset", required=True, help="Dataset name (fuzzy-matched).")
@click.option(
    "--rows", multiple=True, help="Variable(s) to place in rows."
)
@click.option("--cols", multiple=True, help="Variable(s) to place in columns.")
@click.option("--wafers", multiple=True, help="Variable(s) to place in wafers.")
@click.option(
    "--geography", default=None,
    help='Geography level for Census datasets (e.g., "Remoteness Areas").',
)
@click.option(
    "--geo-filter", default=None,
    help='Filter geography to a state/region (e.g., "South Australia"). Requires --geography.',
)
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
@click.pass_context
def fetch(ctx, dataset, rows, cols, wafers, geography, geo_filter, output, headed, user_id, password, timeout):
    """Fetch a table from ABS TableBuilder and download as CSV."""
    knowledge = ctx.obj['knowledge']
    knowledge.record_run()

    # Validate geography flags
    if geo_filter and not geography:
        click.echo("Error: --geo-filter requires --geography.", err=True)
        sys.exit(1)
    if not rows and not geography:
        click.echo("Error: --rows or --geography is required.", err=True)
        sys.exit(1)

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
        geography=geography,
        geo_filter=geo_filter,
    )

    if output is None:
        output = f"tablebuilder_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    click.echo(f"Dataset: {request.dataset}")
    if request.geography:
        click.echo(f"Geography: {request.geography}")
        if request.geo_filter:
            click.echo(f"Geo filter: {request.geo_filter}")
    if request.rows:
        click.echo(f"Rows: {', '.join(request.rows)}")
    if request.cols:
        click.echo(f"Cols: {', '.join(request.cols)}")
    if request.wafers:
        click.echo(f"Wafers: {', '.join(request.wafers)}")
    click.echo(f"Output: {output}")

    # ... rest unchanged (imports and try/except block remain the same)
```

Note: `--rows` changes from `required=True` to no requirement. Validation is done manually in the function body.

**Step 4: Run tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: ALL PASS. Also check that `test_fetch_requires_rows` needs updating since `--rows` is no longer unconditionally required.

Update `test_fetch_requires_rows`:

```python
def test_fetch_requires_rows_or_geography(self):
    """fetch without --rows or --geography exits with error."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["fetch", "--dataset", "Census 2021 Basic"]
    )
    assert result.exit_code != 0
```

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/tablebuilder/cli.py tests/test_cli.py
git commit -m "feat: add --geography and --geo-filter flags to fetch command"
```

---

### Task 5: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add geography examples to Common Commands section**

Add under the existing fetch example:

```markdown
# Fetch with Census geography
uv run tablebuilder fetch --dataset "2021 Census - cultural diversity" --geography "Remoteness Areas" --geo-filter "South Australia" -o sa_remoteness.csv

# Fetch all states by remoteness
uv run tablebuilder fetch --dataset "2021 Census - cultural diversity" --geography "Remoteness Areas" -o all_remoteness.csv
```

**Step 2: Add geography note to Key Technical Details**

Add a new subsection:

```markdown
### Census Geography Selection
Census datasets have geography as a separate tree section ("Geographical Areas..."), not as regular variables. The `--geography` flag triggers special handling: expand the geography group, click the level, expand state nodes, check leaf checkboxes. The `--geo-filter` flag narrows to a specific state. Geography is always added to rows before any `--rows` variables.
```

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Census geography selection to CLAUDE.md"
```

---

### Task 6: Integration test

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Add the integration test**

```python
@pytest.mark.integration
class TestGeographyIntegration:
    def test_fetch_sa_remoteness(self, abs_page_with_dataset):
        """Can fetch SA population by remoteness from Census 2021."""
        from tablebuilder.table_builder import select_geography

        select_geography(
            abs_page_with_dataset,
            "Remoteness Areas",
            geo_filter="South Australia",
        )
        # Verify table is not empty
        page_text = abs_page_with_dataset.evaluate(
            "() => document.body.innerText.substring(0, 500)"
        )
        assert "Your table is empty" not in page_text
```

**Step 2: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add Census geography integration test"
```

---

### Task 7: End-to-end verification

**Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS (integration tests skipped without credentials)

**Step 2: Manual smoke test with real ABS credentials**

Run:
```bash
uv run tablebuilder fetch \
  --dataset "2021 Census - cultural diversity" \
  --geography "Remoteness Areas" \
  --geo-filter "South Australia" \
  --headed \
  -o test_sa_remoteness.csv
```

Expected: CSV file with SA remoteness categories matching the data we fetched earlier (Major Cities ~1.34M, Total ~1.78M).

**Step 3: Clean up test output**

```bash
rm -f test_sa_remoteness.csv
```

**Step 4: Final commit if any adjustments needed**

```bash
git add -A && git commit -m "fix: adjustments from end-to-end geography testing"
```
