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

    # Extract category keys from the response
    category_keys = []
    if response and "nodeList" in response:
        for node in response["nodeList"]:
            for child in node.get("children", []):
                category_keys.append(child["key"])

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

    Tries direct download first by submitting the downloadGoButton.
    If the response is not binary (application/octet-stream), falls back
    to the queue flow: navigate to saved tables, find the latest job,
    and download via the download servlet.

    Args:
        session: An authenticated TableBuilderHTTPSession.
        output_path: Filesystem path where the CSV should be saved.
    """
    logger.info("Attempting direct table download")

    # Try direct download via the Go button (regular form submit, not AJAX)
    resp = session._session.post(
        TABLEVIEW_URL,
        data={
            "downloadControl:downloadGoButton": "Download table",
            "downloadControl_SUBMIT": "1",
            "javax.faces.ViewState": session.viewstate,
        },
        allow_redirects=True,
    )

    content_type = resp.headers.get("Content-Type", "")
    if "octet-stream" in content_type or "zip" in content_type:
        logger.info("Direct download succeeded, saving to %s", output_path)
        _save_content(resp.content, output_path)
        # Update ViewState if the response has one
        from tablebuilder.http_session import extract_viewstate
        new_vs = extract_viewstate(resp.text if hasattr(resp, 'text') else "")
        if new_vs:
            session.viewstate = new_vs
        return

    # Fall back to queue flow
    logger.info("Direct download returned %s, falling back to queue flow", content_type)

    # Queue the table via the downloadTableMode dialog
    import time
    table_name = f"tb_{int(time.time())}"
    logger.info("Queuing table as '%s'", table_name)

    # Open queue dialog and submit
    session.jsf_post(TABLEVIEW_URL, {
        "downloadTableModeForm:downloadTableNameTxt": table_name,
        "downloadTableModeForm:queueTableButton": "Queue",
        "downloadTableModeForm_SUBMIT": "1",
    })

    # Navigate to saved tables page
    resp = session._session.get(OPEN_TABLE_URL)
    from tablebuilder.http_session import extract_viewstate
    new_vs = extract_viewstate(resp.text)
    if new_vs:
        session.viewstate = new_vs

    # Poll for the download to be ready
    for attempt in range(60):
        jobs_tree = session.rest_get(MANAGE_TABLES_PATH)
        # Walk the tree to find a node with a jobId
        def find_job(nodes):
            for node in nodes:
                data = node.get("data", {})
                if data.get("jobId"):
                    return data
                children = node.get("children", [])
                result = find_job(children)
                if result:
                    return result
            return None

        job = find_job(jobs_tree.get("nodeList", []))
        if job and job.get("jobId"):
            job_id = job["jobId"]
            logger.info("Found job %s, downloading", job_id)
            download_url = f"{DOWNLOAD_TABLE_URL}?jobId={job_id}"
            resp = session._session.get(download_url)
            _save_content(resp.content, output_path)
            logger.info("Table saved to %s", output_path)
            return

        logger.debug("Polling for download... attempt %d", attempt + 1)
        time.sleep(5)

    raise RuntimeError("Download timed out after 5 minutes of polling.")


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
        pw_cookies.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or "tablebuilder.abs.gov.au",
            "path": cookie.path or "/",
        })

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(pw_cookies)
        page = context.new_page()

        # Navigate to tableView — the server should have our built table
        page.goto(TABLEVIEW_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # If we landed on the catalogue page instead, the session transfer failed
        if "dataCatalogueExplorer" in page.url:
            logger.warning("Session transfer failed, falling back to queue flow in Playwright")
            browser.close()
            raise RuntimeError(
                "Playwright session transfer failed — landed on catalogue instead of tableView. "
                "The HTTP session cookies may not carry the JSF server state."
            )

        # Wait for data to appear (auto-retrieve may need time)
        for _ in range(15):
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
                # Extract CSV from ZIP if needed
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
