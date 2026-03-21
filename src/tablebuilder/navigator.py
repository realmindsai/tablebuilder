# ABOUTME: Navigate datasets and variables in the TableBuilder UI.
# ABOUTME: Fuzzy-matches dataset names and opens them in Table View.

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from tablebuilder.logging_config import get_logger
from tablebuilder.resilience import find_element, find_all_elements, retry
from tablebuilder.selectors import (
    TREE_NODE,
    TREE_LABEL,
    TREE_EXPANDER_COLLAPSED,
    SEARCH_INPUT,
    SEARCH_BUTTON,
)

logger = get_logger("tablebuilder.navigator")


class NavigationError(Exception):
    """Raised when navigation in TableBuilder fails."""


class SessionExpiredError(NavigationError):
    """Raised when the ABS session appears to have expired."""


def fuzzy_match_dataset(query: str, available: list[str]) -> str:
    """Find the best matching dataset name from available options.

    Tries exact match first, then case-insensitive, then word-level substring,
    then word-level with punctuation stripped, then with years dropped.
    """
    import re

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

    # Word match with punctuation stripped — handles commas, periods, etc.
    query_tokens = re.findall(r'\w+', query_lower)
    for name in available:
        name_tokens_str = ' '.join(re.findall(r'\w+', name.lower()))
        if all(token in name_tokens_str for token in query_tokens):
            return name

    # Year-tolerant match — drop 4-digit years from query, match remaining words,
    # then pick the best match among candidates
    non_year_tokens = [t for t in query_tokens if not re.match(r'^\d{4}$', t)]
    if non_year_tokens and len(non_year_tokens) < len(query_tokens):
        candidates = []
        for name in available:
            name_tokens_str = ' '.join(re.findall(r'\w+', name.lower()))
            if all(token in name_tokens_str for token in non_year_tokens):
                candidates.append(name)
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            # Pick the candidate whose year is closest to the query year
            query_years = [int(t) for t in query_tokens if re.match(r'^\d{4}$', t)]
            if query_years:
                target_year = max(query_years)
                def year_distance(name):
                    name_years = [int(y) for y in re.findall(r'\d{4}', name)]
                    if not name_years:
                        return 9999
                    return min(abs(y - target_year) for y in name_years)
                candidates.sort(key=year_distance)
            return candidates[0]

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
    labels = find_all_elements(page, TREE_LABEL)
    for lbl in labels:
        if label_text in (lbl.text_content() or ''):
            node = lbl.evaluate_handle('el => el.closest(".treeNodeElement")')
            exp = node.as_element().query_selector('.treeNodeExpander')
            if exp and 'collapsed' in (exp.get_attribute('class') or ''):
                exp.click()
                page.wait_for_timeout(2000)
                return True
    return False


def _expand_all_collapsed(page: Page, max_rounds: int = 50) -> None:
    """Keep expanding collapsed tree nodes until none remain.

    Stops when no collapsed nodes are found, when no progress is made
    (same count after a full iteration), or after max_rounds iterations.
    """
    prev_count = -1
    stale_rounds = 0
    for _round in range(max_rounds):
        collapsed = find_all_elements(page, TREE_EXPANDER_COLLAPSED)
        if not collapsed:
            break
        # Detect stale loops where the same elements remain unexpandable
        if len(collapsed) == prev_count:
            stale_rounds += 1
            if stale_rounds >= 1:
                logger.warning(
                    "Stopping expansion: %d collapsed elements remain "
                    "after %d rounds with no progress (likely non-tree elements)",
                    len(collapsed), _round + 1,
                )
                break
        else:
            stale_rounds = 0
        prev_count = len(collapsed)
        for expander in collapsed:
            try:
                expander.click()
                page.wait_for_timeout(1000)
            except Exception:
                continue


def list_datasets(page: Page, knowledge=None) -> list[str]:
    """Read available dataset names from the TableBuilder home page."""
    logger.info("Listing available datasets")
    # Expand all collapsed tree nodes to reveal the full hierarchy
    _expand_all_collapsed(page)

    # Collect leaf dataset names — only nodes whose expander has the .leaf class
    names = []
    nodes = find_all_elements(page, TREE_NODE, knowledge)
    for node in nodes:
        expander = node.query_selector('.treeNodeExpander')
        if expander and 'leaf' in (expander.get_attribute('class') or ''):
            label = node.query_selector('.label')
            if label:
                text = (label.text_content() or '').strip()
                if text:
                    names.append(text)

    logger.debug("Found %d datasets", len(names))
    return names


@retry(max_attempts=2, retryable_exceptions=(PlaywrightTimeout,))
def open_dataset(page: Page, dataset_query: str, knowledge=None) -> None:
    """Find and open a dataset in TableBuilder, reaching Table View."""
    logger.info("Opening dataset matching '%s'", dataset_query)
    available = list_datasets(page, knowledge)
    if not available:
        raise SessionExpiredError(
            "Session expired -- catalogue returned 0 datasets"
        )
    matched_name = fuzzy_match_dataset(dataset_query, available)
    logger.debug("Fuzzy matched to '%s'", matched_name)

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

    logger.info("Dataset '%s' opened in Table View", matched_name)


def search_variable(page: Page, variable_name: str, knowledge=None) -> None:
    """Use the dataset search box to find and highlight a variable."""
    logger.debug("Searching for variable '%s'", variable_name)
    search_input = find_element(page, SEARCH_INPUT, knowledge)
    if not search_input:
        raise NavigationError("Cannot find the search box in the dataset panel.")

    search_input.fill("")
    search_input.fill(variable_name)

    search_button = find_element(page, SEARCH_BUTTON, knowledge)
    if search_button:
        search_button.click()
    else:
        page.keyboard.press("Enter")

    page.wait_for_timeout(1000)
    logger.debug("Variable search for '%s' submitted", variable_name)


DATA_CATALOGUE_URL = (
    "https://tablebuilder.abs.gov.au/webapi/jsf/dataCatalogueExplorer.xhtml"
)


def navigate_back_to_catalogue(page: Page) -> None:
    """Navigate from Table View back to the dataset catalogue.

    Uses direct URL navigation rather than clicking the Back button,
    which is more reliable across different UI states.
    """
    logger.debug("Navigating back to dataset catalogue")
    page.goto(DATA_CATALOGUE_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)
    logger.debug("Arrived at dataset catalogue")
