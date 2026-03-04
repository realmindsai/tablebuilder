# ABOUTME: Extracts the full variable tree from an ABS TableBuilder dataset page.
# ABOUTME: Parses tree nodes into DatasetTree with geography, groups, variables, and categories.

import json
import time
from pathlib import Path

from playwright.sync_api import Page

from tablebuilder.logging_config import get_logger
from tablebuilder.models import CategoryInfo, DatasetTree, VariableGroup, VariableInfo
from tablebuilder.navigator import (
    list_datasets,
    navigate_back_to_catalogue,
    open_dataset,
)

logger = get_logger("tablebuilder.tree_extractor")

# JavaScript snippet that walks all .treeNodeElement nodes inside the
# schema tree panel and extracts label text, leaf status, checkbox presence,
# and depth from UL/LI nesting (not CSS padding).
_EXTRACT_TREE_JS = """
() => {
    // Only look in the variable schema tree, not the saved tables tree
    const container = document.querySelector('#tableViewSchemaTree')
                    || document.querySelector('.treeControl');
    if (!container) return [];

    const nodes = container.querySelectorAll('.treeNodeElement');
    return Array.from(nodes).map(node => {
        const label = node.querySelector('.label');
        const expander = node.querySelector('.treeNodeExpander');
        const checkbox = node.querySelector('input[type=checkbox]');

        // Count ancestor UL elements to determine depth
        let depth = 0;
        let el = node.parentElement;
        while (el && el !== container) {
            if (el.tagName === 'UL') depth++;
            el = el.parentElement;
        }

        return {
            label: label ? label.textContent.trim() : '',
            is_leaf: expander ? expander.classList.contains('leaf') : true,
            has_checkbox: !!checkbox,
            depth: depth
        };
    });
}
"""


_MAX_EXPAND_SECONDS = 120
_MAX_EXPAND_ROUNDS = 100


def _expand_tree_bounded(page: Page) -> None:
    """Expand all collapsed tree nodes in the schema tree with a time limit.

    Only expands nodes inside #tableViewSchemaTree to avoid touching
    the saved tables tree. Uses a time limit to prevent infinite loops.
    """
    start = time.time()
    rounds = 0
    selector = '#tableViewSchemaTree .treeNodeExpander.collapsed'
    while rounds < _MAX_EXPAND_ROUNDS:
        if time.time() - start > _MAX_EXPAND_SECONDS:
            logger.warning("Tree expansion timed out after %ds", _MAX_EXPAND_SECONDS)
            break
        collapsed = page.query_selector_all(selector)
        if not collapsed:
            break
        rounds += 1
        logger.debug("Expand round %d: %d collapsed nodes", rounds, len(collapsed))
        for expander in collapsed:
            try:
                expander.click()
                page.wait_for_timeout(300)
            except Exception:
                continue
        # Brief pause between rounds for DOM updates
        page.wait_for_timeout(500)
    logger.debug("Expansion done after %d rounds (%.1fs)", rounds, time.time() - start)


def _extract_tree_with_depths(page: Page) -> list[dict]:
    """Use page.evaluate() to extract all tree node data from the DOM.

    Returns a list of dicts with keys: label, is_leaf, has_checkbox, depth.
    Depth is calculated from UL nesting in the DOM.
    """
    return page.evaluate(_EXTRACT_TREE_JS)


def _indent_to_depth(nodes: list[dict]) -> list[dict]:
    """Map pixel indent values to integer depth levels.

    Finds all unique indent values, sorts them, and assigns each an ordinal
    depth (0, 1, 2, ...). Adds a 'depth' key to each node dict.
    """
    if not nodes:
        return []

    unique_indents = sorted(set(n["indent_px"] for n in nodes))
    indent_map = {px: idx for idx, px in enumerate(unique_indents)}

    result = []
    for node in nodes:
        enriched = dict(node)
        enriched["depth"] = indent_map[node["indent_px"]]
        result.append(enriched)
    return result


def _parse_variable_label(label: str) -> tuple[str, str]:
    """Split a variable label like 'SEXP Sex' into (code, name).

    The first word is treated as a variable code only if it is ALL-CAPS
    and at most 10 characters long. Otherwise, the entire label is the name
    and the code is empty.
    """
    parts = label.split(None, 1)
    if len(parts) >= 2:
        candidate = parts[0]
        if candidate.isupper() and len(candidate) <= 10:
            return candidate, parts[1]
    return "", label


def _split_geography_and_variables(
    nodes: list[dict],
) -> tuple[list[str], list[dict]]:
    """Separate geography nodes from variable nodes.

    Geography nodes are the initial sequence of leaf nodes that have no
    checkbox. Once a node with has_checkbox=True is encountered, everything
    from its top-level parent group onward is considered variables.

    Returns (geography_names, variable_nodes).
    """
    if not nodes:
        return [], []

    min_depth = min(n["depth"] for n in nodes)

    # Find the index of the first node with has_checkbox=True
    first_checkbox_idx = None
    for i, node in enumerate(nodes):
        if node["has_checkbox"]:
            first_checkbox_idx = i
            break

    if first_checkbox_idx is None:
        # No checkboxes at all — all leaf nodes are geography
        geos = [n["label"] for n in nodes if n["is_leaf"]]
        return geos, []

    # Walk backwards from the first checkbox node to find its top-level parent
    var_start_idx = first_checkbox_idx
    for i in range(first_checkbox_idx - 1, -1, -1):
        if nodes[i]["depth"] == min_depth:
            var_start_idx = i
            break

    # Geography = leaf nodes before the variable section
    geos = [
        n["label"]
        for n in nodes[:var_start_idx]
        if n["is_leaf"]
    ]
    return geos, nodes[var_start_idx:]


def _classify_nodes(nodes: list[dict]) -> list[dict]:
    """Classify each node as 'group', 'variable', or 'category'.

    A variable is a non-leaf node whose immediate children (same depth+1,
    before the next node at the same or lesser depth) include at least one
    leaf node. A category is a leaf node. Everything else is a group.
    """
    for i, node in enumerate(nodes):
        if node["is_leaf"]:
            node["role"] = "category"
            continue

        # Non-leaf: check if this node has leaf children at depth+1
        has_leaf_child = False
        for j in range(i + 1, len(nodes)):
            if nodes[j]["depth"] <= node["depth"]:
                break
            if nodes[j]["depth"] == node["depth"] + 1 and nodes[j]["is_leaf"]:
                has_leaf_child = True
                break

        node["role"] = "variable" if has_leaf_child else "group"

    return nodes


def _parse_variable_tree(nodes: list[dict]) -> list[VariableGroup]:
    """Parse flat depth-annotated nodes into a VariableGroup hierarchy.

    Classifies each node as group/variable/category based on its children,
    NOT based on a fixed depth level. This handles trees with varying branch
    depths (e.g., "Sex" is shallow, "Country of birth" is deep).
    """
    if not nodes:
        return []

    nodes = _classify_nodes(nodes)
    min_depth = min(n["depth"] for n in nodes)

    logger.debug(
        "Tree depth range: %d-%d",
        min_depth,
        max(n["depth"] for n in nodes),
    )

    groups: list[VariableGroup] = []
    # Track group labels at each depth level for building group paths
    group_stack: dict[int, str] = {}
    current_group: VariableGroup | None = None
    current_variable: VariableInfo | None = None
    last_group_path = ""

    for node in nodes:
        depth = node["depth"]
        label = node["label"]
        role = node["role"]

        if role == "group":
            # Update group stack and clear deeper entries
            group_stack[depth] = label
            group_stack = {d: v for d, v in group_stack.items() if d <= depth}

            # Build group path from stack
            group_path = " > ".join(
                group_stack[d] for d in sorted(group_stack)
            )

            # Only create a new VariableGroup if path changed
            if group_path != last_group_path:
                if current_variable and current_group:
                    current_group.variables.append(current_variable)
                    current_variable = None
                if current_group is not None and current_group.variables:
                    groups.append(current_group)
                current_group = VariableGroup(label=group_path)
                last_group_path = group_path

        elif role == "variable":
            # Flush previous variable
            if current_variable and current_group:
                current_group.variables.append(current_variable)

            if current_group is None:
                current_group = VariableGroup(label="(ungrouped)")
                last_group_path = "(ungrouped)"

            code, name = _parse_variable_label(label)
            current_variable = VariableInfo(code=code, label=name)

        elif role == "category":
            if current_variable is not None:
                current_variable.categories.append(CategoryInfo(label=label))

    # Flush final variable and group
    if current_variable and current_group:
        current_group.variables.append(current_variable)
    if current_group is not None and current_group.variables:
        groups.append(current_group)

    return groups


def extract_dataset_tree(
    page: Page, dataset_name: str, knowledge=None
) -> DatasetTree:
    """Extract the full variable tree for an already-opened dataset.

    Assumes the page is on Table View for the given dataset. Expands all
    collapsed tree nodes, extracts DOM data, and parses into a DatasetTree.
    """
    logger.info("Extracting tree for dataset '%s'", dataset_name)

    # Wait for the variable tree panel to load in Table View
    page.wait_for_timeout(3000)

    # Debug: count tree elements before expansion
    pre_count = page.evaluate(
        "() => document.querySelectorAll('.treeNodeElement').length"
    )
    logger.debug("Tree nodes before expansion: %d", pre_count)

    if pre_count == 0:
        # Try waiting longer — the tree panel may load asynchronously
        logger.debug("No tree nodes yet, waiting for tree panel to load...")
        try:
            page.wait_for_selector(
                '#tableViewSchemaTree .treeNodeElement', timeout=10000
            )
        except Exception:
            logger.warning("No tree nodes found for dataset '%s'", dataset_name)

    _expand_tree_bounded(page)

    nodes = _extract_tree_with_depths(page)
    logger.debug("Extracted %d raw tree nodes", len(nodes))
    if nodes:
        depths = set(n['depth'] for n in nodes)
        logger.debug("Depth levels found: %s", sorted(depths))

    geos, var_nodes = _split_geography_and_variables(nodes)
    groups = _parse_variable_tree(var_nodes)

    tree = DatasetTree(
        dataset_name=dataset_name,
        geographies=geos,
        groups=groups,
    )
    logger.info(
        "Extracted %d groups, %d geographies for '%s'",
        len(groups),
        len(geos),
        dataset_name,
    )
    return tree


# --- Cache and progress helpers for batch extraction ---

DEFAULT_CACHE_DIR = Path.home() / ".tablebuilder" / "dict_cache"
DEFAULT_PROGRESS_PATH = Path.home() / ".tablebuilder" / "dictionary_progress.json"


def _tree_to_dict(tree: DatasetTree) -> dict:
    """Serialize a DatasetTree to a plain dict for JSON storage."""
    return {
        "dataset_name": tree.dataset_name,
        "geographies": tree.geographies,
        "groups": [
            {
                "label": g.label,
                "variables": [
                    {
                        "code": v.code,
                        "label": v.label,
                        "categories": [{"label": c.label} for c in v.categories],
                    }
                    for v in g.variables
                ],
            }
            for g in tree.groups
        ],
    }


def _dict_to_tree(data: dict) -> DatasetTree:
    """Deserialize a plain dict back into a DatasetTree."""
    return DatasetTree(
        dataset_name=data["dataset_name"],
        geographies=data.get("geographies", []),
        groups=[
            VariableGroup(
                label=g["label"],
                variables=[
                    VariableInfo(
                        code=v["code"],
                        label=v["label"],
                        categories=[
                            CategoryInfo(label=c["label"])
                            for c in v.get("categories", [])
                        ],
                    )
                    for v in g.get("variables", [])
                ],
            )
            for g in data.get("groups", [])
        ],
    )


def _save_tree_cache(tree: DatasetTree, cache_dir: Path) -> None:
    """Save a DatasetTree as a JSON file in the cache directory."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Sanitize dataset name for use as a filename
    safe_name = tree.dataset_name.replace(" ", "_").replace("/", "_")
    path = cache_dir / f"{safe_name}.json"
    path.write_text(json.dumps(_tree_to_dict(tree), indent=2))
    logger.debug("Cached tree for '%s' at %s", tree.dataset_name, path)


def _load_cached_trees(cache_dir: Path) -> list[DatasetTree]:
    """Load all cached DatasetTree JSON files from the cache directory."""
    if not cache_dir.exists():
        return []
    trees = []
    for path in sorted(cache_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            trees.append(_dict_to_tree(data))
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Skipping corrupt cache file %s: %s", path, exc)
    return trees


def _save_progress(progress: dict, progress_path: Path) -> None:
    """Save batch extraction progress to a JSON file."""
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps(progress, indent=2))


def _load_progress(progress_path: Path) -> dict:
    """Load batch extraction progress, returning a default dict if missing."""
    if not progress_path.exists():
        return {"completed": [], "failed": {}, "total": 0}
    try:
        return json.loads(progress_path.read_text())
    except (json.JSONDecodeError, KeyError):
        return {"completed": [], "failed": {}, "total": 0}


DICT_CACHE_DIR = DEFAULT_CACHE_DIR


def extract_all_datasets(
    page: Page,
    datasets: list[str] | None = None,
    exclude_census: bool = True,
    resume: bool = True,
    knowledge=None,
) -> list[DatasetTree]:
    """Extract variable trees for multiple datasets with crash recovery.

    For each dataset: open it, extract its tree, cache it, then navigate
    back to the catalogue. On error per dataset, log a warning and continue.

    Args:
        page: A logged-in Playwright page on the dataset catalogue.
        datasets: Explicit list of dataset names. If None, auto-discovers via list_datasets.
        exclude_census: When auto-discovering, skip datasets with 'Census' in the name.
        resume: When True, skip datasets already completed in previous runs.
        knowledge: Optional KnowledgeBase for self-healing selectors.

    Returns:
        List of successfully extracted DatasetTree objects (including cached ones).
    """
    cache_dir = DEFAULT_CACHE_DIR
    progress_path = DEFAULT_PROGRESS_PATH

    # Discover datasets if not provided
    if datasets is None:
        all_datasets = list_datasets(page, knowledge)
        if exclude_census:
            all_datasets = [d for d in all_datasets if "Census" not in d]
        datasets = all_datasets

    # Load progress for resume support
    progress = _load_progress(progress_path) if resume else {"completed": [], "failed": {}, "total": 0}
    progress["total"] = len(datasets)

    trees: list[DatasetTree] = []

    for name in datasets:
        if resume and name in progress["completed"]:
            logger.info("Skipping already completed dataset '%s'", name)
            continue

        logger.info("Processing dataset '%s'", name)
        try:
            open_dataset(page, name, knowledge)
            tree = extract_dataset_tree(page, name, knowledge)
            _save_tree_cache(tree, cache_dir)
            trees.append(tree)
            progress["completed"].append(name)
            _save_progress(progress, progress_path)
            logger.info("Successfully extracted '%s'", name)
        except Exception as exc:
            logger.warning("Failed to extract '%s': %s", name, exc)
            progress["failed"][name] = str(exc)
            _save_progress(progress, progress_path)

        # Navigate back to catalogue for the next dataset
        try:
            navigate_back_to_catalogue(page)
        except Exception as exc:
            logger.warning("Failed to navigate back to catalogue: %s", exc)

    _save_progress(progress, progress_path)

    # Load all cached trees (includes this run + previous runs)
    all_trees = _load_cached_trees(cache_dir)
    return all_trees
