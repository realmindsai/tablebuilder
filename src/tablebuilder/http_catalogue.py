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
    # Split fragment into words for scoring
    fragment_words = set(fragment_lower.split())
    matches: list[tuple[int, list[str], dict]] = []

    def _walk(nodes: list[dict], path: list[str]) -> None:
        for node in nodes:
            key = node.get("key", "")
            current_path = path + [key]
            data = node.get("data", {})

            if (
                data.get("type") == "DATABASE"
                and fragment_lower in data.get("name", "").lower()
            ):
                # Score: count how many query words appear in the name
                name_lower = data.get("name", "").lower()
                score = sum(1 for w in fragment_words if w in name_lower)
                matches.append((score, current_path, node))

            children = node.get("children", [])
            if children:
                _walk(children, current_path)

    _walk(tree.get("nodeList", []), [])

    if not matches:
        return None

    # Sort by score descending, pick best match
    matches.sort(key=lambda m: m[0], reverse=True)
    return matches[0][1], matches[0][2]


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

    # Step 2a: Fire selectedDatabase to tell JSF which node is active
    logger.info("Firing selectedDatabase AJAX to notify JSF")
    session.richfaces_ajax(
        catalogue_url,
        form_id="j_id_3f",
        component_id="j_id_3n",
    )

    # Step 2b: Fire the doubleClickDatabase AJAX action
    logger.info("Firing doubleClickDatabase AJAX action")
    session.richfaces_ajax(
        catalogue_url,
        form_id="j_id_3f",
        component_id="j_id_3i",
    )

    # Step 3: GET the tableView page and update ViewState
    logger.info("Navigating to tableView page")
    resp = session._session.get(tableview_url)
    new_vs = extract_viewstate(resp.text)
    if new_vs:
        session.viewstate = new_vs
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
                levels = data.get("levels", []) or [
                    child.get("data", {}).get("name", "")
                    for child in children
                ]
                schema[name] = {
                    "key": key,
                    "group": group_path,
                    "child_count": data.get("childCount", len(children)),
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
    import re

    # 1. Exact match
    if name in schema:
        return schema[name]

    # 2. Code match — extract codes from parentheses like "Sex Male/Female (SEXP)"
    #    and from "CODE Label" format like "SEXP Sex"
    name_upper = name.split()[0] if name.split() else name
    for var_name, info in schema.items():
        # Match code in parentheses: "Something (CODE)"
        paren_match = re.search(r'\((\w+)\)', var_name)
        if paren_match and paren_match.group(1).upper() == name_upper.upper():
            return info
        # Match "CODE Label" format
        parts = var_name.split()
        if parts and parts[0].upper() == name_upper.upper():
            return info

    # 3. Case-insensitive substring match
    name_lower = name.lower()
    for var_name, info in schema.items():
        if name_lower in var_name.lower():
            return info

    # 4. Word-level match — all words in name appear in var_name
    name_words = set(name_lower.split())
    for var_name, info in schema.items():
        var_lower = var_name.lower()
        if all(w in var_lower for w in name_words):
            return info

    return None
