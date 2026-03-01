# ABOUTME: Navigate datasets and variables in the TableBuilder UI.
# ABOUTME: Fuzzy-matches dataset names and opens them in Table View.

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


class NavigationError(Exception):
    """Raised when navigation in TableBuilder fails."""


def fuzzy_match_dataset(query: str, available: list[str]) -> str:
    """Find the best matching dataset name from available options.

    Tries exact match first, then case-insensitive, then substring.
    """
    query_lower = query.lower()

    # Exact match
    for name in available:
        if name == query:
            return name

    # Case-insensitive exact match
    for name in available:
        if name.lower() == query_lower:
            return name

    # Substring match — all query words must appear in the dataset name
    query_words = query_lower.split()
    for name in available:
        name_lower = name.lower()
        if all(word in name_lower for word in query_words):
            return name

    raise NavigationError(
        f"No dataset matching '{query}'. Available datasets:\n"
        + "\n".join(f"  - {name}" for name in available)
    )


def _expand_node(page: Page, label_text: str) -> bool:
    """Expand a collapsed tree node by its label text.

    Finds a .label element containing label_text, walks up to its
    .treeNodeElement parent, and clicks the .treeNodeExpander if collapsed.
    Returns True if a node was expanded, False otherwise.
    """
    labels = page.query_selector_all('.label')
    for lbl in labels:
        if label_text in (lbl.text_content() or ''):
            node = lbl.evaluate_handle('el => el.closest(".treeNodeElement")')
            exp = node.as_element().query_selector('.treeNodeExpander')
            if exp and 'collapsed' in (exp.get_attribute('class') or ''):
                exp.click()
                page.wait_for_timeout(2000)
                return True
    return False


def _expand_all_collapsed(page: Page) -> None:
    """Keep expanding collapsed tree nodes until none remain."""
    while True:
        collapsed = page.query_selector_all('.treeNodeExpander.collapsed')
        if not collapsed:
            break
        for expander in collapsed:
            try:
                expander.click()
                page.wait_for_timeout(1000)
            except Exception:
                continue


def list_datasets(page: Page) -> list[str]:
    """Read available dataset names from the TableBuilder home page."""
    # Expand all collapsed tree nodes to reveal the full hierarchy
    _expand_all_collapsed(page)

    # Collect leaf dataset names — only nodes whose expander has the .leaf class
    names = []
    nodes = page.query_selector_all('.treeNodeElement')
    for node in nodes:
        expander = node.query_selector('.treeNodeExpander')
        if expander and 'leaf' in (expander.get_attribute('class') or ''):
            label = node.query_selector('.label')
            if label:
                text = (label.text_content() or '').strip()
                if text:
                    names.append(text)

    return names


def open_dataset(page: Page, dataset_query: str) -> None:
    """Find and open a dataset in TableBuilder, reaching Table View."""
    available = list_datasets(page)
    matched_name = fuzzy_match_dataset(dataset_query, available)

    # Expand parent folders that may be collapsed, then double-click the leaf
    # Walk through tree labels to find the matched dataset
    labels = page.query_selector_all('.treeNodeElement .label')
    target_label = None
    for lbl in labels:
        if (lbl.text_content() or '').strip() == matched_name:
            target_label = lbl
            break

    if not target_label:
        raise NavigationError(f"Found '{matched_name}' but cannot locate it in the UI.")

    # Double-click the leaf dataset label to open Table View
    target_label.dblclick()

    # Wait for Table View to load (URL changes to tableView.xhtml)
    try:
        page.wait_for_url("**/tableView.xhtml*", timeout=15000)
    except PlaywrightTimeout:
        raise NavigationError(
            f"Opened '{matched_name}' but Table View did not load. "
            "The dataset may be unavailable."
        )


def search_variable(page: Page, variable_name: str) -> None:
    """Use the dataset search box to find and highlight a variable."""
    search_input = page.query_selector('#searchPattern')
    if not search_input:
        raise NavigationError("Cannot find the search box in the dataset panel.")

    search_input.fill("")
    search_input.fill(variable_name)

    search_button = page.query_selector('#searchButton')
    if search_button:
        search_button.click()
    else:
        page.keyboard.press("Enter")

    page.wait_for_timeout(1000)
