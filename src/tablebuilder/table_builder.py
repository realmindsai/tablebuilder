# ABOUTME: Table construction — add variables to rows, columns, and wafers.
# ABOUTME: Drives the TableBuilder UI to search variables, select categories, and assign axes.

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from tablebuilder.logging_config import get_logger
from tablebuilder.models import Axis, TableRequest
from tablebuilder.navigator import search_variable, _expand_all_collapsed
from tablebuilder.resilience import find_all_elements
from tablebuilder.selectors import TREE_NODE, AXIS_BUTTONS

logger = get_logger("tablebuilder.table_builder")


class TableBuildError(Exception):
    """Raised when table construction fails."""


def _label_matches(ui_text: str, variable_name: str) -> bool:
    """Check if a UI tree label matches a variable name.

    ABS tree labels include a code prefix like "SEXP Sex" or "AGEP Age".
    The dictionary stores these separately (code: SEXP, label: Sex).
    This function matches against:
    1. Exact match: "Sex" == "Sex"
    2. Code-prefixed: "SEXP Sex" ends with " Sex"
    3. Full UI label: "SEXP Sex" == "SEXP Sex"
    """
    if ui_text == variable_name:
        return True
    # Code-prefixed label: "SEXP Sex" — check if text after first space matches
    space_idx = ui_text.find(' ')
    if space_idx > 0 and ui_text[space_idx + 1:] == variable_name:
        return True
    return False


def _find_variable_node(page: Page, variable_name: str):
    """Find the tree node element for a specific variable by label match.

    Handles ABS tree labels which include a code prefix (e.g. "SEXP Sex").
    """
    nodes = find_all_elements(page, TREE_NODE)

    # Pass 1: exact or code-prefixed match with non-leaf expander
    for node in nodes:
        label = node.query_selector('.label')
        if not label:
            continue
        text = (label.text_content() or '').strip()
        if _label_matches(text, variable_name):
            expander = node.query_selector('.treeNodeExpander')
            if expander and 'leaf' not in (expander.get_attribute('class') or ''):
                logger.debug("Found variable '%s' matching UI label '%s'", variable_name, text)
                return node

    # Pass 2: case-insensitive match with non-leaf expander
    name_lower = variable_name.lower()
    for node in nodes:
        label = node.query_selector('.label')
        if not label:
            continue
        text = (label.text_content() or '').strip()
        text_lower = text.lower()
        if text_lower == name_lower or (text_lower.find(' ') > 0 and text_lower[text_lower.find(' ') + 1:] == name_lower):
            expander = node.query_selector('.treeNodeExpander')
            if expander and 'leaf' not in (expander.get_attribute('class') or ''):
                logger.info("Found variable '%s' via case-insensitive match with '%s'", variable_name, text)
                return node

    # Pass 3: match by code prefix — if variable_name looks like a code (e.g. "OCCP"),
    # match tree labels that start with it (e.g. "OCCP Occupation")
    name_upper = variable_name.upper()
    for node in nodes:
        label = node.query_selector('.label')
        if not label:
            continue
        text = (label.text_content() or '').strip()
        if text.upper().startswith(name_upper + ' '):
            expander = node.query_selector('.treeNodeExpander')
            if expander and 'leaf' not in (expander.get_attribute('class') or ''):
                logger.info("Found variable '%s' via code prefix match with '%s'", variable_name, text)
                return node

    return None


def _is_variable_node(label_text: str) -> bool:
    """Detect if a tree node label looks like a variable header (CODE Label (N)).

    ABS variable nodes show as "CODE Label (N)" where CODE is 3-8 uppercase
    letters/digits and (N) is a pure digit count at the END of the label
    (e.g. "SEXP Sex (2)", "INDP Industry of Employment (19)").
    Labels like "Hours Worked (ranges)" or "Method of Travel (6 travel modes)"
    are NOT variable headers — their parenthesized content is descriptive, not a count.
    """
    import re
    # Match: code prefix + label + count suffix at end like "SEXP Sex (2)"
    # The \(\d+\)\s*$ ensures the digits-only paren is at the end
    if re.match(r'^[A-Z][A-Z0-9]{2,}\s.+\(\d+\)\s*$', label_text):
        return True
    return False


def _check_variable_categories(page: Page, variable_name: str) -> int:
    """Check all leaf category checkboxes belonging to a variable.

    Walks tree nodes after the variable node, checking leaf checkboxes.
    Skips intermediate sub-group nodes (non-leaf, non-variable) and stops
    when hitting the next variable-level node (detected by code prefix pattern).
    """
    nodes = find_all_elements(page, TREE_NODE)
    all_nodes = list(nodes)

    # Find the variable node index — try label match, then code prefix
    target_idx = -1
    name_upper = variable_name.upper()
    for i, node in enumerate(all_nodes):
        label = node.query_selector('.label')
        if not label:
            continue
        text = (label.text_content() or '').strip()
        matched = _label_matches(text, variable_name) or \
                  text.upper().startswith(name_upper + ' ')
        if matched:
            expander = node.query_selector('.treeNodeExpander')
            if expander and 'leaf' not in (expander.get_attribute('class') or ''):
                target_idx = i
                break

    if target_idx < 0:
        raise TableBuildError(f"Cannot find variable '{variable_name}' in the tree.")

    # Walk nodes after the variable, checking leaf category checkboxes.
    # Skip intermediate sub-group nodes but stop at the next variable node.
    # Handles stale DOM handles gracefully — breaks on protocol errors.
    checked = 0
    for node in all_nodes[target_idx + 1:]:
        try:
            expander = node.query_selector('.treeNodeExpander')
        except Exception:
            logger.warning("Stale DOM handle during category walk, stopping")
            break

        if not expander:
            break

        try:
            exp_class = expander.get_attribute('class') or ''
        except Exception:
            logger.warning("Stale expander handle, stopping category walk")
            break

        if 'leaf' in exp_class:
            # Leaf node — check its checkbox
            try:
                cb = node.query_selector('input[type=checkbox]')
                if cb and not cb.is_checked():
                    cb.click()
                    page.wait_for_timeout(200)
                if cb:
                    checked += 1
            except Exception:
                logger.warning("Stale handle checking category, skipping")
                continue
        else:
            # Non-leaf node — check if it's the next variable (stop)
            # or an intermediate sub-group (skip)
            try:
                label = node.query_selector('.label')
                text = (label.text_content() or '').strip() if label else ''
            except Exception:
                break
            if _is_variable_node(text):
                break
            # Otherwise it's a sub-group header — skip and continue

    return checked


def _submit_axis_button(page: Page, axis: Axis) -> None:
    """Submit the axis assignment button via form submission.

    The JSF axis buttons (Add to Row/Column/Wafer) require form submission
    rather than dispatch_event or regular click to trigger the server-side
    action properly.
    """
    selector_entry = AXIS_BUTTONS[axis]
    # Extract the raw JSF ID from the CSS selector primary
    # primary is like "#buttonForm\:addR" — strip leading # and unescape \:
    raw_id = selector_entry.primary.lstrip('#').replace('\\:', ':')
    css_id = raw_id.replace(':', '\\\\:')

    logger.debug("Submitting axis button for %s (id: %s)", axis.value, raw_id)

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
    # Wait for the page to settle after form submission — the JSF action
    # may trigger a page reload which destroys the execution context
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        page.wait_for_timeout(5000)


def add_variable(page: Page, variable_name: str, axis: Axis, knowledge=None) -> None:
    """Search for a variable, select all its categories, and add to the given axis."""
    logger.info("Adding variable '%s' to %s", variable_name, axis.value)
    search_variable(page, variable_name, knowledge)

    # Expand all collapsed groups to reveal variables and their categories
    _expand_all_collapsed(page)
    page.wait_for_timeout(500)

    # Validate the variable exists in the tree before checking categories
    var_node = _find_variable_node(page, variable_name)
    if not var_node:
        logger.error("Variable '%s' not found in tree after search", variable_name)

    # Check only the target variable's category checkboxes
    checked = _check_variable_categories(page, variable_name)
    if checked == 0:
        raise TableBuildError(
            f"No categories found for variable '{variable_name}'."
        )

    logger.debug("Checked %d categories for '%s'", checked, variable_name)
    page.wait_for_timeout(300)

    # Submit the axis button via form submission
    _submit_axis_button(page, axis)

    # Verify the table is no longer empty
    try:
        page_text = page.evaluate("() => document.body.innerText.substring(0, 500)")
        if "Your table is empty" in page_text:
            raise TableBuildError(
                f"Failed to add '{variable_name}' to {axis.value}. "
                "Table is still empty after submission."
            )
    except Exception as e:
        if "context" in str(e).lower() or "destroyed" in str(e).lower():
            # Page navigated during form submit — wait and retry check
            page.wait_for_timeout(3000)
            try:
                page_text = page.evaluate("() => document.body.innerText.substring(0, 500)")
                if "Your table is empty" in page_text:
                    raise TableBuildError(
                        f"Failed to add '{variable_name}' to {axis.value}. "
                        "Table is still empty after submission."
                    )
            except Exception:
                logger.warning("Could not verify table state after adding '%s'", variable_name)
        else:
            raise

    logger.info("Variable '%s' added to %s", variable_name, axis.value)


def _find_geography_group(page):
    """Find and expand the 'Geographical Areas...' top-level group.

    Returns the matched label element after expansion.
    Raises TableBuildError if no geography group found.
    """
    labels = page.query_selector_all('.treeNodeElement .label')
    geo_label = None
    for lbl in labels:
        text = (lbl.text_content() or '').strip()
        if text.startswith("Geographical Areas"):
            geo_label = lbl
            break

    if not geo_label:
        raise TableBuildError(
            "No geography group found. This dataset may not support geography selection."
        )

    # Expand the geography group if collapsed
    node = geo_label.evaluate_handle('el => el.closest(".treeNodeElement")')
    expander = node.as_element().query_selector('.treeNodeExpander')
    if expander and 'collapsed' in (expander.get_attribute('class') or ''):
        expander.click()
        page.wait_for_timeout(3000)

    logger.debug("Geography group expanded")
    return geo_label


def _find_geography_level(page, level_name):
    """Find and click a geography level label (e.g., 'Remoteness Areas').

    Fuzzy-matches: the level label must contain level_name as a substring.
    Returns the matched label element.
    Raises TableBuildError if not found, listing available levels.
    """
    labels = page.query_selector_all('.treeNodeElement .label')
    available_levels = []
    matched_label = None

    for lbl in labels:
        text = (lbl.text_content() or '').strip()
        if text.startswith("Geographical Areas"):
            continue
        # Geography levels are children of the geo group with suffixes like "(UR)" or "(POE)"
        if '(' in text and text.endswith(')'):
            available_levels.append(text)
            if level_name.lower() in text.lower() and matched_label is None:
                matched_label = lbl

    if not matched_label:
        level_list = "\n".join(f"  - {l}" for l in available_levels)
        raise TableBuildError(
            f"Geography level '{level_name}' not found. "
            f"Available levels:\n{level_list}"
        )

    # Click the level to populate state nodes
    matched_label.click()
    page.wait_for_timeout(5000)
    logger.debug("Geography level '%s' selected", level_name)
    return matched_label


def _find_and_check_states(page, geo_filter=None):
    """Expand state nodes and check their leaf category checkboxes.

    If geo_filter is set, only expand and check that state.
    Otherwise, expand all states and check all categories.
    Returns total number of checked checkboxes.
    Raises TableBuildError if geo_filter state not found or zero checked.
    """
    nodes = page.query_selector_all('.treeNodeElement')
    all_nodes = list(nodes)

    # Find state nodes: non-leaf nodes with checkboxes
    state_nodes = []
    for node in all_nodes:
        label_el = node.query_selector('.label')
        expander = node.query_selector('.treeNodeExpander')
        cb = node.query_selector('input[type=checkbox]')
        if not label_el or not expander or not cb:
            continue
        if 'leaf' in (expander.get_attribute('class') or ''):
            continue
        label_text = (label_el.text_content() or '').strip()
        if label_text:
            state_nodes.append((label_text, node, expander))

    if geo_filter:
        # Find the matching state
        matched = None
        for label_text, node, expander in state_nodes:
            if geo_filter.lower() in label_text.lower():
                matched = (label_text, node, expander)
                break
        if not matched:
            state_list = "\n".join(f"  - {s[0]}" for s in state_nodes)
            raise TableBuildError(
                f"Geography state/region '{geo_filter}' not found. "
                f"Available:\n{state_list}"
            )
        states_to_expand = [matched]
    else:
        states_to_expand = state_nodes

    total_checked = 0
    for label_text, node, expander in states_to_expand:
        if 'collapsed' in (expander.get_attribute('class') or ''):
            expander.click()
            page.wait_for_timeout(2000)
        logger.debug("Expanded state: %s", label_text)

    # Re-query after expansion to get updated DOM
    nodes = page.query_selector_all('.treeNodeElement')
    for node in nodes:
        expander = node.query_selector('.treeNodeExpander')
        if not expander or 'leaf' not in (expander.get_attribute('class') or ''):
            continue
        cb = node.query_selector('input[type=checkbox]')
        if cb and not cb.is_checked():
            cb.click()
            page.wait_for_timeout(200)
        if cb:
            total_checked += 1

    if total_checked == 0:
        raise TableBuildError("No geography categories found to check.")

    logger.debug("Checked %d geography categories", total_checked)
    return total_checked


def select_geography(page, geography, geo_filter=None, knowledge=None):
    """Select a Census geography level and check its categories.

    Expands the 'Geographical Areas' group, clicks the geography level,
    optionally filters to a state, checks leaf checkboxes, and submits
    to the row axis.
    """
    logger.info(
        "Selecting geography '%s'%s",
        geography,
        f" filtered to '{geo_filter}'" if geo_filter else "",
    )

    _find_geography_group(page)
    _find_geography_level(page, geography)
    checked = _find_and_check_states(page, geo_filter)

    # Submit to rows
    _submit_axis_button(page, Axis.ROW)

    logger.info("Geography added to rows (%d categories)", checked)


def build_table(page: Page, request: TableRequest, knowledge=None) -> None:
    """Add all variables from a TableRequest to their respective axes."""
    logger.info("Building table for dataset '%s'", request.dataset)

    if request.geography:
        select_geography(page, request.geography, request.geo_filter, knowledge)

    for var in request.rows:
        add_variable(page, var, Axis.ROW, knowledge)

    for var in request.cols:
        add_variable(page, var, Axis.COL, knowledge)

    for var in request.wafers:
        add_variable(page, var, Axis.WAFER, knowledge)

    logger.info("Table build complete")
