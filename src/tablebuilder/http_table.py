# ABOUTME: HTTP table operations for ABS TableBuilder category selection, axis assignment, and data download.
# ABOUTME: Builds REST payloads, selects checkbox categories, assigns variables to axes, and retrieves/downloads results.

from __future__ import annotations

import io
import os
import shutil
import tempfile
import zipfile

from tablebuilder.http_session import BASE_URL, TableBuilderHTTPSession
from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.http_table")

TABLEVIEW_URL = f"{BASE_URL}/jsf/tableView/tableView.xhtml"
SCHEMA_TREE_PATH = "/rest/catalogue/tableSchema/tree"

# Mapping from axis name to (button suffix, button value)
_AXIS_BUTTONS = {
    "row": ("addR", "Row"),
    "col": ("addC", "Column"),
    "wafer": ("addL", "Wafer"),
}


def build_node_state(
    group_key: str, field_key: str, category_keys: list[str]
) -> dict:
    """Build the nodeState payload for checking category checkboxes.

    Each checkbox click sends a nodeState that nests category selections
    under the group and field keys in the schema tree.

    Args:
        group_key: The key of the group node containing the variable.
        field_key: The key of the variable (field) node.
        category_keys: List of category keys to mark as selected.

    Returns:
        A dict with the nested nodeState structure for the REST POST.
    """
    return {
        "nodeState": {
            "set": {
                group_key: {
                    "children": {
                        field_key: {
                            "children": {
                                cat_key: {"value": True}
                                for cat_key in category_keys
                            }
                        }
                    }
                }
            }
        }
    }


def build_expand_payload(group_key: str, field_key: str) -> dict:
    """Build the expandedNodes + returnNode payload to expand a variable.

    Expanding a variable node reveals its child categories and their keys.

    Args:
        group_key: The key of the group node containing the variable.
        field_key: The key of the variable (field) node.

    Returns:
        A dict with expandedNodes and returnNode for the REST POST.
    """
    return {
        "expandedNodes": {
            "set": {
                group_key: {
                    "children": {
                        field_key: {"value": True}
                    }
                }
            }
        },
        "returnNode": {
            "node": [group_key, field_key],
            "data": True,
            "state": True,
            "expanded": True,
        },
    }


def _find_group_key_for_variable(tree: dict, var_key: str) -> str | None:
    """Walk the schema tree to find the group key that contains a variable.

    Searches through all nodes looking for a field/draggable node whose
    key matches var_key, and returns the key of its immediate parent
    (the group node).

    Args:
        tree: The schema tree dict with a "nodeList" key.
        var_key: The key of the variable to find.

    Returns:
        The group node key, or None if not found.
    """

    def _walk(nodes: list[dict], parent_key: str | None) -> str | None:
        for node in nodes:
            key = node.get("key", "")
            data = node.get("data", {})
            children = node.get("children", [])

            is_field = (
                data.get("iconType") == "FIELD" or data.get("draggable") is True
            )

            if is_field and key == var_key:
                return parent_key

            result = _walk(children, key)
            if result is not None:
                return result

        return None

    return _walk(tree.get("nodeList", []), None)


def get_category_keys(
    session: TableBuilderHTTPSession,
    schema: dict,
    var_info: dict,
) -> tuple[str, str, list[str]]:
    """Expand a variable node to discover its category children.

    Fetches the schema tree to find the group key for the variable,
    then sends an expand payload to get the full list of category
    children with their keys.

    Args:
        session: An authenticated TableBuilderHTTPSession.
        schema: The schema dict from get_schema() (used for context).
        var_info: A variable info dict from find_variable().

    Returns:
        A tuple of (group_key, field_key, [category_keys]).

    Raises:
        ValueError: If the variable's group key cannot be found in the tree.
    """
    field_key = var_info["key"]

    # Fetch the full schema tree to find the group key
    tree = session.rest_get(SCHEMA_TREE_PATH)
    group_key = _find_group_key_for_variable(tree, field_key)

    if group_key is None:
        raise ValueError(
            f"Could not find group key for variable '{field_key}' in the schema tree."
        )

    # Expand the variable to get category children
    expand_payload = build_expand_payload(group_key, field_key)
    response = session.rest_post(SCHEMA_TREE_PATH, expand_payload)

    # Extract category keys from the response — categories are direct nodeList items
    category_keys = []
    if response and "nodeList" in response:
        for node in response["nodeList"]:
            category_keys.append(node["key"])

    logger.info(
        "Variable '%s': group_key=%s, %d categories discovered",
        field_key,
        group_key,
        len(category_keys),
    )

    return group_key, field_key, category_keys


def select_all_categories(
    session: TableBuilderHTTPSession,
    schema: dict,
    var_info: dict,
) -> None:
    """Select all category checkboxes for a variable.

    Discovers category keys by expanding the variable node, then sends
    a nodeState REST POST followed by a RichFaces AJAX call for each
    category, mimicking the browser checkbox-click behaviour.

    Args:
        session: An authenticated TableBuilderHTTPSession.
        schema: The schema dict from get_schema().
        var_info: A variable info dict from find_variable().
    """
    group_key, field_key, category_keys = get_category_keys(
        session, schema, var_info
    )

    for cat_key in category_keys:
        # POST nodeState for this category
        node_state = build_node_state(group_key, field_key, [cat_key])
        session.rest_post(SCHEMA_TREE_PATH, node_state)
        logger.debug("Selected category '%s' for variable '%s'", cat_key, field_key)

        # Fire JSF AJAX after each checkbox click
        session.richfaces_ajax(
            TABLEVIEW_URL,
            form_id="treeForm",
            component_id="treeForm:j_id_6m",
        )

    logger.info(
        "Selected %d categories for variable '%s'",
        len(category_keys),
        field_key,
    )


def add_to_axis(session: TableBuilderHTTPSession, axis: str) -> None:
    """Assign the currently selected variable to a table axis.

    Posts the JSF buttonForm to assign the checked categories to the
    specified axis (row, column, or wafer).

    Args:
        session: An authenticated TableBuilderHTTPSession.
        axis: One of "row", "col", or "wafer".

    Raises:
        ValueError: If axis is not a recognized value.
    """
    if axis not in _AXIS_BUTTONS:
        raise ValueError(
            f"Invalid axis '{axis}'. Must be one of: {', '.join(_AXIS_BUTTONS.keys())}"
        )

    button_suffix, button_value = _AXIS_BUTTONS[axis]

    data = {
        "buttonForm_SUBMIT": "1",
        f"buttonForm:{button_suffix}": button_value,
    }

    logger.info("Adding selection to %s axis", axis)
    session.jsf_post(TABLEVIEW_URL, data)


OPEN_TABLE_URL = f"{BASE_URL}/jsf/tableView/openTable.xhtml"
MANAGE_TABLES_PATH = "/rest/catalogue/manageTables/tree"
DOWNLOAD_TABLE_URL = f"{BASE_URL}/downloadTable"


def retrieve_data(session: TableBuilderHTTPSession) -> None:
    """Fire the retrieve/cross-tabulation AJAX call to generate table results.

    Sends a RichFaces AJAX POST on pageForm:retB with the required empty
    drag-and-drop fields and partial event type.  The server processes the
    cross-tabulation and populates the table view.

    Args:
        session: An authenticated TableBuilderHTTPSession.
    """
    logger.info("Retrieving cross-tabulation data")
    session.richfaces_ajax(
        TABLEVIEW_URL,
        form_id="pageForm",
        component_id="pageForm:retB",
        extra_params={
            "dndItemType": "",
            "dndItemArg": "",
            "dndTargetType": "",
            "dndTargetArg": "",
            "javax.faces.partial.event": "click",
        },
    )


def select_csv_format(session: TableBuilderHTTPSession) -> None:
    """Select CSV as the download format from the dropdown control.

    Posts the format selection change event to the tableView JSF page,
    triggering the server to prepare CSV output.

    Args:
        session: An authenticated TableBuilderHTTPSession.
    """
    logger.info("Selecting CSV download format")
    session.jsf_post(
        TABLEVIEW_URL,
        {
            "downloadControl:downloadType": "CSV",
            "downloadControl_SUBMIT": "1",
            "javax.faces.behavior.event": "valueChange",
            "javax.faces.source": "downloadControl:downloadType",
            "javax.faces.partial.ajax": "true",
        },
    )


def _save_content(content: bytes, output_path: str) -> None:
    """Save download content to output_path, extracting CSV from ZIP if needed.

    If the content is a valid ZIP archive, extracts the first file from it
    and writes it to output_path. Otherwise, writes the raw bytes directly.

    Args:
        content: The raw bytes from the download response.
        output_path: Filesystem path where the CSV should be saved.
    """
    if zipfile.is_zipfile(io.BytesIO(content)):
        logger.debug("Downloaded content is a ZIP archive, extracting CSV")
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            # Extract the first file in the archive (the CSV)
            csv_name = zf.namelist()[0]
            with zf.open(csv_name) as src, open(output_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
    else:
        logger.debug("Downloaded content is raw CSV, saving directly")
        with open(output_path, "wb") as f:
            f.write(content)


def http_fetch_table(
    session: TableBuilderHTTPSession, request, output_path: str
) -> None:
    """Fetch a table via HTTP — the full pipeline.

    Composes all HTTP catalogue and table operations into a single
    end-to-end flow: find the database, open it, get the schema, select
    categories for each variable, assign axes, retrieve data, and download.

    Args:
        session: An authenticated TableBuilderHTTPSession.
        request: A TableRequest describing the table to fetch.
        output_path: Filesystem path where the CSV should be saved.

    Raises:
        NavigationError: If the database cannot be found in the catalogue.
        TableBuildError: If a requested variable is not found in the schema.
    """
    from tablebuilder.http_catalogue import find_database, find_variable, get_schema, open_database

    # 1. Get catalogue and find database
    tree = session.rest_get("/rest/catalogue/databases/tree")
    result = find_database(tree, request.dataset)
    if not result:
        from tablebuilder.navigator import NavigationError

        raise NavigationError(f"Database not found: {request.dataset}")
    path, db_node = result
    logger.info("Found database: %s", db_node["data"]["name"])

    # 2. Open database
    open_database(session, path)

    # 3. Get schema
    schema = get_schema(session)

    # 4. For each variable, find it, select categories, add to axis
    for var_name, axis in request.variable_axes().items():
        var_info = find_variable(schema, var_name)
        if not var_info:
            from tablebuilder.table_builder import TableBuildError

            raise TableBuildError(f"Variable not found in schema: {var_name}")
        logger.info("Adding %s to %s", var_name, axis.value)
        select_all_categories(session, schema, var_info)
        add_to_axis(session, axis.value)

    # 5. Retrieve data
    retrieve_data(session)
    select_csv_format(session)

    # 6. Download — use Playwright for the download step since the download
    # servlet requires browser-side JavaScript to trigger
    _playwright_download(session, output_path)
    logger.info("Downloaded table to %s", output_path)


def download_table(session: TableBuilderHTTPSession, output_path: str) -> None:
    """Download the cross-tabulation result as a CSV file.

    After building via REST/AJAX, do a regular JSF form submit (NOT AJAX)
    to get the full HTML page with download forms and a valid ViewState.
    Then POST the download form. For large tables, POST the queue form
    and poll saved tables.
    """
    import re
    import time
    from tablebuilder.http_session import extract_viewstate

    # Step 1: POST a regular form submit to get the full page with all forms.
    # The retrieve button (pageForm:retB) triggers a full page render.
    logger.info("Triggering full page render via form submit")
    page_resp = session._session.post(
        TABLEVIEW_URL,
        data={
            "pageForm:retB": "",
            "pageForm_SUBMIT": "1",
            "javax.faces.ViewState": session.viewstate,
        },
        allow_redirects=True,
    )
    page_html = page_resp.text
    page_vs = extract_viewstate(page_html)
    logger.info("Page response: %d bytes, ViewState: %s, has downloadControl: %s",
                len(page_html), bool(page_vs), "downloadControl" in page_html)

    if page_vs:
        session.viewstate = page_vs
    if "downloadControl" not in page_html:
        raise RuntimeError("Full page render did not include download forms")

    # Step 2: Try direct download
    logger.info("Attempting direct download with full-page ViewState")
    dl_resp = session._session.post(
        TABLEVIEW_URL,
        data={
            "downloadControl:downloadGoButton": "Download table",
            "downloadControl_SUBMIT": "1",
            "javax.faces.ViewState": session.viewstate,
        },
        allow_redirects=True,
    )

    content_type = dl_resp.headers.get("Content-Type", "")
    if "octet-stream" in content_type or "zip" in content_type:
        logger.info("Direct download succeeded")
        _save_content(dl_resp.content, output_path)
        return

    # Step 3: Direct download returned HTML — table too large, queue it
    logger.info("Direct download returned %s — queuing table", content_type)

    # Update ViewState from the download response
    dl_vs = extract_viewstate(dl_resp.text)
    if dl_vs:
        session.viewstate = dl_vs

    table_name = f"tb_{int(time.time())}"
    logger.info("Queuing as '%s'", table_name)

    # Queue via RichFaces AJAX — the queue button's onclick handler fires
    # RichFaces.ajax() with incId=1, not a regular form submit.
    queue_resp = session._session.post(
        TABLEVIEW_URL,
        data={
            "downloadTableModeForm:downloadTableNameTxt": table_name,
            "downloadTableModeForm:queueTableButton": "Queue table",
            "downloadTableModeForm_SUBMIT": "1",
            "javax.faces.ViewState": session.viewstate,
            "AJAX:EVENTS_COUNT": "1",
            "org.richfaces.ajax.component": "downloadTableModeForm:queueTableButton",
        },
        headers={
            "Faces-Request": "partial/ajax",
            "incId": "1",
        },
    )
    logger.info("Queue AJAX: status=%d, len=%d", queue_resp.status_code, len(queue_resp.content))

    # Check for error in the XML response
    if "errorMsg" in queue_resp.text or "failed" in queue_resp.text.lower():
        error_match = re.search(r'<span[^>]*>([^<]*failed[^<]*)</span>', queue_resp.text, re.IGNORECASE)
        error_text = error_match.group(1) if error_match else queue_resp.text[:200]
        raise RuntimeError(f"Queue submission failed: {error_text}")

    # Update ViewState from queue response
    queue_vs = extract_viewstate(queue_resp.text)
    if queue_vs:
        session.viewstate = queue_vs

    # Step 4: Poll saved tables page for our queued table
    SAVED_TABLES_URL = f"{BASE_URL}/jsf/tableView/openTable.xhtml"
    for attempt in range(240):  # up to 20 minutes
        saved_resp = session._session.get(SAVED_TABLES_URL)
        saved_html = saved_resp.text

        if table_name in saved_html and "Completed" in saved_html:
            job_ids = re.findall(r'downloadTable\?jobId=(\d+)', saved_html)
            if job_ids:
                job_id = job_ids[-1]
                logger.info("Table '%s' completed, jobId=%s", table_name, job_id)
                dl_resp = session._session.get(f"{DOWNLOAD_TABLE_URL}?jobId={job_id}")
                _save_content(dl_resp.content, output_path)
                logger.info("Saved to %s", output_path)
                return

        if attempt % 12 == 0:
            found = table_name in saved_html
            logger.info("Polling for '%s'... attempt %d (%s)", table_name, attempt + 1,
                        "queued" if found else "not found")
        time.sleep(5)

    raise RuntimeError(f"Table '{table_name}' did not complete within 20 minutes.")


def _playwright_download(session: TableBuilderHTTPSession, output_path: str) -> None:
    """Download the table using a brief Playwright session with transferred cookies.

    After HTTP-based login/build/retrieve, we transfer the session cookies to
    Playwright and use browser-side JavaScript to trigger the download. This
    handles the download servlet which requires browser JS to initiate.
    """
    import time as _time
    from playwright.sync_api import sync_playwright

    logger.info("Starting Playwright download session")

    # Transfer cookies from requests session to Playwright
    pw_cookies = []
    for cookie in session._session.cookies:
        # Playwright requires domain to start with . for domain-wide cookies
        domain = cookie.domain or "tablebuilder.abs.gov.au"
        if not domain.startswith("."):
            domain = "." + domain
        pw_cookies.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": domain,
            "path": cookie.path or "/",
            "secure": True,
        })

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(pw_cookies)
        page = context.new_page()

        # Navigate to tableView — the server should have our built table
        page.goto(TABLEVIEW_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # If we landed on the catalogue page, the session doesn't have an open DB.
        # That's expected — the JSF server state is separate. Click retrieve to
        # trigger auto-retrieve which rebuilds the table on this Playwright session.
        if "dataCatalogueExplorer" in page.url:
            logger.info("Landed on catalogue — need to open DB in Playwright too")
            # Just use the full Playwright queue flow from scratch
            browser.close()
            _playwright_full_fallback(session, output_path)
            return

        # Click the retrieve button to trigger server-side cross-tabulation
        ret_btn = page.query_selector("#pageForm\\:retB")
        if ret_btn:
            logger.info("Clicking retrieve button")
            ret_btn.click(force=True)

        # Wait for data to appear
        for _ in range(30):
            cells = page.query_selector_all("td")
            data_cells = [c for c in cells[:30]
                          if (c.text_content() or "").strip().replace(",", "").isdigit()]
            if data_cells:
                logger.info("Table data visible (%d cells)", len(data_cells))
                break
            page.wait_for_timeout(2000)

        # Select CSV format if dropdown exists
        fmt = page.query_selector("#downloadControl\\:downloadType")
        if fmt:
            page.select_option("#downloadControl\\:downloadType", "CSV")
            page.wait_for_timeout(500)

        # Try direct download button
        dl_btn = page.query_selector(
            '#downloadControl\\:downloadGoButton, input[value="Download table"]'
        )
        if dl_btn:
            logger.info("Clicking download button")
            try:
                with page.expect_download(timeout=30000) as dl_info:
                    dl_btn.click()
                download = dl_info.value
                download.save_as(output_path)
                _extract_if_zip(output_path)
                logger.info("Downloaded via direct button to %s", output_path)
                browser.close()
                return
            except Exception as e:
                logger.warning("Direct download failed: %s", e)

        # Fall back to queue flow via Playwright
        logger.info("Falling back to Playwright queue flow")
        from tablebuilder.downloader import queue_and_download
        queue_and_download(page, output_path)
        browser.close()


def _playwright_full_fetch(config, request, output_path: str, jl=None) -> None:
    """Fetch a table entirely via Playwright — login, build, download.

    Used when HTTP direct download fails. Does everything in a single
    Playwright browser session using the existing table_builder and
    downloader modules from the CLI.
    """
    from playwright.sync_api import sync_playwright
    from tablebuilder.browser import TableBuilderSession
    from tablebuilder.table_builder import add_variables_and_build
    from tablebuilder.downloader import queue_and_download
    from tablebuilder.knowledge import KnowledgeBase

    knowledge = KnowledgeBase()

    with TableBuilderSession(config, headless=True, knowledge=knowledge) as tb_session:
        page = tb_session.page

        # Navigate to the dataset
        if jl:
            jl.log_progress("Browser: finding dataset...")
        from tablebuilder.navigator import Navigator
        nav = Navigator(page, knowledge=knowledge)
        nav.open_dataset(request.dataset)

        # Build the table
        if jl:
            jl.log_progress("Browser: adding variables...")
        add_variables_and_build(page, request, knowledge=knowledge)

        # Download
        if jl:
            jl.log_progress("Browser: downloading...")
        queue_and_download(page, output_path, knowledge=knowledge)

    knowledge.save()
    logger.info("Playwright full fetch completed: %s", output_path)


def playwright_build_and_download(config, request, output_path: str) -> None:
    """Build and download a table entirely in a single Playwright session.

    Used when HTTP direct download fails (large tables). Logs in via Playwright,
    uses HTTP REST calls within the same session to build the table (fast),
    then uses the browser to queue and download.
    """
    from playwright.sync_api import sync_playwright
    import time as _time
    from tablebuilder.http_catalogue import find_database, open_database, get_schema, find_variable

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Login via Playwright
        page.goto(f"{BASE_URL}/jsf/login.xhtml", wait_until="networkidle")
        page.fill("#loginForm\\:username2", config.user_id)
        page.fill("#loginForm\\:password2", config.password)
        page.click("#loginForm\\:login2")
        page.wait_for_load_state("networkidle", timeout=15000)
        if "terms.xhtml" in page.url:
            page.click("#termsForm\\:termsButton")
            page.wait_for_load_state("networkidle", timeout=10000)
        logger.info("Playwright logged in for full build+download")

        # Extract cookies from Playwright and create an HTTP session
        pw_cookies = page.context.cookies()
        import requests
        http_session = requests.Session()
        for c in pw_cookies:
            http_session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

        # Create a lightweight session wrapper that shares Playwright's cookies
        session = TableBuilderHTTPSession(config)
        session._session = http_session

        # Get ViewState from the catalogue page
        from tablebuilder.http_session import extract_viewstate
        resp = http_session.get(f"{BASE_URL}/jsf/dataCatalogueExplorer.xhtml")
        vs = extract_viewstate(resp.text)
        if vs:
            session._viewstate = vs

        # Build table via HTTP REST (fast) using Playwright's session cookies
        tree = session.rest_get("/rest/catalogue/databases/tree")
        result = find_database(tree, request.dataset)
        if not result:
            browser.close()
            raise RuntimeError(f"Database not found: {request.dataset}")
        path, db_node = result
        open_database(session, path)
        schema = get_schema(session)

        for var_name, axis in request.variable_axes().items():
            var_info = find_variable(schema, var_name)
            if not var_info:
                browser.close()
                raise RuntimeError(f"Variable not found: {var_name}")
            select_all_categories(session, schema, var_info)
            add_to_axis(session, axis.value)

        retrieve_data(session)
        select_csv_format(session)
        logger.info("Table built via HTTP in Playwright session")

        # Now navigate Playwright to tableView — same session, should have the table
        page.goto(f"{BASE_URL}/jsf/tableView.xhtml", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        if "dataCatalogueExplorer" in page.url:
            browser.close()
            raise RuntimeError("Playwright redirected to catalogue despite building table via HTTP")

        # Use the existing Playwright downloader
        from tablebuilder.downloader import queue_and_download
        queue_and_download(page, output_path)
        browser.close()
        logger.info("Large table downloaded to %s", output_path)


def _playwright_queue_and_download(
    session: TableBuilderHTTPSession, output_path: str, table_name: str,
) -> None:
    """Queue a table via Playwright and poll saved tables until it completes.

    The HTTP session already built the table on the server. Playwright logs in
    as the same user, navigates to tableView (where the built table should be),
    opens the queue dialog, submits with our table_name, then polls the saved
    tables page until "Completed, click here to download" appears.
    """
    from playwright.sync_api import sync_playwright
    import time as _time

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Login via Playwright
        page.goto(f"{BASE_URL}/jsf/login.xhtml", wait_until="networkidle")
        page.fill("#loginForm\\:username2", session.config.user_id)
        page.fill("#loginForm\\:password2", session.config.password)
        page.click("#loginForm\\:login2")
        page.wait_for_load_state("networkidle", timeout=15000)
        if "terms.xhtml" in page.url:
            page.click("#termsForm\\:termsButton")
            page.wait_for_load_state("networkidle", timeout=10000)
        logger.info("Playwright logged in")

        # Navigate to tableView — server should have our built table
        page.goto(f"{BASE_URL}/jsf/tableView.xhtml", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # If redirected to catalogue, no table is available
        if "dataCatalogueExplorer" in page.url:
            browser.close()
            raise RuntimeError(
                "Playwright session redirected to catalogue — no table available. "
                "The HTTP session's server state may have expired."
            )

        # Open the queue dialog by clicking the downloadTableMode link
        queue_dialog_link = page.query_selector("#downloadTableModePanelFirstHref")
        if queue_dialog_link:
            queue_dialog_link.click()
            page.wait_for_timeout(1000)
        else:
            # Try clicking the retrieve button first, then the queue dialog
            ret_btn = page.query_selector("#pageForm\\:retB")
            if ret_btn:
                ret_btn.click(force=True)
                page.wait_for_timeout(5000)

        # Fill in the table name and submit
        name_input = page.query_selector("#downloadTableModeForm\\:downloadTableNameTxt")
        if name_input:
            name_input.fill(table_name)
            page.wait_for_timeout(500)
            queue_btn = page.query_selector("#downloadTableModeForm\\:queueTableButton")
            if queue_btn:
                queue_btn.click()
                page.wait_for_timeout(3000)
                logger.info("Queued table as '%s'", table_name)
            else:
                logger.warning("Queue button not found")
        else:
            logger.warning("Queue name input not found — trying direct queue via large table mode")
            # Try the large table mode dialog instead
            ltm_ok = page.query_selector("#largeTableModeForm\\:largeTableModeOKButton")
            if ltm_ok:
                ltm_ok.click()
                page.wait_for_timeout(3000)

        # Navigate to saved tables and poll for completion
        saved_url = f"{BASE_URL}/jsf/tableView/openTable.xhtml"
        for attempt in range(240):  # up to 20 minutes
            page.goto(saved_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1000)
            page_text = page.content()

            if table_name in page_text and "Completed" in page_text:
                # Find download links
                links = page.query_selector_all('a:has-text("click here to download")')
                for link in links:
                    row = link.evaluate("el => el.closest('tr') ? el.closest('tr').textContent : ''")
                    if table_name in row:
                        logger.info("Table '%s' completed, downloading", table_name)
                        try:
                            with page.expect_download(timeout=60000) as dl_info:
                                link.click()
                            download = dl_info.value
                            download.save_as(output_path)
                            _extract_if_zip(output_path)
                            logger.info("Downloaded to %s", output_path)
                            browser.close()
                            return
                        except Exception as e:
                            logger.warning("Download click failed: %s", e)

            if attempt % 12 == 0:
                logger.info("Polling for '%s'... attempt %d", table_name, attempt + 1)
            _time.sleep(5)

        browser.close()
        raise RuntimeError(
            f"Table '{table_name}' did not complete within 20 minutes."
        )


def _extract_if_zip(path: str) -> None:
    """If the file at path is a ZIP, extract the first file and replace."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
                if names:
                    csv_name = names[0]
                    with zf.open(csv_name) as src:
                        content = src.read()
                    with open(path, "wb") as f:
                        f.write(content)
                    logger.debug("Extracted %s from ZIP", csv_name)
    except Exception as e:
        logger.warning("ZIP extraction failed: %s", e)
