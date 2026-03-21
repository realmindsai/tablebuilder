#!/usr/bin/env python3
# ABOUTME: Re-extracts datasets with missing category data from ABS TableBuilder.
# ABOUTME: Deletes broken cache files, re-extracts from live site, rebuilds the DB.

"""Re-extract datasets that have variables with 0 categories in the dictionary cache.

Usage:
    uv run python scripts/reextract_broken_datasets.py [--headed] [--dry-run]
"""

import json
import os
import sys
from pathlib import Path

import click

CACHE_DIR = Path.home() / ".tablebuilder" / "dict_cache"


def find_broken_datasets() -> list[tuple[str, str, int, int]]:
    """Find datasets with variables that have 0 categories.

    Returns list of (filename, dataset_name, total_vars, zero_cat_vars).
    """
    broken = []
    for f in sorted(CACHE_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        total_vars = sum(len(g.get("variables", [])) for g in data.get("groups", []))
        zero_cat_vars = sum(
            1
            for g in data.get("groups", [])
            for v in g.get("variables", [])
            if len(v.get("categories", [])) == 0
        )
        if zero_cat_vars > 0:
            broken.append((f.name, data["dataset_name"], total_vars, zero_cat_vars))
    return broken


@click.command()
@click.option("--headed", is_flag=True, help="Show browser window for debugging.")
@click.option("--dry-run", is_flag=True, help="Just list broken datasets, don't re-extract.")
def main(headed, dry_run):
    """Re-extract datasets with missing category data."""
    broken = find_broken_datasets()

    if not broken:
        click.echo("No broken datasets found. All cache files have categories.")
        return

    click.echo(f"Found {len(broken)} datasets with missing categories:\n")
    for filename, name, total, zero in broken:
        click.echo(f"  {name}")
        click.echo(f"    {zero}/{total} variables missing categories")
        click.echo(f"    Cache file: {filename}")
    click.echo()

    if dry_run:
        click.echo("Dry run — not re-extracting.")
        return

    # Delete broken cache files
    dataset_names = []
    for filename, name, _, _ in broken:
        cache_path = CACHE_DIR / filename
        click.echo(f"Deleting {cache_path}")
        cache_path.unlink()
        dataset_names.append(name)

    # Re-extract using the existing extraction pipeline
    from tablebuilder.config import load_config
    from tablebuilder.browser import TableBuilderSession
    from tablebuilder.knowledge import KnowledgeBase
    from tablebuilder.tree_extractor import extract_dataset_tree, _save_tree_cache
    from tablebuilder.navigator import open_dataset, navigate_back_to_catalogue

    knowledge = KnowledgeBase()
    config = load_config()

    click.echo(f"\nRe-extracting {len(dataset_names)} datasets from ABS TableBuilder...")
    click.echo("This requires a live browser session and may take several minutes.\n")

    succeeded = []
    failed = []

    with TableBuilderSession(config, headless=not headed, knowledge=knowledge) as page:
        click.echo("Logged in to TableBuilder.\n")

        for i, name in enumerate(dataset_names, 1):
            click.echo(f"[{i}/{len(dataset_names)}] Extracting: {name}")
            try:
                open_dataset(page, name, knowledge=knowledge)
                tree = extract_dataset_tree(page, name, knowledge=knowledge)

                # Verify we got categories this time
                total_cats = sum(
                    len(v.categories)
                    for g in tree.groups
                    for v in g.variables
                )
                if total_cats == 0:
                    click.echo(f"  WARNING: Still got 0 categories. Saving anyway.")
                else:
                    click.echo(f"  Extracted {total_cats} categories across {sum(len(g.variables) for g in tree.groups)} variables.")

                _save_tree_cache(tree, CACHE_DIR)
                succeeded.append(name)

            except Exception as e:
                click.echo(f"  FAILED: {e}")
                failed.append((name, str(e)))

            # Navigate back for next dataset
            try:
                navigate_back_to_catalogue(page)
            except Exception:
                pass

    click.echo(f"\nDone. {len(succeeded)} succeeded, {len(failed)} failed.")

    if failed:
        click.echo("\nFailed datasets:")
        for name, err in failed:
            click.echo(f"  {name}: {err}")

    if succeeded:
        # Rebuild the database
        click.echo("\nRebuilding dictionary database...")
        from tablebuilder.dictionary_db import build_db, DEFAULT_DB_PATH, DEFAULT_CACHE_DIR
        build_db(DEFAULT_CACHE_DIR, DEFAULT_DB_PATH)
        click.echo(f"Database rebuilt at {DEFAULT_DB_PATH}")

        # Copy to query-planner
        import shutil
        qp_db = Path(__file__).parent.parent / "query-planner" / "dictionary.db"
        if qp_db.is_symlink() or qp_db.exists():
            click.echo(f"Query planner DB symlink: {qp_db} -> {os.readlink(qp_db) if qp_db.is_symlink() else 'file'}")
        click.echo("\nRefresh your browser to see updated data.")

    knowledge.save()


if __name__ == "__main__":
    main()
