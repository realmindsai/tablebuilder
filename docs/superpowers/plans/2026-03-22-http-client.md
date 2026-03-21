# HTTP Client Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure-HTTP client that replaces Playwright browser automation for fetching ABS TableBuilder data, reducing fetch time from 8-28 minutes to under 15 seconds.

**Architecture:** A `TableBuilderHTTPSession` context manager (drop-in replacement for `TableBuilderSession`) manages a `requests.Session` with JSF ViewState tracking. It calls REST JSON APIs for catalogue/schema operations and JSF form POSTs for table manipulation. The CLI gains a `--http` flag that switches between Playwright and HTTP backends.

**Tech Stack:** `requests` (already in deps), existing `tablebuilder` models and config

---

## Protocol Reference

Full protocol documented in `output/capture_analysis.md`. Key sequence:

1. Login: POST `/jsf/login.xhtml` with `loginForm:_idcl=loginForm:login2`
2. Select database: POST `/rest/catalogue/databases/tree` with `{"currentNode": [path]}`
3. Open database: RichFaces AJAX POST to `/jsf/dataCatalogueExplorer.xhtml` (component `j_id_3i`)
4. Navigate to tableView: GET `/jsf/tableView/tableView.xhtml`
5. Get schema: GET `/rest/catalogue/tableSchema/tree` (returns all 239 variables inline)
6. Select categories: POST `/rest/catalogue/tableSchema/tree` with `{"nodeState": {...}}`
7. Notify JSF: RichFaces AJAX POST to `/jsf/tableView/tableView.xhtml` (component `treeForm:j_id_6m`)
8. Add to axis: POST `/jsf/tableView/tableView.xhtml` with `buttonForm:addR=Row`
9. Retrieve data: RichFaces AJAX POST with `pageForm:retB` + progress polling
10. Select CSV: POST with `downloadControl:downloadType=CSV`
11. Download: GET `/webapi/downloadTable?jobId=<id>`

ViewState changes after every JSF POST — must extract from each response.

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/tablebuilder/http_session.py` | Create | `TableBuilderHTTPSession` context manager — login, ViewState tracking, session cookies |
| `src/tablebuilder/http_catalogue.py` | Create | REST catalogue operations — find database, open database, get/search schema |
| `src/tablebuilder/http_table.py` | Create | Table operations — select categories, add to axis, retrieve, download |
| `src/tablebuilder/cli.py` | Modify | Add `--http` flag to `fetch` command |
| `tests/test_http_session.py` | Create | Unit tests for login + ViewState (mocked HTTP) |
| `tests/test_http_catalogue.py` | Create | Unit tests for catalogue + schema (mocked HTTP) |
| `tests/test_http_table.py` | Create | Unit tests for table operations (mocked HTTP) |
| `tests/test_http_integration.py` | Create | Integration tests against real ABS (marked `@pytest.mark.integration`) |

---

## Chunk 1: HTTP Session (Login + ViewState)

### Task 1: Login and ViewState tracking

**Files:**
- Create: `src/tablebuilder/http_session.py`
- Create: `tests/test_http_session.py`

- [ ] **Step 1: Write failing test for ViewState extraction**

```python
# tests/test_http_session.py
from tablebuilder.http_session import extract_viewstate

class TestExtractViewState:
    def test_extracts_from_login_page(self):
        html = '<input type="hidden" name="javax.faces.ViewState" id="j_id__v_0:javax.faces.ViewState:3" value="ABC123" autocomplete="off" />'
        assert extract_viewstate(html) == "ABC123"

    def test_returns_none_when_missing(self):
        assert extract_viewstate("<html></html>") is None

    def test_extracts_from_xml_partial_update(self):
        xml = '<update id="javax.faces.ViewState"><![CDATA[NEW_VS_TOKEN]]></update>'
        assert extract_viewstate(xml) == "NEW_VS_TOKEN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_http_session.py::TestExtractViewState -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement extract_viewstate**

```python
# src/tablebuilder/http_session.py
# ABOUTME: Pure-HTTP session management for ABS TableBuilder.
# ABOUTME: Handles login, ViewState tracking, and cookie persistence via requests.Session.

import re

from tablebuilder.config import Config
from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.http_session")

BASE_URL = "https://tablebuilder.abs.gov.au/webapi"

# Matches ViewState in HTML hidden inputs and XML partial updates
_VS_HTML_RE = re.compile(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"')
_VS_XML_RE = re.compile(r'<update id="javax\.faces\.ViewState">\s*<!\[CDATA\[([^\]]+)\]\]>')


def extract_viewstate(text: str) -> str | None:
    """Extract JSF ViewState token from HTML or XML response."""
    m = _VS_HTML_RE.search(text)
    if m:
        return m.group(1)
    m = _VS_XML_RE.search(text)
    if m:
        return m.group(1)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_http_session.py::TestExtractViewState -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for login**

```python
# tests/test_http_session.py (append)
import pytest
from unittest.mock import MagicMock, patch
from tablebuilder.http_session import TableBuilderHTTPSession, LoginError
from tablebuilder.config import Config

LOGIN_PAGE_HTML = '''<form id="loginForm">
<input type="hidden" name="javax.faces.ViewState" id="vs" value="INITIAL_VS" autocomplete="off" />
</form>'''

CATALOGUE_PAGE_HTML = '''<html><head><title>Data Catalogue</title></head>
<input type="hidden" name="javax.faces.ViewState" id="vs" value="LOGGED_IN_VS" autocomplete="off" />
</html>'''


class TestLogin:
    def test_login_sends_correct_form_data(self):
        """Login POST includes credentials, ViewState, and _idcl button identifier."""
        config = Config(user_id="testuser", password="testpass")
        session = TableBuilderHTTPSession(config)

        mock_resp_login = MagicMock(status_code=200, text=LOGIN_PAGE_HTML, url="login.xhtml")
        mock_resp_post = MagicMock(status_code=200, text=CATALOGUE_PAGE_HTML, url="dataCatalogueExplorer.xhtml")

        with patch.object(session, '_session') as mock_s:
            mock_s.get.return_value = mock_resp_login
            mock_s.post.return_value = mock_resp_post
            session.login()

            post_call = mock_s.post.call_args
            form_data = post_call.kwargs.get('data') or post_call.args[1] if len(post_call.args) > 1 else post_call.kwargs['data']
            assert form_data["loginForm:username2"] == "testuser"
            assert form_data["loginForm:password2"] == "testpass"
            assert form_data["loginForm:_idcl"] == "loginForm:login2"
            assert form_data["javax.faces.ViewState"] == "INITIAL_VS"

    def test_login_updates_viewstate(self):
        """After login, viewstate is updated from the catalogue page."""
        config = Config(user_id="u", password="p")
        session = TableBuilderHTTPSession(config)

        mock_resp_login = MagicMock(status_code=200, text=LOGIN_PAGE_HTML, url="login.xhtml")
        mock_resp_post = MagicMock(status_code=200, text=CATALOGUE_PAGE_HTML, url="dataCatalogueExplorer.xhtml")

        with patch.object(session, '_session') as mock_s:
            mock_s.get.return_value = mock_resp_login
            mock_s.post.return_value = mock_resp_post
            session.login()
            assert session.viewstate == "LOGGED_IN_VS"

    def test_login_raises_on_bad_credentials(self):
        """Login raises LoginError when still on login page after POST."""
        config = Config(user_id="bad", password="bad")
        session = TableBuilderHTTPSession(config)

        mock_resp_login = MagicMock(status_code=200, text=LOGIN_PAGE_HTML, url="login.xhtml")
        mock_resp_post = MagicMock(status_code=200, text=LOGIN_PAGE_HTML, url="login.xhtml")

        with patch.object(session, '_session') as mock_s:
            mock_s.get.return_value = mock_resp_login
            mock_s.post.return_value = mock_resp_post
            with pytest.raises(LoginError, match="still on login page"):
                session.login()

    def test_login_handles_terms_page(self):
        """Login accepts terms when redirected to terms.xhtml."""
        config = Config(user_id="u", password="p")
        session = TableBuilderHTTPSession(config)

        terms_html = '<input type="hidden" name="javax.faces.ViewState" id="vs" value="TERMS_VS" />'
        mock_login_get = MagicMock(status_code=200, text=LOGIN_PAGE_HTML, url="login.xhtml")
        mock_terms_resp = MagicMock(status_code=200, text=terms_html, url="terms.xhtml")
        mock_cat_resp = MagicMock(status_code=200, text=CATALOGUE_PAGE_HTML, url="dataCatalogueExplorer.xhtml")

        with patch.object(session, '_session') as mock_s:
            mock_s.get.return_value = mock_login_get
            mock_s.post.side_effect = [mock_terms_resp, mock_cat_resp]
            session.login()
            assert session.viewstate == "LOGGED_IN_VS"
            assert mock_s.post.call_count == 2
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/test_http_session.py::TestLogin -v`
Expected: FAIL (TableBuilderHTTPSession not defined)

- [ ] **Step 7: Implement TableBuilderHTTPSession**

```python
# src/tablebuilder/http_session.py (append to existing)
import time

import requests

from tablebuilder.browser import LoginError


class TableBuilderHTTPSession:
    """Context manager for a pure-HTTP session to ABS TableBuilder.

    Drop-in replacement for TableBuilderSession — yields itself instead of a Page.
    """

    def __init__(self, config: Config, knowledge=None):
        self.config = config
        self.knowledge = knowledge
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json, text/html, */*",
        })
        self.viewstate: str | None = None
        self.catalogue_html: str = ""

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._session.close()
        return False

    def login(self):
        """Log in via JSF form POST, handle terms page, store ViewState."""
        login_start = time.time()
        logger.info("HTTP login started for user %s", self.config.user_id)

        r = self._session.get(f"{BASE_URL}/jsf/login.xhtml")
        vs = extract_viewstate(r.text)
        if not vs:
            raise LoginError("Cannot find ViewState on login page.")

        r = self._session.post(f"{BASE_URL}/jsf/login.xhtml", data={
            "loginForm:username2": self.config.user_id,
            "loginForm:password2": self.config.password,
            "loginForm_SUBMIT": "1",
            "javax.faces.ViewState": vs,
            "r": "",
            "loginForm:_idcl": "loginForm:login2",
        }, headers={
            "Referer": f"{BASE_URL}/jsf/login.xhtml",
            "Origin": "https://tablebuilder.abs.gov.au",
        }, allow_redirects=True)

        if "terms.xhtml" in r.url:
            vs = extract_viewstate(r.text) or vs
            r = self._session.post(r.url, data={
                "termsForm:termsButton": "Accept",
                "termsForm_SUBMIT": "1",
                "javax.faces.ViewState": vs,
            }, allow_redirects=True)

        if "dataCatalogueExplorer" not in r.url:
            raise LoginError(
                f"Login failed — still on login page. Check your User ID and password. URL: {r.url}"
            )

        self.viewstate = extract_viewstate(r.text)
        self.catalogue_html = r.text
        login_duration = time.time() - login_start
        logger.info("HTTP login succeeded in %.1f seconds", login_duration)
        if self.knowledge:
            self.knowledge.record_timing("http_login", login_duration)

    def jsf_post(self, url: str, data: dict) -> requests.Response:
        """POST to a JSF page with current ViewState, update ViewState from response."""
        data["javax.faces.ViewState"] = self.viewstate
        r = self._session.post(url, data=data, allow_redirects=True)
        new_vs = extract_viewstate(r.text)
        if new_vs:
            self.viewstate = new_vs
        return r

    def richfaces_ajax(self, url: str, form_id: str, component_id: str,
                       extra_params: dict | None = None) -> requests.Response:
        """Send a RichFaces AJAX POST with standard partial parameters."""
        data = {
            f"{form_id}_SUBMIT": "1",
            "javax.faces.ViewState": self.viewstate,
            "org.richfaces.ajax.component": component_id,
            component_id: component_id,
            "rfExt": "null",
            "AJAX:EVENTS_COUNT": "1",
            "javax.faces.partial.event": "undefined",
            "javax.faces.source": component_id,
            "javax.faces.partial.ajax": "true",
            "javax.faces.partial.execute": "@component",
            "javax.faces.partial.render": "@component",
            form_id: form_id,
        }
        if extra_params:
            data.update(extra_params)
        r = self._session.post(url, data=data, headers={
            "Faces-Request": "partial/ajax",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": url,
        })
        new_vs = extract_viewstate(r.text)
        if new_vs:
            self.viewstate = new_vs
        return r

    def rest_get(self, path: str) -> dict:
        """GET a REST JSON endpoint."""
        r = self._session.get(f"{BASE_URL}{path}")
        r.raise_for_status()
        return r.json()

    def rest_post(self, path: str, payload: dict) -> dict | None:
        """POST JSON to a REST endpoint, return parsed JSON or None."""
        r = self._session.post(f"{BASE_URL}{path}", json=payload)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if "json" in ct and r.text.strip():
            return r.json()
        return None
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest tests/test_http_session.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add src/tablebuilder/http_session.py tests/test_http_session.py
git commit -m "feat: add HTTP session with login and ViewState tracking"
```

---

## Chunk 2: Catalogue and Schema

### Task 2: Catalogue operations (find database, open database)

**Files:**
- Create: `src/tablebuilder/http_catalogue.py`
- Create: `tests/test_http_catalogue.py`

- [ ] **Step 1: Write failing tests for find_database**

```python
# tests/test_http_catalogue.py
import json
from tablebuilder.http_catalogue import find_database

SAMPLE_TREE = {
    "nodeList": [{
        "key": "cm9vdA",
        "data": {"type": "FOLDER", "name": "Data"},
        "children": [{
            "key": "MjAyMUNlbnN1cw",
            "data": {"type": "FOLDER", "name": "2021 Census of Population and Housing"},
            "children": [{
                "key": "Y2Vuc3VzMjAyMVRCUHJv",
                "data": {"type": "FOLDER", "name": "Census TableBuilder Pro"},
                "children": [{
                    "key": "MjAyMVBlcnNvbnNFTg",
                    "data": {"leaf": True, "type": "DATABASE", "name": "2021 Census - counting persons, place of enumeration"},
                }],
            }],
        }],
    }],
}

class TestFindDatabase:
    def test_finds_by_substring(self):
        path, node = find_database(SAMPLE_TREE, "counting persons")
        assert node["key"] == "MjAyMVBlcnNvbnNFTg"
        assert len(path) == 4

    def test_returns_none_for_missing(self):
        assert find_database(SAMPLE_TREE, "nonexistent") is None

    def test_case_insensitive(self):
        path, node = find_database(SAMPLE_TREE, "COUNTING PERSONS")
        assert node["key"] == "MjAyMVBlcnNvbnNFTg"
```

- [ ] **Step 2: Run test, verify fail**

- [ ] **Step 3: Implement find_database**

```python
# src/tablebuilder/http_catalogue.py
# ABOUTME: REST catalogue operations for ABS TableBuilder HTTP client.
# ABOUTME: Finds databases in the catalogue tree and opens them via RichFaces AJAX.

import base64

from tablebuilder.http_session import TableBuilderHTTPSession, BASE_URL
from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.http_catalogue")

TABLEVIEW_URL = f"{BASE_URL}/jsf/tableView/tableView.xhtml"
CATALOGUE_URL = f"{BASE_URL}/jsf/dataCatalogueExplorer.xhtml"


def find_database(tree: dict, name_fragment: str) -> tuple[list[str], dict] | None:
    """Walk the catalogue tree to find a DATABASE node by name substring."""
    def walk(nodes, path=None):
        path = path or []
        for node in nodes:
            p = path + [node["key"]]
            n = node.get("data", {}).get("name", "")
            t = node.get("data", {}).get("type", "")
            if name_fragment.lower() in n.lower() and t == "DATABASE":
                return p, node
            result = walk(node.get("children", []), p)
            if result:
                return result
        return None
    return walk(tree.get("nodeList", []))
```

- [ ] **Step 4: Run test, verify pass**

- [ ] **Step 5: Write failing tests for open_database**

```python
class TestOpenDatabase:
    def test_open_database_selects_node_and_sends_ajax(self, mock_session):
        """open_database POSTs currentNode then doubleClickDatabase AJAX."""
        open_database(mock_session, ["root", "census", "db_key"])
        # Should have called rest_post for node selection
        mock_session.rest_post.assert_called_once()
        # Should have called richfaces_ajax for doubleClickDatabase
        mock_session.richfaces_ajax.assert_called_once()

    def test_open_database_follows_redirect_to_tableview(self, mock_session):
        """open_database GETs tableView.xhtml and updates ViewState."""
        mock_session._session.get.return_value = MagicMock(
            status_code=200, text='<input name="javax.faces.ViewState" value="TV_VS" />', url=TABLEVIEW_URL
        )
        open_database(mock_session, ["root", "census", "db_key"])
        assert mock_session.viewstate == "TV_VS"
```

- [ ] **Step 6: Implement open_database**

- [ ] **Step 7: Write failing tests for get_schema + find_variable**

```python
class TestGetSchema:
    def test_returns_variable_map(self, mock_session):
        """get_schema returns dict mapping variable name to key and metadata."""

class TestFindVariable:
    def test_finds_by_label(self):
        """find_variable matches 'SEXP Sex' by label."""

    def test_finds_by_code(self):
        """find_variable matches 'SEXP' when full label is 'SEXP Sex'."""
```

- [ ] **Step 8: Implement get_schema and find_variable**

`get_schema()` GETs `/rest/catalogue/tableSchema/tree`, walks all nodes, returns `{name: {key, group, child_count, levels}}` for every node with `iconType == "FIELD"`.

`find_variable(schema, name)` matches by exact label, code prefix, or case-insensitive substring.

- [ ] **Step 9: Run all tests, verify pass**

- [ ] **Step 10: Commit**

```bash
git add src/tablebuilder/http_catalogue.py tests/test_http_catalogue.py
git commit -m "feat: add HTTP catalogue with find_database, open_database, get_schema"
```

---

## Chunk 3: Table Operations

### Task 3: Select categories and add to axis

**Files:**
- Create: `src/tablebuilder/http_table.py`
- Create: `tests/test_http_table.py`

- [ ] **Step 1: Write failing tests for select_categories**

```python
# tests/test_http_table.py
from tablebuilder.http_table import build_node_state

class TestBuildNodeState:
    def test_single_category(self):
        """Builds nodeState for one category checkbox."""
        result = build_node_state(group_key="GRP", field_key="FLD", category_keys=["MQ"])
        assert result == {
            "nodeState": {"set": {"GRP": {"children": {"FLD": {"children": {"MQ": {"value": True}}}}}}}
        }

    def test_multiple_categories(self):
        """Builds nodeState with multiple checked categories."""
        result = build_node_state("GRP", "FLD", ["MQ", "Mg"])
        children = result["nodeState"]["set"]["GRP"]["children"]["FLD"]["children"]
        assert children == {"MQ": {"value": True}, "Mg": {"value": True}}
```

- [ ] **Step 2: Run test, verify fail**

- [ ] **Step 3: Implement build_node_state**

```python
# src/tablebuilder/http_table.py
# ABOUTME: Table building operations via HTTP — category selection, axis assignment, download.
# ABOUTME: Replaces Playwright-based table_builder.py and downloader.py for the HTTP backend.

import base64

from tablebuilder.http_session import TableBuilderHTTPSession, BASE_URL
from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.http_table")

TABLEVIEW_URL = f"{BASE_URL}/jsf/tableView/tableView.xhtml"
SCHEMA_TREE_URL = "/rest/catalogue/tableSchema/tree"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode().rstrip("=")


def build_node_state(group_key: str, field_key: str, category_keys: list[str]) -> dict:
    """Build the nodeState payload to check category checkboxes."""
    children = {k: {"value": True} for k in category_keys}
    return {
        "nodeState": {
            "set": {
                group_key: {
                    "children": {
                        field_key: {
                            "children": children,
                        }
                    }
                }
            }
        }
    }
```

- [ ] **Step 4: Run test, verify pass**

- [ ] **Step 5: Write failing tests for select_all_categories**

```python
class TestSelectAllCategories:
    def test_expands_variable_and_checks_all(self, mock_session):
        """Expands variable node to get category keys, then checks all."""

    def test_notifies_jsf_after_each_checkbox(self, mock_session):
        """Fires treeForm:j_id_6m AJAX after each nodeState POST."""
```

- [ ] **Step 6: Implement select_all_categories**

Expand the variable node via `expandedNodes` + `returnNode` POST, get child category keys from the response, then POST `nodeState` for each category + fire `treeForm:j_id_6m` AJAX after each.

- [ ] **Step 7: Write failing tests for add_to_axis**

```python
class TestAddToAxis:
    def test_posts_buttonform_with_axis(self, mock_session):
        """add_to_axis POSTs buttonForm with addR/addC/addL."""
        add_to_axis(mock_session, "row")
        data = mock_session.jsf_post.call_args.kwargs['data']
        assert data["buttonForm:addR"] == "Row"
        assert data["buttonForm_SUBMIT"] == "1"
```

- [ ] **Step 8: Implement add_to_axis**

```python
def add_to_axis(session: TableBuilderHTTPSession, axis: str) -> None:
    """Submit the buttonForm to add selected variable to an axis."""
    button_map = {"row": "addR", "col": "addC", "wafer": "addL"}
    value_map = {"row": "Row", "col": "Column", "wafer": "Wafer"}
    btn = button_map[axis]
    session.jsf_post(TABLEVIEW_URL, {
        "buttonForm_SUBMIT": "1",
        f"buttonForm:{btn}": value_map[axis],
    })
```

- [ ] **Step 9: Run all tests, verify pass**

- [ ] **Step 10: Commit**

```bash
git add src/tablebuilder/http_table.py tests/test_http_table.py
git commit -m "feat: add HTTP table operations — category selection and axis assignment"
```

### Task 4: Retrieve data and download

**Files:**
- Modify: `src/tablebuilder/http_table.py`
- Modify: `tests/test_http_table.py`

- [ ] **Step 1: Write failing tests for retrieve_data**

```python
class TestRetrieveData:
    def test_sends_retrieve_ajax(self, mock_session):
        """retrieve_data fires pageForm:retB RichFaces AJAX."""

    def test_polls_progress_until_complete(self, mock_session):
        """Polls j_id_4f:j_id_4g until progress reaches 100."""
```

- [ ] **Step 2: Implement retrieve_data**

Fire `pageForm:retB` via `richfaces_ajax`, then poll `j_id_4f:j_id_4g` until the response contains progress=100 or table data.

- [ ] **Step 3: Write failing tests for download_table**

```python
class TestDownloadTable:
    def test_selects_csv_format(self, mock_session):
        """download_table POSTs downloadControl:downloadType=CSV."""

    def test_downloads_via_servlet(self, mock_session):
        """download_table GETs /downloadTable?jobId=<id> and saves file."""
```

- [ ] **Step 4: Implement download_table**

POST format selection, then either use the direct download button or the queue flow (POST with jobId → GET `/downloadTable?jobId=<id>`). Save response content to file, extract CSV from ZIP if needed.

- [ ] **Step 5: Run all tests, verify pass**

- [ ] **Step 6: Commit**

```bash
git add src/tablebuilder/http_table.py tests/test_http_table.py
git commit -m "feat: add HTTP retrieve and download operations"
```

---

## Chunk 4: High-Level API + CLI Integration

### Task 5: Compose the full fetch flow

**Files:**
- Modify: `src/tablebuilder/http_table.py`
- Modify: `tests/test_http_table.py`

- [ ] **Step 1: Write failing test for http_fetch_table**

```python
class TestHTTPFetchTable:
    def test_full_flow(self, mock_session):
        """http_fetch_table runs: open_db -> get_schema -> select_vars -> add_to_axes -> retrieve -> download."""
```

- [ ] **Step 2: Implement http_fetch_table**

```python
def http_fetch_table(session: TableBuilderHTTPSession, request: TableRequest, output_path: str) -> None:
    """Fetch a table via HTTP — the full pipeline."""
    # 1. Get catalogue and find database
    tree = session.rest_get("/rest/catalogue/databases/tree")
    result = find_database(tree, request.dataset)
    if not result:
        raise NavigationError(f"Database not found: {request.dataset}")
    path, db_node = result

    # 2. Open database
    open_database(session, path)

    # 3. Get schema
    schema = get_schema(session)

    # 4. For each variable, find it, select categories, add to axis
    for var_name, axis in request.variable_axes().items():
        var_info = find_variable(schema, var_name)
        if not var_info:
            raise TableBuildError(f"Variable not found: {var_name}")
        select_all_categories(session, schema, var_info)
        add_to_axis(session, axis.value)

    # 5. Retrieve and download
    retrieve_data(session)
    download_table(session, output_path)
```

- [ ] **Step 3: Run test, verify pass**

- [ ] **Step 4: Commit**

```bash
git add src/tablebuilder/http_table.py tests/test_http_table.py
git commit -m "feat: add http_fetch_table composing the full pipeline"
```

### Task 6: Add --http flag to CLI

**Files:**
- Modify: `src/tablebuilder/cli.py:46-127`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing test for --http flag**

```python
class TestFetchHTTPFlag:
    def test_http_flag_accepted(self, runner):
        """CLI accepts --http flag without error."""
        result = runner.invoke(cli, ['fetch', '--http', '--dataset', 'test', '--rows', 'Sex', '-o', 'out.csv'])
        assert '--http' not in result.output or result.exit_code != 2
```

- [ ] **Step 2: Add --http flag to fetch command**

Add `@click.option("--http", "use_http", is_flag=True, help="Use direct HTTP instead of browser automation.")` to the `fetch` command. When set, use `TableBuilderHTTPSession` + `http_fetch_table` instead of Playwright.

```python
# In the fetch() function, after building the TableRequest:
if use_http:
    from tablebuilder.http_session import TableBuilderHTTPSession
    from tablebuilder.http_table import http_fetch_table

    with TableBuilderHTTPSession(config, knowledge=knowledge) as session:
        click.echo("Logged in via HTTP.")
        click.echo("Fetching table...")
        http_fetch_table(session, request, output)
        click.echo(f"Done! CSV saved to {output}")
else:
    # existing Playwright path unchanged
    ...
```

- [ ] **Step 3: Run CLI test suite**

Run: `uv run pytest tests/test_cli.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/tablebuilder/cli.py tests/test_cli.py
git commit -m "feat: add --http flag to fetch command for direct API access"
```

---

## Chunk 5: Integration Testing

### Task 7: Integration test on totoro

**Files:**
- Create: `tests/test_http_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_http_integration.py
import os
import pytest
from pathlib import Path
from tablebuilder.config import load_config, ConfigError
from tablebuilder.http_session import TableBuilderHTTPSession
from tablebuilder.http_catalogue import find_database, open_database, get_schema, find_variable
from tablebuilder.http_table import http_fetch_table
from tablebuilder.models import TableRequest

skip_no_creds = pytest.mark.skipif(
    not os.environ.get("TABLEBUILDER_USER_ID"),
    reason="No ABS credentials"
)

@pytest.mark.integration
@skip_no_creds
class TestHTTPIntegration:
    def test_login(self):
        config = load_config()
        with TableBuilderHTTPSession(config) as session:
            assert session.viewstate is not None

    def test_get_catalogue(self):
        config = load_config()
        with TableBuilderHTTPSession(config) as session:
            tree = session.rest_get("/rest/catalogue/databases/tree")
            assert len(tree["nodeList"]) > 0

    def test_fetch_sex_table(self, tmp_path):
        config = load_config()
        output = str(tmp_path / "sex_test.csv")
        request = TableRequest(
            dataset="2021 Census - counting persons, place of enumeration",
            rows=["SEXP Sex"],
        )
        with TableBuilderHTTPSession(config) as session:
            http_fetch_table(session, request, output)
        assert Path(output).exists()
        content = Path(output).read_text()
        assert "Male" in content or "Female" in content
```

- [ ] **Step 2: Push to totoro and run**

```bash
git push origin feat/direct-api-access
ssh totoro "cd /tank/code/tablebuilder && git pull origin feat/direct-api-access && uv sync && uv run pytest tests/test_http_integration.py -v -m integration"
```

- [ ] **Step 3: Fix any failures, re-run until green**

- [ ] **Step 4: Commit**

```bash
git add tests/test_http_integration.py
git commit -m "test: add HTTP integration tests for full fetch pipeline"
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| ViewState goes stale between calls | `jsf_post` and `richfaces_ajax` extract new ViewState from every response |
| Category keys differ between databases | `select_all_categories` dynamically expands the variable node to discover keys |
| Download requires queue for large tables | Implement both direct download and queue+poll fallback |
| JSF component IDs change (`j_id_3i`, `j_id_6m`) | Extract from tableView HTML at runtime rather than hardcoding |
| Session timeout on slow networks | Add retry logic to `jsf_post` for 403/timeout responses |

## Expected Performance

| Operation | Playwright | HTTP |
|-----------|-----------|------|
| Login | 5-10s | <1s |
| Open database | 5-15s | <1s |
| Get schema | 2-6 min (expansion loop!) | <1s |
| Select categories | 2-5s/variable | <0.5s |
| Add to axis | 5s (page reload) | <1s |
| Retrieve | 5-30s | 1-5s |
| Download | 10-60s | 1-5s |
| **Total** | **8-28 min** | **5-15s** |
