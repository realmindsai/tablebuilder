#!/usr/bin/env python3
# ABOUTME: Test the improved tree extraction on a single dataset.
# ABOUTME: Verifies the batch expansion JS approach captures all categories.

"""Test extraction on a single dataset to verify the expansion fix.

Usage:
    uv run python scripts/test_single_extraction.py --dataset "2021 Census - counting persons, 15 years and over" --headed
"""

import json

import click

from tablebuilder.config import load_config
from tablebuilder.browser import TableBuilderSession
from tablebuilder.knowledge import KnowledgeBase
from tablebuilder.logging_config import setup_logging
from tablebuilder.tree_extractor import extract_dataset_tree, _save_tree_cache, DEFAULT_CACHE_DIR
from tablebuilder.navigator import open_dataset


@click.command()
@click.option("--dataset", required=True, help="Dataset name to extract.")
@click.option("--headed", is_flag=True, help="Show browser window.")
@click.option("--verbose", "-v", is_flag=True, help="Debug logging.")
def main(dataset, headed, verbose):
    """Extract a single dataset and show category counts."""
    setup_logging(verbose)
    knowledge = KnowledgeBase()
    config = load_config()

    with TableBuilderSession(config, headless=not headed, knowledge=knowledge) as page:
        click.echo(f"Logged in. Opening: {dataset}")
        open_dataset(page, dataset, knowledge=knowledge)

        click.echo("Extracting tree...")
        tree = extract_dataset_tree(page, dataset, knowledge=knowledge)

        total_vars = sum(len(g.variables) for g in tree.groups)
        total_cats = sum(len(v.categories) for g in tree.groups for v in g.variables)
        one_cat = sum(1 for g in tree.groups for v in g.variables if len(v.categories) <= 1)

        click.echo(f"\nResults:")
        click.echo(f"  Groups: {len(tree.groups)}")
        click.echo(f"  Variables: {total_vars}")
        click.echo(f"  Categories: {total_cats}")
        click.echo(f"  Variables with 0-1 cats: {one_cat}")

        # Show specific variables of interest
        click.echo(f"\nKey variables:")
        for g in tree.groups:
            for v in g.variables:
                if v.code in ('AGEP', 'AGE5P', 'AGE10P', 'ANCP', 'ANC1P', 'BPLP', 'LANP'):
                    click.echo(f"  {v.code:10s} {len(v.categories):4d} cats  {v.label}")

        # Save to cache
        _save_tree_cache(tree, DEFAULT_CACHE_DIR)
        click.echo(f"\nSaved to cache.")

    knowledge.save()


if __name__ == "__main__":
    main()
