# ABOUTME: Table construction — add variables to rows, columns, and wafers.
# ABOUTME: Drives the TableBuilder UI to search variables, select categories, and assign axes.

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from tablebuilder.models import Axis, TableRequest
from tablebuilder.navigator import search_variable, _expand_all_collapsed


class TableBuildError(Exception):
    """Raised when table construction fails."""


# JSF element IDs for the axis assignment buttons (wafer is "addL" for Layer)
AXIS_BUTTON_ID = {
    Axis.ROW: "buttonForm:addR",
    Axis.COL: "buttonForm:addC",
    Axis.WAFER: "buttonForm:addL",
}


def _find_variable_node(page: Page, variable_name: str):
    """Find the tree node element for a specific variable by exact label match."""
    nodes = page.query_selector_all('.treeNodeElement')
    for node in nodes:
        label = node.query_selector('.label')
        if label and (label.text_content() or '').strip() == variable_name:
            expander = node.query_selector('.treeNodeExpander')
            # Variable nodes are expanded or collapsed, not leaf
            if expander and 'leaf' not in (expander.get_attribute('class') or ''):
                return node
    return None


def _check_variable_categories(page: Page, variable_name: str) -> int:
    """Check all leaf category checkboxes belonging to a variable.

    Walks the sibling tree nodes after the variable node, checking all
    consecutive leaf nodes until hitting a non-leaf node.
    """
    nodes = page.query_selector_all('.treeNodeElement')
    all_nodes = list(nodes)

    # Find the variable node index
    target_idx = -1
    for i, node in enumerate(all_nodes):
        label = node.query_selector('.label')
        if label and (label.text_content() or '').strip() == variable_name:
            expander = node.query_selector('.treeNodeExpander')
            if expander and 'leaf' not in (expander.get_attribute('class') or ''):
                target_idx = i
                break

    if target_idx < 0:
        raise TableBuildError(f"Cannot find variable '{variable_name}' in the tree.")

    # Check consecutive leaf siblings after the variable node
    checked = 0
    for node in all_nodes[target_idx + 1:]:
        expander = node.query_selector('.treeNodeExpander')
        if not expander or 'leaf' not in (expander.get_attribute('class') or ''):
            break
        cb = node.query_selector('input[type=checkbox]')
        if cb and not cb.is_checked():
            cb.click()
            page.wait_for_timeout(200)
        if cb:
            checked += 1

    return checked


def _submit_axis_button(page: Page, axis: Axis) -> None:
    """Submit the axis assignment button via form submission.

    The JSF axis buttons (Add to Row/Column/Wafer) require form submission
    rather than dispatch_event or regular click to trigger the server-side
    action properly.
    """
    button_id = AXIS_BUTTON_ID[axis]
    css_id = button_id.replace(':', '\\\\:')

    page.evaluate(
        f"""
        () => {{
            const btn = document.querySelector('#{css_id}');
            if (!btn || !btn.form) throw new Error('Axis button or form not found');
            const form = btn.form;
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = btn.name;
            input.value = btn.value;
            form.appendChild(input);
            form.submit();
        }}
        """
    )
    page.wait_for_timeout(5000)


def add_variable(page: Page, variable_name: str, axis: Axis) -> None:
    """Search for a variable, select all its categories, and add to the given axis."""
    search_variable(page, variable_name)

    # Expand all collapsed groups to reveal variables and their categories
    _expand_all_collapsed(page)
    page.wait_for_timeout(500)

    # Check only the target variable's category checkboxes
    checked = _check_variable_categories(page, variable_name)
    if checked == 0:
        raise TableBuildError(
            f"No categories found for variable '{variable_name}'."
        )

    page.wait_for_timeout(300)

    # Submit the axis button via form submission
    _submit_axis_button(page, axis)

    # Verify the table is no longer empty
    page_text = page.evaluate("() => document.body.innerText.substring(0, 500)")
    if "Your table is empty" in page_text:
        raise TableBuildError(
            f"Failed to add '{variable_name}' to {axis.value}. "
            "Table is still empty after submission."
        )


def build_table(page: Page, request: TableRequest) -> None:
    """Add all variables from a TableRequest to their respective axes."""
    for var in request.rows:
        add_variable(page, var, Axis.ROW)

    for var in request.cols:
        add_variable(page, var, Axis.COL)

    for var in request.wafers:
        add_variable(page, var, Axis.WAFER)
