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


def list_datasets(page: Page) -> list[str]:
    """Read available dataset names from the TableBuilder home page."""
    # Expand all dataset folders by clicking triangles
    triangles = page.query_selector_all(
        ".tree-toggle, .ui-tree-toggler, [class*='toggle']"
    )
    for triangle in triangles:
        try:
            triangle.click()
            page.wait_for_timeout(500)
        except Exception:
            continue

    # Collect dataset names (leaf nodes with cube icons or dataset class)
    dataset_elements = page.query_selector_all(
        ".dataset-name, .cube-icon + span, [class*='dataset'] span"
    )
    names = []
    for el in dataset_elements:
        text = (el.text_content() or "").strip()
        if text:
            names.append(text)

    if not names:
        # Fallback: grab all tree node labels
        tree_nodes = page.query_selector_all(
            ".ui-treenode-label, .tree-label, [role='treeitem']"
        )
        for node in tree_nodes:
            text = (node.text_content() or "").strip()
            if text and len(text) > 3:
                names.append(text)

    return names


def open_dataset(page: Page, dataset_query: str) -> None:
    """Find and open a dataset in TableBuilder, reaching Table View."""
    available = list_datasets(page)
    matched_name = fuzzy_match_dataset(dataset_query, available)

    # Double-click the matched dataset to open it
    dataset_el = page.get_by_text(matched_name, exact=True).first
    if not dataset_el:
        raise NavigationError(f"Found '{matched_name}' but cannot locate it in the UI.")

    dataset_el.dblclick()

    # Wait for Table View to load
    try:
        page.wait_for_selector(
            "text=Add to Row, text=Add to Column",
            timeout=15000,
        )
    except PlaywrightTimeout:
        raise NavigationError(
            f"Opened '{matched_name}' but Table View did not load. "
            "The dataset may be unavailable."
        )


def search_variable(page: Page, variable_name: str) -> None:
    """Use the dataset search box to find and highlight a variable."""
    search_input = page.query_selector(
        "input[placeholder*='Search'], input[class*='search']"
    )
    if not search_input:
        raise NavigationError("Cannot find the search box in the dataset panel.")

    search_input.fill("")
    search_input.fill(variable_name)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1000)
