# ABOUTME: Central registry of all CSS/JSF selectors for the ABS TableBuilder UI.
# ABOUTME: Each selector has a primary value and fallback strategies for self-healing.

from dataclasses import dataclass, field

from tablebuilder.models import Axis


@dataclass
class SelectorEntry:
    """A UI selector with fallback alternatives for resilient element location."""

    name: str  # Human-readable name
    primary: str  # Primary CSS selector
    fallbacks: list[str] = field(default_factory=list)  # Alternatives if primary fails
    description: str = ""  # What this element does


# ---------------------------------------------------------------------------
# Login selectors
# ---------------------------------------------------------------------------

LOGIN_USERNAME = SelectorEntry(
    name="LOGIN_USERNAME",
    primary="#loginForm\\:username2",
    fallbacks=['input[name*="username"]', 'input[type="text"]'],
    description="Username input on the login form",
)

LOGIN_PASSWORD = SelectorEntry(
    name="LOGIN_PASSWORD",
    primary="#loginForm\\:password2",
    fallbacks=['input[name*="password"]', 'input[type="password"]'],
    description="Password input on the login form",
)

LOGIN_BUTTON = SelectorEntry(
    name="LOGIN_BUTTON",
    primary="#loginForm\\:login2",
    fallbacks=['button:has-text("Login")', 'input[type="submit"]'],
    description="Login submit button",
)

TERMS_BUTTON = SelectorEntry(
    name="TERMS_BUTTON",
    primary="#termsForm\\:termsButton",
    fallbacks=['button:has-text("Accept")', 'button:has-text("I Agree")'],
    description="Accept terms and conditions button",
)

# ---------------------------------------------------------------------------
# Tree selectors
# ---------------------------------------------------------------------------

TREE_NODE = SelectorEntry(
    name="TREE_NODE",
    primary=".treeNodeElement",
    fallbacks=[".tree-node", '[role="treeitem"]'],
    description="A node element in the variable tree",
)

TREE_LABEL = SelectorEntry(
    name="TREE_LABEL",
    primary=".label",
    fallbacks=[".tree-label", ".node-label"],
    description="Label text inside a tree node",
)

TREE_EXPANDER = SelectorEntry(
    name="TREE_EXPANDER",
    primary=".treeNodeExpander",
    fallbacks=[".tree-expander", "[aria-expanded]"],
    description="Expand/collapse toggle on a tree node",
)

TREE_EXPANDER_COLLAPSED = SelectorEntry(
    name="TREE_EXPANDER_COLLAPSED",
    primary=".treeNodeExpander.collapsed",
    fallbacks=['[aria-expanded="false"]'],
    description="A collapsed tree node expander",
)

SEARCH_INPUT = SelectorEntry(
    name="SEARCH_INPUT",
    primary="#searchPattern",
    fallbacks=['input[placeholder*="search"]', 'input[type="search"]'],
    description="Search input for filtering variables",
)

SEARCH_BUTTON = SelectorEntry(
    name="SEARCH_BUTTON",
    primary="#searchButton",
    fallbacks=['button:has-text("Search")'],
    description="Button to trigger variable search",
)

CATEGORY_CHECKBOX = SelectorEntry(
    name="CATEGORY_CHECKBOX",
    primary="input[type=checkbox]",
    fallbacks=['[role="checkbox"]'],
    description="Checkbox for selecting a category value",
)

# ---------------------------------------------------------------------------
# Download selectors
# ---------------------------------------------------------------------------

FORMAT_DROPDOWN = SelectorEntry(
    name="FORMAT_DROPDOWN",
    primary="#downloadControl\\:downloadType",
    fallbacks=['select[name*="downloadType"]'],
    description="Dropdown to select download format (CSV, etc.)",
)

QUEUE_BUTTON = SelectorEntry(
    name="QUEUE_BUTTON",
    primary="#pageForm\\:retB",
    fallbacks=['button:has-text("Queue")'],
    description="Button to open the queue/download dialog",
)

QUEUE_DIALOG = SelectorEntry(
    name="QUEUE_DIALOG",
    primary="#downloadTableModePanel_container",
    fallbacks=['[role="dialog"]', ".modal"],
    description="Modal dialog for queuing a table download",
)

QUEUE_NAME_INPUT = SelectorEntry(
    name="QUEUE_NAME_INPUT",
    primary="#downloadTableModeForm\\:downloadTableNameTxt",
    fallbacks=['input[name*="TableName"]'],
    description="Input field for naming the queued table",
)

QUEUE_SUBMIT = SelectorEntry(
    name="QUEUE_SUBMIT",
    primary="#downloadTableModeForm\\:queueTableButton",
    fallbacks=['button:has-text("Queue")'],
    description="Submit button inside the queue dialog",
)

# ---------------------------------------------------------------------------
# Axis button selectors
# ---------------------------------------------------------------------------

AXIS_ROW_BUTTON = SelectorEntry(
    name="AXIS_ROW_BUTTON",
    primary="#buttonForm\\:addR",
    fallbacks=['button:has-text("Add to Row")', 'input[value*="Row"]'],
    description="Button to assign variable to the Row axis",
)

AXIS_COL_BUTTON = SelectorEntry(
    name="AXIS_COL_BUTTON",
    primary="#buttonForm\\:addC",
    fallbacks=['button:has-text("Add to Column")', 'input[value*="Column"]'],
    description="Button to assign variable to the Column axis",
)

AXIS_WAFER_BUTTON = SelectorEntry(
    name="AXIS_WAFER_BUTTON",
    primary="#buttonForm\\:addL",
    fallbacks=['button:has-text("Add to Wafer")', 'input[value*="Layer"]'],
    description="Button to assign variable to the Wafer (layer) axis",
)

# ---------------------------------------------------------------------------
# Axis mapping
# ---------------------------------------------------------------------------

AXIS_BUTTONS: dict[Axis, SelectorEntry] = {
    Axis.ROW: AXIS_ROW_BUTTON,
    Axis.COL: AXIS_COL_BUTTON,
    Axis.WAFER: AXIS_WAFER_BUTTON,
}

# ---------------------------------------------------------------------------
# Aggregate list of all selectors for iteration / validation
# ---------------------------------------------------------------------------

ALL_SELECTORS: list[SelectorEntry] = [
    LOGIN_USERNAME,
    LOGIN_PASSWORD,
    LOGIN_BUTTON,
    TERMS_BUTTON,
    TREE_NODE,
    TREE_LABEL,
    TREE_EXPANDER,
    TREE_EXPANDER_COLLAPSED,
    SEARCH_INPUT,
    SEARCH_BUTTON,
    CATEGORY_CHECKBOX,
    FORMAT_DROPDOWN,
    QUEUE_BUTTON,
    QUEUE_DIALOG,
    QUEUE_NAME_INPUT,
    QUEUE_SUBMIT,
    AXIS_ROW_BUTTON,
    AXIS_COL_BUTTON,
    AXIS_WAFER_BUTTON,
]
