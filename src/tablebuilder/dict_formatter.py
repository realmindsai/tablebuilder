# ABOUTME: Pure-function markdown formatter for data dictionary output.
# ABOUTME: Converts DatasetTree objects into structured markdown documentation.

import re
from collections import defaultdict
from datetime import date

from tablebuilder.models import DatasetTree, VariableInfo

MAX_CATEGORIES_SHOWN = 8


def _slugify(name: str) -> str:
    """Convert a dataset name to a markdown anchor slug.

    Lowercase, spaces to hyphens, remove special characters except hyphens.
    Multiple spaces become multiple hyphens to match GitHub anchor behavior.
    """
    slug = name.lower()
    slug = slug.replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    return slug


def _format_variable(var: VariableInfo) -> str:
    """Format a single variable as a markdown list item with optional categories."""
    lines = []

    if var.code:
        lines.append(f"- **{var.code}** {var.label}")
    else:
        lines.append(f"- {var.label}")

    if var.categories:
        cat_labels = [c.label for c in var.categories]
        total = len(cat_labels)

        if total > MAX_CATEGORIES_SHOWN:
            shown = ", ".join(cat_labels[:MAX_CATEGORIES_SHOWN])
            lines.append(f"  - Categories: {shown}, ... ({total} total)")
        else:
            shown = ", ".join(cat_labels)
            lines.append(f"  - Categories: {shown}")

    return "\n".join(lines)


def format_dataset(tree: DatasetTree) -> str:
    """Format a single DatasetTree into a markdown section.

    Produces a ## heading with geographies and variable groups.
    """
    lines = []

    lines.append(f"## {tree.dataset_name}")
    lines.append("")
    lines.append("### Available Geographies")
    lines.append("")

    if tree.geographies:
        for geo in tree.geographies:
            lines.append(f"- {geo}")
    else:
        lines.append("- (none listed)")

    lines.append("")
    lines.append("### Variables")

    for group in tree.groups:
        lines.append("")
        lines.append(f"#### {group.label}")

        for var in group.variables:
            lines.append("")
            lines.append(_format_variable(var))

    lines.append("")
    return "\n".join(lines)


def _format_cross_reference(trees: list[DatasetTree]) -> str:
    """Build a cross-reference table of variables across datasets.

    Collects all variables, counts dataset occurrences, sorts by frequency
    descending then alphabetically by code.
    """
    # Map variable code -> (label, set of dataset names)
    var_info: dict[str, tuple[str, set[str]]] = {}

    for tree in trees:
        for group in tree.groups:
            for var in group.variables:
                if not var.code:
                    continue
                if var.code not in var_info:
                    var_info[var.code] = (var.label, set())
                var_info[var.code][1].add(tree.dataset_name)

    # Sort by count descending, then code ascending
    sorted_vars = sorted(
        var_info.items(),
        key=lambda item: (-len(item[1][1]), item[0]),
    )

    lines = []
    lines.append("## Variable Cross-Reference")
    lines.append("")
    lines.append("| Variable | Description | Datasets |")
    lines.append("|----------|-------------|----------|")

    for code, (label, datasets) in sorted_vars:
        count = len(datasets)
        lines.append(f"| {code} | {label} | {count} datasets |")

    lines.append("")
    return "\n".join(lines)


def format_data_dictionary(
    trees: list[DatasetTree],
    title: str = "ABS TableBuilder Data Dictionary",
) -> str:
    """Format a complete data dictionary document from multiple DatasetTrees.

    Produces a full markdown document with title, date, table of contents,
    dataset sections separated by dividers, and a cross-reference table.
    """
    today = date.today().isoformat()

    lines = []

    # Title and date
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"Extracted from ABS TableBuilder on {today}.")
    lines.append("")

    # Table of Contents
    lines.append("## Table of Contents")
    lines.append("")
    for i, tree in enumerate(trees, 1):
        slug = _slugify(tree.dataset_name)
        lines.append(f"{i}. [{tree.dataset_name}](#{slug})")
    # Include cross-reference in TOC
    lines.append(f"{len(trees) + 1}. [Variable Cross-Reference](#variable-cross-reference)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Dataset sections
    for tree in trees:
        lines.append(format_dataset(tree))
        lines.append("---")
        lines.append("")

    # Cross-reference table
    lines.append(_format_cross_reference(trees))

    return "\n".join(lines)
