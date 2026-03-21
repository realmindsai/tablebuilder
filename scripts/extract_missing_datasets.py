# ABOUTME: Extract the 25 previously-failed datasets from ABS TableBuilder.
# ABOUTME: Uses explicit dataset list and retries with better catalogue expansion.

import json
import time
from pathlib import Path

from tablebuilder.browser import TableBuilderSession
from tablebuilder.config import load_config
from tablebuilder.navigator import list_datasets, navigate_back_to_catalogue, open_dataset
from tablebuilder.tree_extractor import (
    DEFAULT_PROGRESS_PATH,
    _save_progress,
    _save_tree_cache,
    _load_progress,
    DEFAULT_CACHE_DIR,
    extract_dataset_tree,
)


def main():
    progress = _load_progress(DEFAULT_PROGRESS_PATH)
    failed_names = list(progress["failed"].keys())
    print(f"Retrying {len(failed_names)} failed datasets...")

    config = load_config()
    extracted = 0
    still_failed = {}

    with TableBuilderSession(config, headless=False) as page:
        print("Logged in to TableBuilder.")

        for i, name in enumerate(failed_names):
            print(f"\n[{i+1}/{len(failed_names)}] Processing: {name}")

            try:
                # Open the dataset - this handles catalogue listing + fuzzy match
                open_dataset(page, name)

                # Extract the tree
                tree = extract_dataset_tree(page, name)
                _save_tree_cache(tree, DEFAULT_CACHE_DIR)

                # Mark as completed
                progress["completed"].append(name)
                if name in progress["failed"]:
                    del progress["failed"][name]
                _save_progress(progress, DEFAULT_PROGRESS_PATH)

                n_groups = len(tree.groups)
                n_vars = sum(len(g.variables) for g in tree.groups)
                n_cats = sum(
                    len(v.categories) for g in tree.groups for v in g.variables
                )
                print(f"  OK: {n_groups} groups, {n_vars} variables, {n_cats} categories")
                extracted += 1

            except Exception as exc:
                print(f"  FAILED: {exc}")
                still_failed[name] = str(exc)
                progress["failed"][name] = str(exc)
                _save_progress(progress, DEFAULT_PROGRESS_PATH)

            # Navigate back to catalogue for the next dataset
            try:
                navigate_back_to_catalogue(page)
                # Wait a bit longer for tree to load fully
                time.sleep(3)
            except Exception as exc:
                print(f"  Warning: failed to navigate back: {exc}")

    print(f"\n{'='*60}")
    print(f"Extracted: {extracted}/{len(failed_names)}")
    if still_failed:
        print(f"Still failed: {len(still_failed)}")
        for name, err in still_failed.items():
            print(f"  - {name}: {err[:80]}")


if __name__ == "__main__":
    main()
