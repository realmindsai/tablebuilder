# ABOUTME: Parse the Census 2021 markdown data dictionary into dict_cache JSON files.
# ABOUTME: Converts structured markdown into the same format used by tree_extractor.py.

import json
import re
from pathlib import Path

MARKDOWN_PATH = Path(__file__).parent.parent / "docs" / "census_2021_data_dictionary.md"
CACHE_DIR = Path.home() / ".tablebuilder" / "dict_cache"


def parse_census_markdown(md_text: str) -> list[dict]:
    """Parse the Census 2021 markdown into a list of dataset dicts."""
    datasets = []
    current_dataset = None
    current_geographies = []
    current_group = None
    current_variable = None
    in_geographies = False
    in_variables = False
    in_cross_reference = False

    for line in md_text.splitlines():
        line = line.rstrip()

        # Skip cross-reference section at the end
        if line.startswith("## Variable Cross-Reference"):
            in_cross_reference = True
            # Flush last dataset
            if current_dataset:
                _flush_variable(current_dataset, current_group, current_variable)
                current_variable = None
                _flush_group(current_dataset, current_group)
                current_group = None
                datasets.append(current_dataset)
                current_dataset = None
            continue
        if in_cross_reference:
            continue

        # New dataset (## heading)
        if line.startswith("## ") and not line.startswith("###"):
            # Flush previous dataset
            if current_dataset:
                _flush_variable(current_dataset, current_group, current_variable)
                current_variable = None
                _flush_group(current_dataset, current_group)
                current_group = None
                datasets.append(current_dataset)

            dataset_name = "2021 Census - " + line[3:].strip()
            current_dataset = {
                "dataset_name": dataset_name,
                "geographies": [],
                "groups": [],
            }
            current_geographies = []
            current_group = None
            current_variable = None
            in_geographies = False
            in_variables = False
            continue

        if not current_dataset:
            continue

        # Geography section
        if line.startswith("### Available Geographies"):
            in_geographies = True
            in_variables = False
            continue

        # Variables section
        if line.startswith("### Variables"):
            in_geographies = False
            in_variables = True
            continue

        # Geography list items
        if in_geographies and line.startswith("- "):
            geo = line[2:].strip()
            current_dataset["geographies"].append(geo)
            continue

        # Group heading (#### level)
        if in_variables and line.startswith("#### "):
            # Flush previous group
            _flush_variable(current_dataset, current_group, current_variable)
            current_variable = None
            _flush_group(current_dataset, current_group)

            group_label = line[5:].strip()
            current_group = {"label": group_label, "variables": []}
            continue

        # Variable line: - **CODE** Label
        if in_variables and line.startswith("- **"):
            # Flush previous variable
            _flush_variable(current_dataset, current_group, current_variable)

            match = re.match(r"- \*\*(\w+)\*\*\s+(.*)", line)
            if match:
                code = match.group(1)
                label = match.group(2)
                current_variable = {
                    "code": code,
                    "label": label,
                    "categories": [],
                }
            continue

        # Categories line:   - Categories: ...
        if in_variables and current_variable and line.strip().startswith("- Categories:"):
            cats_text = line.strip()[len("- Categories:"):].strip()
            # Handle the "(N total)" suffix
            cats_text = re.sub(r"\s*\(\d+ total\)\s*$", "", cats_text)
            # Split on commas, but be careful of commas within category names
            # Categories are separated by ", " but some categories contain commas
            # Use a simple split since the format is consistent
            cats = [c.strip() for c in cats_text.split(", ") if c.strip()]
            current_variable["categories"] = [
                {"label": c} for c in cats
            ]
            continue

    # Flush last dataset
    if current_dataset:
        _flush_variable(current_dataset, current_group, current_variable)
        _flush_group(current_dataset, current_group)
        datasets.append(current_dataset)

    return datasets


def _flush_variable(dataset, group, variable):
    """Add variable to group if both exist."""
    if variable and group:
        group["variables"].append(variable)


def _flush_group(dataset, group):
    """Add group to dataset if it has variables."""
    if group and group["variables"] and dataset:
        dataset["groups"].append(group)


def main():
    md_text = MARKDOWN_PATH.read_text()
    datasets = parse_census_markdown(md_text)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for ds in datasets:
        safe_name = ds["dataset_name"].replace(" ", "_").replace("/", "_")
        path = CACHE_DIR / f"{safe_name}.json"
        path.write_text(json.dumps(ds, indent=2))

        n_groups = len(ds["groups"])
        n_vars = sum(len(g["variables"]) for g in ds["groups"])
        n_cats = sum(
            len(v["categories"])
            for g in ds["groups"]
            for v in g["variables"]
        )
        print(f"  {ds['dataset_name']}: {n_groups} groups, {n_vars} vars, {n_cats} cats")

    print(f"\nWrote {len(datasets)} Census datasets to {CACHE_DIR}")


if __name__ == "__main__":
    main()
