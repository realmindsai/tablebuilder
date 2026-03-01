# ABOUTME: Table construction — add variables to rows, columns, and wafers.
# ABOUTME: Drives the TableBuilder UI to search variables, select categories, and assign axes.

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from tablebuilder.models import Axis, TableRequest
from tablebuilder.navigator import search_variable


class TableBuildError(Exception):
    """Raised when table construction fails."""


AXIS_BUTTON_TEXT = {
    Axis.ROW: "Add to Row",
    Axis.COL: "Add to Column",
    Axis.WAFER: "Add to Wafer",
}


def add_variable(page: Page, variable_name: str, axis: Axis) -> None:
    """Search for a variable, select all its categories, and add to the given axis."""
    search_variable(page, variable_name)

    # Find the variable in the tree and click to expand it
    var_node = page.get_by_text(variable_name).first
    if not var_node:
        raise TableBuildError(f"Variable '{variable_name}' not found in dataset.")

    var_node.click()
    page.wait_for_timeout(500)

    # Select all categories — look for a "Select all" checkbox or check all boxes
    select_all = page.query_selector(
        "input[type='checkbox'][title*='Select all'], "
        "input[type='checkbox'][aria-label*='Select all']"
    )
    if select_all:
        select_all.check()
    else:
        # Check individual category checkboxes
        checkboxes = page.query_selector_all(
            ".category-checkbox, input[type='checkbox']"
        )
        for cb in checkboxes:
            if not cb.is_checked():
                cb.check()

    page.wait_for_timeout(300)

    # Click the "Add to Row/Column/Wafer" button
    button_text = AXIS_BUTTON_TEXT[axis]
    try:
        button = page.get_by_text(button_text).first
        if not button:
            raise TableBuildError(f"Cannot find '{button_text}' button.")
        button.click()
        page.wait_for_timeout(1000)
    except PlaywrightTimeout:
        raise TableBuildError(
            f"Timed out clicking '{button_text}' for variable '{variable_name}'."
        )


def build_table(page: Page, request: TableRequest) -> None:
    """Add all variables from a TableRequest to their respective axes."""
    for var in request.rows:
        add_variable(page, var, Axis.ROW)

    for var in request.cols:
        add_variable(page, var, Axis.COL)

    for var in request.wafers:
        add_variable(page, var, Axis.WAFER)
