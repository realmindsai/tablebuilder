# ABOUTME: HTTP table operations for ABS TableBuilder category selection and axis assignment.
# ABOUTME: Builds REST payloads, selects checkbox categories, and assigns variables to table axes.

from __future__ import annotations

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
