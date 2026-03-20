#!/usr/bin/env python3
# ABOUTME: Full re-extraction of all ABS TableBuilder datasets with improved expansion.
# ABOUTME: Discovers all datasets from the live site, extracts trees, rebuilds the DB.

"""Full re-extraction of all datasets from ABS TableBuilder.

Usage:
    uv run python scripts/full_reextract.py [--headed] [--dry-run]
"""

import json
import shutil
import time
from pathlib import Path

import click

from tablebuilder.config import load_config
from tablebuilder.browser import TableBuilderSession
from tablebuilder.knowledge import KnowledgeBase
from tablebuilder.logging_config import setup_logging
from tablebuilder.tree_extractor import (
    extract_dataset_tree,
    _save_tree_cache,
    DEFAULT_CACHE_DIR,
    DEFAULT_PROGRESS_PATH,
)
from tablebuilder.navigator import list_datasets, open_dataset, navigate_back_to_catalogue


PROGRESS_PATH = Path.home() / ".tablebuilder" / "full_reextract_progress.json"


def _load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return {"completed": [], "failed": {}, "total": 0}


def _save_progress(progress: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2))


@click.command()
@click.option("--headed", is_flag=True, help="Show browser window.")
@click.option("--dry-run", is_flag=True, help="Just list datasets, don't extract.")
@click.option("--resume/--no-resume", default=True, help="Resume from previous run.")
@click.option("--verbose", "-v", is_flag=True, help="Debug logging.")
def main(headed, dry_run, resume, verbose):
    """Full re-extraction of all ABS TableBuilder datasets."""
    setup_logging(verbose)
    knowledge = KnowledgeBase()
    config = load_config()

    progress = _load_progress() if resume else {"completed": [], "failed": {}, "total": 0}

    with TableBuilderSession(config, headless=not headed, knowledge=knowledge) as page:
        click.echo("Logged in. Discovering datasets...")
        all_datasets = list_datasets(page, knowledge)
        click.echo(f"Found {len(all_datasets)} datasets on ABS TableBuilder.")

        progress["total"] = len(all_datasets)

        if dry_run:
            for name in sorted(all_datasets):
                cached = name in progress["completed"]
                click.echo(f"  {'[done]' if cached else '[todo]'} {name}")
            todo = len(all_datasets) - len(progress["completed"])
            click.echo(f"\n{todo} datasets to extract.")
            return

        succeeded = []
        failed = []
        skipped = 0
        start_time = time.time()

        for i, name in enumerate(all_datasets, 1):
            if resume and name in progress["completed"]:
                skipped += 1
                continue

            elapsed = time.time() - start_time
            done_count = len(succeeded) + len(failed)
            if done_count > 0:
                avg = elapsed / done_count
                remaining = (len(all_datasets) - i) * avg
                eta_min = remaining / 60
                click.echo(f"[{i}/{len(all_datasets)}] (~{eta_min:.0f}m left) Extracting: {name}")
            else:
                click.echo(f"[{i}/{len(all_datasets)}] Extracting: {name}")

            try:
                open_dataset(page, name, knowledge=knowledge)
                tree = extract_dataset_tree(page, name, knowledge=knowledge)

                total_vars = sum(len(g.variables) for g in tree.groups)
                total_cats = sum(len(v.categories) for g in tree.groups for v in g.variables)
                bad_vars = sum(1 for g in tree.groups for v in g.variables if len(v.categories) <= 1)

                _save_tree_cache(tree, DEFAULT_CACHE_DIR)
                progress["completed"].append(name)
                _save_progress(progress)
                succeeded.append(name)

                click.echo(f"  {total_vars} vars, {total_cats} cats ({bad_vars} with 0-1 cats)")

            except Exception as e:
                click.echo(f"  FAILED: {e}")
                progress["failed"][name] = str(e)
                _save_progress(progress)
                failed.append((name, str(e)))

            try:
                navigate_back_to_catalogue(page)
            except Exception:
                pass

    total_time = time.time() - start_time
    click.echo(f"\nExtraction complete in {total_time/60:.1f} minutes.")
    click.echo(f"  Succeeded: {len(succeeded)}")
    click.echo(f"  Failed: {len(failed)}")
    click.echo(f"  Skipped (already done): {skipped}")

    if failed:
        click.echo("\nFailed datasets:")
        for name, err in failed:
            click.echo(f"  {name}: {err}")

    # Rebuild the database
    click.echo("\nRebuilding dictionary database...")
    from tablebuilder.dictionary_db import build_db, DEFAULT_DB_PATH, DEFAULT_CACHE_DIR as DB_CACHE_DIR
    build_db(DB_CACHE_DIR, DEFAULT_DB_PATH)
    click.echo(f"Database rebuilt at {DEFAULT_DB_PATH}")
    click.echo("Refresh your browser to see updated data.")

    knowledge.save()


if __name__ == "__main__":
    main()
