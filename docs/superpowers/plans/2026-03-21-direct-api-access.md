# Direct API Access Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Playwright browser automation with direct HTTP calls to ABS TableBuilder's REST API and JSF endpoints, reducing fetch time from 8-28 minutes to seconds.

**Architecture:** A new `http_client.py` module manages a `requests.Session` with JSF ViewState tracking and cookie persistence. It calls REST endpoints for catalogue/schema operations and RichFaces AJAX for table manipulation. The existing CLI and service layer call the HTTP client instead of Playwright.

**Tech Stack:** `requests`, existing `tablebuilder` package, JSF/RichFaces AJAX protocol

---

## Discovery Summary

### What We Found (2026-03-21)

The ABS TableBuilder frontend is a Java Server Faces (JSF) app with RichFaces AJAX and a React-based tree component. Behind the JSF facade, there are clean REST JSON APIs:

### Confirmed Working REST Endpoints

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/rest/catalogue/databases/tree` | GET | Full catalogue of all 197 databases as JSON tree | JSESSIONID cookie |
| `/rest/catalogue/databases/tree` | POST | Expand/select nodes: `{"currentNode": [...path]}` or `{"expandedNodes": {...}}` | JSESSIONID |
| `/rest/catalogue/databaseTables/tree` | GET | User's saved tables | JSESSIONID |
| `/rest/catalogue/tableSchema/tree` | GET | Variable tree for currently opened database — full variable hierarchy | JSESSIONID |
| `/rest/catalogue/tableSchema/tree` | POST | Expand/select variable nodes (same API shape as databases/tree) | JSESSIONID |

### JSF/RichFaces AJAX Actions (via form POST to .xhtml)

| Action | JS Function | RichFaces Target | Parameters |
|--------|-------------|------------------|------------|
| Open database | `doubleClickDatabase()` | `j_id_3i` | None (uses selected node from REST tree) |
| Select variable in tree | `tableSchemaTreeOnSelect()` | `treeForm:j_id_6m` | None (uses selected node from REST tree) |
| Add variable to axis | `dropToTable(id, dim, comp)` | `buttonForm:j_id_58` | `id`: variable key, `dim`: "row"/"col"/"wafer", `comp`: component index |
| Render/retrieve table | `renderTable()` | `pageForm:j_id_9y` | None |
| Remove variable | `tableRemoveSubjectComponent(comp)` | `tableJsFunctions:j_id_8k` | `component`: component ID |
| Select wafer | `tableSelectWafer(wafer)` | `tableJsFunctions:j_id_94` | `wafer`: wafer ID |
| Search variables | `searchButton` RichFaces AJAX | `searchButton` | `searchPattern` input value |

### Download Path

- **Servlet URL:** `../downloadTable` (relative to tableView) = `/webapi/downloadTable`
- **Format dropdown:** `#downloadControl:downloadType` with CSV/Excel options
- **Queue flow:** `downloadTableModeForm` modal with name field + queue submit
- **Direct download:** `input[value="Download table"]` button hits the download servlet

### Key Protocol Details

- **Node IDs are base64-encoded:** `b64encode("2021PersonsEN")` = `MjAyMVBlcnNvbnNFTg`
- **Schema variable keys encode:** `SXV4__<database>__<record>__<field>_FLD` (e.g., `SXV4__TBPersonsEnum__Person Records__SEXP_FLD`)
- **ViewState:** Every JSF form POST requires `javax.faces.ViewState` extracted from the last page response
- **RichFaces AJAX POSTs** require: form `_SUBMIT=1`, ViewState, `org.richfaces.ajax.component`, `javax.faces.partial.ajax=true`, and the function-specific parameters
- **Login requires:** `loginForm:_idcl=loginForm:login2` to identify the button click
- **Session cookies:** `JSESSIONID` (primary), `AWSALB` (load balancer)

### What Still Needs Investigation

1. **`dropToTable(id, dim, comp)` exact protocol** — We know the JS function signature but haven't captured a live call yet. Need to intercept the exact AJAX POST when adding a variable to an axis.
2. **`/webapi/downloadTable` servlet** — How does it know which table to download? Cookie-based? Query params? Need to capture a live download request.
3. **`/rest/table` endpoint** — Returns 500 on empty POST, 400 on wrong payload. The right payload format is unknown. May be how the frontend fetches rendered table data.
4. **Checkbox selection protocol** — When clicking a checkbox in the tree, what AJAX call fires? Is it the `tableSchemaTreeOnSelect` function, or something else?
5. **Auto-retrieve vs manual retrieve** — Some tables auto-populate data. What triggers this? The `autoRetrieveScripts` form with a `showProgressIfAutoRetrievingData()` function suggests a polling mechanism.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/tablebuilder/http_client.py` | Create | HTTP session, login, JSF ViewState tracking, RichFaces AJAX helper |
| `src/tablebuilder/rest_api.py` | Create | Catalogue, schema, and table REST API wrappers |
| `scripts/capture_add_variable.py` | Create | Playwright script to capture exact AJAX traffic for dropToTable and download |
| `tests/test_http_client.py` | Create | Unit tests for HTTP client (mocked responses) |
| `tests/test_rest_api.py` | Create | Unit tests for REST API wrappers (mocked responses) |
| `tests/test_http_integration.py` | Create | Integration tests hitting real ABS API |

---

## Chunk 1: Capture Missing Protocol Details

Before building anything, we need to capture the exact AJAX protocol for two operations we haven't seen yet: adding a variable to an axis, and downloading the table.

### Task 1: Capture dropToTable and download AJAX traffic

**Files:**
- Create: `scripts/capture_add_variable.py`

- [ ] **Step 1: Write the Playwright capture script**

Script should:
1. Log in and open "2021 Census - counting persons, place of enumeration"
2. Enable network request/response interception (only XHR/fetch/document)
3. Expand "Person Variables" → "People Characteristics" in the tree
4. Click the "SEXP Sex" checkbox
5. Click "Add to Row" button (or call `dropToTable()` directly)
6. Capture the exact POST body and response
7. Click "Retrieve Data" and capture the POST
8. Click "Download table" and capture the download URL/headers
9. Save all captured traffic to `output/capture_add_variable.json`

Key things to capture for each AJAX call:
- Full POST body (URL-encoded form data)
- All request headers (especially Faces-Request, X-Requested-With)
- Response body (XML partial update or JSON)
- Any ViewState changes between calls

- [ ] **Step 2: Run on local machine (has Chromium)**

Run: `uv run python scripts/capture_add_variable.py`

- [ ] **Step 3: Analyze the captured traffic**

Extract from the capture:
- Exact POST body for `dropToTable(id, dim, comp)` — what are `id`, `dim`, `comp` values?
- Exact POST body for retrieve/render
- Download servlet URL and any query parameters or form data
- Whether ViewState changes between operations (it likely does)

- [ ] **Step 4: Document findings in this plan file**

Update the "What Still Needs Investigation" section above with the answers.

- [ ] **Step 5: Commit**

```bash
git add scripts/capture_add_variable.py output/capture_add_variable.json
git commit -m "research: capture dropToTable and download AJAX protocol"
```

---

## Chunk 2: HTTP Client Foundation

### Task 2: Build the JSF/RichFaces HTTP client

**Files:**
- Create: `src/tablebuilder/http_client.py`
- Test: `tests/test_http_client.py`

- [ ] **Step 1: Write failing tests for login**

```python
def test_login_extracts_viewstate(mock_responses):
    """Login parses ViewState from login page and sends correct form data."""

def test_login_handles_terms_page(mock_responses):
    """Login accepts terms page when redirected there after credentials."""

def test_login_raises_on_bad_credentials(mock_responses):
    """Login raises LoginError when still on login.xhtml after POST."""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_http_client.py -v`
Expected: FAIL

- [ ] **Step 3: Implement TableBuilderHTTPClient.login()**

The client should:
- GET login page, extract ViewState
- POST with credentials + `loginForm:_idcl=loginForm:login2`
- Handle terms page redirect
- Store cookies in `requests.Session`
- Track current ViewState

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_http_client.py -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for RichFaces AJAX helper**

```python
def test_richfaces_ajax_sends_correct_params():
    """AJAX helper includes form SUBMIT, ViewState, component ID, and partial params."""

def test_richfaces_ajax_extracts_redirect():
    """AJAX helper detects redirect URL in XML response."""

def test_richfaces_ajax_updates_viewstate():
    """AJAX helper extracts new ViewState from partial update response."""
```

- [ ] **Step 6: Implement richfaces_ajax() helper method**

Generic method that sends a RichFaces partial AJAX POST with all required fields.

- [ ] **Step 7: Run tests, verify pass**

- [ ] **Step 8: Commit**

```bash
git add src/tablebuilder/http_client.py tests/test_http_client.py
git commit -m "feat: add HTTP client with login and RichFaces AJAX support"
```

### Task 3: Build REST API wrappers

**Files:**
- Create: `src/tablebuilder/rest_api.py`
- Test: `tests/test_rest_api.py`

- [ ] **Step 1: Write failing tests for catalogue operations**

```python
def test_get_catalogue_returns_database_list():
    """GET databases/tree returns parsed tree with database nodes."""

def test_find_database_by_name():
    """find_database() walks tree to find database by name substring."""

def test_open_database_sends_select_then_ajax():
    """open_database() POSTs currentNode then triggers doubleClickDatabase AJAX."""
```

- [ ] **Step 2: Run tests, verify fail**

- [ ] **Step 3: Implement catalogue operations**

- `get_catalogue()` — GET `/rest/catalogue/databases/tree`, return parsed tree
- `find_database(name)` — Walk tree, return path + node for matching DATABASE leaf
- `open_database(path)` — POST currentNode to REST, then call `doubleClickDatabase` via RichFaces AJAX, follow redirect to tableView

- [ ] **Step 4: Run tests, verify pass**

- [ ] **Step 5: Write failing tests for schema operations**

```python
def test_get_schema_returns_variable_tree():
    """GET tableSchema/tree returns variable hierarchy."""

def test_expand_variable_group():
    """POST expandedNodes reveals child variables."""

def test_find_variable_by_name():
    """find_variable() locates variable node by label."""
```

- [ ] **Step 6: Implement schema operations**

- `get_schema()` — GET `/rest/catalogue/tableSchema/tree`
- `expand_node(key)` — POST expandedNodes
- `find_variable(name)` — Walk schema tree, match by label (handle "SEXP Sex" code-prefixed format)

- [ ] **Step 7: Run tests, verify pass**

- [ ] **Step 8: Commit**

```bash
git add src/tablebuilder/rest_api.py tests/test_rest_api.py
git commit -m "feat: add REST API wrappers for catalogue and schema"
```

---

## Chunk 3: Table Operations (depends on Chunk 1 findings)

### Task 4: Implement variable selection and axis assignment

**Files:**
- Modify: `src/tablebuilder/rest_api.py`
- Test: `tests/test_rest_api.py`

- [ ] **Step 1: Write failing tests for add_variable_to_axis**

Based on Chunk 1 findings, test the exact `dropToTable(id, dim, comp)` protocol.

- [ ] **Step 2: Implement add_variable_to_axis()**

Call the `dropToTable` RichFaces AJAX with the variable ID, dimension ("row"/"col"/"wafer"), and component index.

- [ ] **Step 3: Write failing tests for retrieve_table**

- [ ] **Step 4: Implement retrieve_table()**

Call `renderTable()` via RichFaces AJAX, wait for completion.

- [ ] **Step 5: Run tests, verify pass**

- [ ] **Step 6: Commit**

### Task 5: Implement download

**Files:**
- Modify: `src/tablebuilder/rest_api.py`
- Test: `tests/test_rest_api.py`

- [ ] **Step 1: Write failing tests for download_table**

Based on Chunk 1 findings, test the download servlet access.

- [ ] **Step 2: Implement download_table()**

Access `/webapi/downloadTable` with the right parameters/cookies, save the response.

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

---

## Chunk 4: Integration and CLI

### Task 6: Integration test with real ABS API

**Files:**
- Create: `tests/test_http_integration.py`

- [ ] **Step 1: Write end-to-end test**

```python
@pytest.mark.integration
def test_fetch_sex_by_age_via_http():
    """Full flow: login -> open 2021 census -> add Sex to rows -> retrieve -> download CSV."""
```

- [ ] **Step 2: Run on totoro (has real credentials and no rate limit concerns)**

- [ ] **Step 3: Commit**

### Task 7: Add HTTP backend to CLI

**Files:**
- Modify: `src/tablebuilder/cli.py`

- [ ] **Step 1: Add `--http` flag to `fetch` command**

When `--http` is passed, use `http_client.py` + `rest_api.py` instead of Playwright.

- [ ] **Step 2: Test both paths still work**

- [ ] **Step 3: Commit**

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `dropToTable` requires unknown parameters | Medium | Blocks Chunk 3 | Chunk 1 captures the exact protocol first |
| ABS changes JSF component IDs (j_id_3i etc.) | Medium | Breaks AJAX calls | These IDs are server-generated; build a lookup that extracts them from the page HTML |
| Download servlet needs table to be rendered first | High | Adds complexity | May need to poll for render completion before download |
| Rate limiting or session timeout | Low | Slows development | Use totoro for integration tests; add retry logic |
| ViewState invalidation between calls | Medium | 403/500 errors | Extract fresh ViewState from every response |

## Performance Comparison (Expected)

| Operation | Playwright (current) | HTTP Direct (target) |
|-----------|---------------------|---------------------|
| Login | 5-10s | <1s |
| Open database | 5-15s | <1s |
| Tree expansion | 2-6 min (stale loop!) | <1s (REST API) |
| Variable selection | 2-5s per variable | <0.5s |
| Retrieve data | 5-30s | 1-5s |
| Download | 10-60s (queue + poll) | 1-5s (direct servlet) |
| **Total per table** | **8-28 min** | **< 15s** |
