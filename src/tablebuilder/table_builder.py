# ABOUTME: Table construction — add variables to rows, columns, and wafers.
# ABOUTME: Drives the TableBuilder UI to search variables, select categories, and assign axes.

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from tablebuilder.models import Axis, TableRequest
from tablebuilder.navigator import search_variable, _expand_node


class TableBuildError(Exception):
    """Raised when table construction fails."""


# JSF element IDs for the axis assignment buttons (wafer is "addL" for Layer)
AXIS_BUTTON_ID = {
    Axis.ROW: "buttonForm:addR",
    Axis.COL: "buttonForm:addC",
    Axis.WAFER: "buttonForm:addL",
}


def add_variable(page: Page, variable_name: str, axis: Axis) -> None:
    """Search for a variable, select all its categories, and add to the given axis."""
    search_variable(page, variable_name)

    # Expand the variable node in the tree to reveal its categories
    _expand_node(page, variable_name)
    page.wait_for_timeout(500)

    # Select category checkboxes — leaf nodes with checkboxes under the variable
    nodes = page.query_selector_all('.treeNodeElement')
    for node in nodes:
        expander = node.query_selector('.treeNodeExpander')
        if expander and 'leaf' in (expander.get_attribute('class') or ''):
            cb = node.query_selector('input[type=checkbox]')
            if cb and not cb.is_checked():
                cb.check()

    page.wait_for_timeout(300)

    # Click the axis button using dispatch_event (button may be invisible to .click())
    button_id = AXIS_BUTTON_ID[axis]
    # Escape the colon for CSS selector: "buttonForm:addR" -> "#buttonForm\:addR"
    css_selector = '#' + button_id.replace(':', '\\:')
    button = page.query_selector(css_selector)
    if not button:
        raise TableBuildError(
            f"Cannot find axis button '#{button_id}' for {axis.value}."
        )
    button.dispatch_event('click')
    page.wait_for_timeout(1000)


def build_table(page: Page, request: TableRequest) -> None:
    """Add all variables from a TableRequest to their respective axes."""
    for var in request.rows:
        add_variable(page, var, Axis.ROW)

    for var in request.cols:
        add_variable(page, var, Axis.COL)

    for var in request.wafers:
        add_variable(page, var, Axis.WAFER)
