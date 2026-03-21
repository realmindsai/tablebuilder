# ABOUTME: HTTP catalogue operations for ABS TableBuilder database navigation.
# ABOUTME: Provides find_database, open_database, get_schema, and find_variable functions.

from __future__ import annotations

from tablebuilder.http_session import BASE_URL, TableBuilderHTTPSession, extract_viewstate
from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.http_catalogue")


def find_database(
    tree: dict, name_fragment: str
) -> tuple[list[str], dict] | None:
    """Walk the catalogue tree JSON to find a DATABASE node by name substring.

    Searches case-insensitively through all nodes in the tree returned by
    GET /rest/catalogue/databases/tree. Only matches nodes whose data.type
    is "DATABASE".

    Args:
        tree: The catalogue tree dict with a "nodeList" key.
        name_fragment: Case-insensitive substring to match against node names.

    Returns:
        A tuple of (path_of_keys, node_dict) if found, or None.
    """
    fragment_lower = name_fragment.lower()

    def _walk(nodes: list[dict], path: list[str]) -> tuple[list[str], dict] | None:
        for node in nodes:
            key = node.get("key", "")
            current_path = path + [key]
            data = node.get("data", {})

            if (
                data.get("type") == "DATABASE"
                and fragment_lower in data.get("name", "").lower()
            ):
                return current_path, node

            children = node.get("children", [])
            if children:
                result = _walk(children, current_path)
                if result is not None:
                    return result

        return None

    return _walk(tree.get("nodeList", []), [])


def open_database(
    session: TableBuilderHTTPSession, path: list[str]
) -> None:
    """Open a database by navigating through the catalogue.

    Performs three steps:
    1. POST the selected node path to the REST catalogue endpoint
    2. Fire doubleClickDatabase via RichFaces AJAX on the catalogue page
    3. GET the tableView page to navigate there, updating ViewState

    Args:
        session: An authenticated TableBuilderHTTPSession.
        path: List of node keys from root to the target database.
    """
    catalogue_url = f"{BASE_URL}/jsf/dataCatalogueExplorer.xhtml"
    tableview_url = f"{BASE_URL}/jsf/tableView/tableView.xhtml"

    # Step 1: POST the selected path to the REST endpoint
    logger.info("Selecting database node with path: %s", path)
    session.rest_post("/rest/catalogue/databases/tree", {"currentNode": path})

    # Step 2: Fire the doubleClickDatabase AJAX action
    logger.info("Firing doubleClickDatabase AJAX action")
    session.richfaces_ajax(
        catalogue_url,
        form_id="j_id_3f",
        component_id="j_id_3i",
        extra_params={"doubleClickDatabase": "doubleClickDatabase"},
    )

    # Step 3: GET the tableView page and update ViewState
    logger.info("Navigating to tableView page")
    resp = session._session.get(tableview_url)
    new_vs = extract_viewstate(resp.text)
    if new_vs:
        session._viewstate = new_vs
        logger.debug("ViewState updated from tableView page")


def get_schema(session: TableBuilderHTTPSession) -> dict:
    """Fetch and parse the table schema tree for the currently open database.

    GETs /rest/catalogue/tableSchema/tree and walks all nodes, collecting
    every variable node (iconType == "FIELD" or draggable == True).

    Args:
        session: An authenticated TableBuilderHTTPSession with a database open.

    Returns:
        A dict mapping variable names to their metadata:
        {variable_name: {"key": key, "group": group_path,
                         "child_count": N, "levels": [...]}}
    """
    tree = session.rest_get("/rest/catalogue/tableSchema/tree")
    schema: dict[str, dict] = {}

    def _walk(nodes: list[dict], group_path: str) -> None:
        for node in nodes:
            data = node.get("data", {})
            key = node.get("key", "")
            name = data.get("name", "")
            children = node.get("children", [])

            is_field = (
                data.get("iconType") == "FIELD" or data.get("draggable") is True
            )

            if is_field:
                levels = [
                    child.get("data", {}).get("name", "")
                    for child in children
                ]
                schema[name] = {
                    "key": key,
                    "group": group_path,
                    "child_count": len(children),
                    "levels": levels,
                }
            else:
                # Non-field node: recurse into children with updated group path
                child_group = f"{group_path}/{name}" if group_path else name
                _walk(children, child_group)

    _walk(tree.get("nodeList", []), "")

    logger.info("Schema loaded: %d variables", len(schema))
    return schema


def find_variable(schema: dict, name: str) -> dict | None:
    """Find a variable in the schema dict by name, code prefix, or substring.

    Match priority:
    1. Exact match on key (variable name)
    2. Code prefix match: if schema has "SEXP Sex", match on "SEXP" or "Sex"
    3. Case-insensitive substring match

    Args:
        schema: Dict returned by get_schema().
        name: Search string (variable name, code, or substring).

    Returns:
        The variable info dict, or None if not found.
    """
    # 1. Exact match
    if name in schema:
        return schema[name]

    # 2. Code prefix / label word match (split schema key on space)
    for var_name, info in schema.items():
        parts = var_name.split()
        if name in parts:
            return info

    # 3. Case-insensitive substring match
    name_lower = name.lower()
    for var_name, info in schema.items():
        if name_lower in var_name.lower():
            return info

    return None
