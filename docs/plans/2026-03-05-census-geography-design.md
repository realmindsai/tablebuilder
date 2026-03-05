# Census Geography Selection for `fetch` Command

## Problem

Census datasets in ABS TableBuilder use geography as a separate tree section, not as regular searchable variables. The current `fetch` command only handles regular variables. Every Census geography query requires a custom script.

## Decision

Add two opt-in CLI flags (`--geography`, `--geo-filter`) and a new `select_geography()` function to handle Census geography selection within the existing `fetch` pipeline.

## CLI Interface

Two new options on `fetch`:

```
--geography TEXT    Geography level (e.g., "Remoteness Areas"). Census datasets only.
--geo-filter TEXT   Filter geography to a state/region (e.g., "South Australia").
                    Requires --geography. Omit to select all.
```

Validation:
- `--geo-filter` without `--geography` raises an error.
- `--geography` without `--rows` is allowed (geography alone is a valid table).
- `--geography` with `--rows` processes geography first, then variables.
- `--rows` is required unless `--geography` is provided.

Example usage:

```bash
# SA remoteness only
uv run tablebuilder fetch \
  --dataset "2021 Census - cultural diversity" \
  --geography "Remoteness Areas" \
  --geo-filter "South Australia" \
  -o sa_remoteness.csv

# All states x remoteness
uv run tablebuilder fetch \
  --dataset "2021 Census - cultural diversity" \
  --geography "Remoteness Areas" \
  -o all_remoteness.csv

# Geography + variable cross-tab
uv run tablebuilder fetch \
  --dataset "2021 Census - cultural diversity" \
  --geography "Remoteness Areas" \
  --geo-filter "South Australia" \
  --rows "SEXP Sex" \
  -o sa_remoteness_by_sex.csv
```

## Data Model

Add two optional fields to `TableRequest` in `models.py`:

```python
@dataclass
class TableRequest:
    dataset: str
    rows: list[str]
    cols: list[str] = field(default_factory=list)
    wafers: list[str] = field(default_factory=list)
    geography: str | None = None
    geo_filter: str | None = None
```

Validation in `__post_init__`:
- `geo_filter` set without `geography` raises `ValueError`.
- Neither `rows` nor `geography` provided raises `ValueError`.

## Geography Selection Logic

New function `select_geography()` in `table_builder.py`.

### Flow

1. **Find geography group** -- scan top-level tree nodes for one starting with "Geographical Areas", expand it.
2. **Find geography level** -- fuzzy-match `--geography` value against expanded children (they have suffixes like "(UR)", so match on substring).
3. **Click the geography level label** -- populates child state nodes.
4. **If `--geo-filter` is set:** find the matching state node, expand it, check all leaf checkboxes under that state.
5. **If no `--geo-filter`:** expand all state nodes, check all leaf checkboxes under every state.
6. **Submit the row axis button.**

### Fuzzy Matching

- Geography group: first tree node whose label starts with "Geographical Areas".
- Geography level: first child whose label contains the `--geography` value.
- Geo filter: first state node whose label equals or contains the `--geo-filter` value.

### Error Cases

- No "Geographical Areas" group found: `TableBuildError("No geography group found. This dataset may not support geography selection.")`.
- Geography level not found: `TableBuildError` listing available levels.
- Geo filter state not found: `TableBuildError` listing available states.
- Zero checkboxes checked: `TableBuildError`.

## Integration into build_table()

Geography is processed before variables:

```python
def build_table(page, request, knowledge=None):
    if request.geography:
        select_geography(page, request.geography, request.geo_filter, knowledge)
    for var in request.rows:
        add_variable(page, var, Axis.ROW, knowledge)
    for var in request.cols:
        add_variable(page, var, Axis.COL, knowledge)
    for var in request.wafers:
        add_variable(page, var, Axis.WAFER, knowledge)
```

Geography goes first because it modifies the tree structure and the variable search happens after.

## Files Touched

1. `models.py` -- add `geography` and `geo_filter` fields to `TableRequest`
2. `table_builder.py` -- add `select_geography()`, update `build_table()`
3. `cli.py` -- add `--geography` and `--geo-filter` options, relax `--rows` requirement
4. `tests/test_table_builder.py` -- 7 new geography tests
5. `tests/test_cli.py` -- 3 new CLI validation tests
6. `tests/test_models.py` -- 3 new model tests
7. `tests/test_integration.py` -- 1 new integration test

## Testing

### Unit tests (mocked Playwright page)

- `test_select_geography_expands_group` -- finds and expands "Geographical Areas..." node
- `test_select_geography_clicks_level` -- fuzzy matches level label with "(UR)" suffix
- `test_select_geography_with_filter` -- only filtered state's checkboxes checked
- `test_select_geography_without_filter` -- all states expanded, all checkboxes checked
- `test_select_geography_missing_group` -- `TableBuildError` when no geography group
- `test_select_geography_missing_level` -- `TableBuildError` listing available levels
- `test_select_geography_missing_filter` -- `TableBuildError` listing available states

### CLI validation tests

- `test_geo_filter_without_geography_errors`
- `test_geography_without_rows_valid`
- `test_geography_with_rows_valid`

### Model tests

- `test_table_request_geo_filter_without_geography_raises`
- `test_table_request_no_rows_no_geography_raises`
- `test_table_request_geography_only_valid`

### Integration test

- Census 2021 cultural diversity with `--geography "Remoteness Areas" --geo-filter "South Australia"` verifying CSV download.
