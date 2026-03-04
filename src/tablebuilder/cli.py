# ABOUTME: Click CLI entry point for the tablebuilder command.
# ABOUTME: Provides fetch, datasets, dictionary, and doctor subcommands.

import sys
from datetime import datetime

import click

from tablebuilder.config import ConfigError, load_config
from tablebuilder.knowledge import KnowledgeBase
from tablebuilder.logging_config import setup_logging
from tablebuilder.models import TableRequest


@click.group()
@click.option('-v', '--verbose', is_flag=True, help='Show debug logging.')
@click.pass_context
def cli(ctx, verbose):
    """Download data from ABS TableBuilder."""
    ctx.ensure_object(dict)
    setup_logging(verbose)
    ctx.obj['knowledge'] = KnowledgeBase()


@cli.command()
@click.option("--dataset", required=True, help="Dataset name (fuzzy-matched).")
@click.option(
    "--rows", multiple=True, required=True, help="Variable(s) to place in rows."
)
@click.option("--cols", multiple=True, help="Variable(s) to place in columns.")
@click.option("--wafers", multiple=True, help="Variable(s) to place in wafers.")
@click.option(
    "-o",
    "--output",
    default=None,
    help="Output CSV path. Defaults to ./tablebuilder_YYYYMMDD_HHMMSS.csv.",
)
@click.option("--headed", is_flag=True, help="Show browser window for debugging.")
@click.option("--user-id", default=None, help="ABS User ID (overrides .env).")
@click.option("--password", default=None, help="ABS password (overrides .env).")
@click.option(
    "--timeout",
    default=600,
    type=int,
    help="Queue timeout in seconds (default: 600).",
)
@click.pass_context
def fetch(ctx, dataset, rows, cols, wafers, output, headed, user_id, password, timeout):
    """Fetch a table from ABS TableBuilder and download as CSV."""
    knowledge = ctx.obj['knowledge']
    knowledge.record_run()

    try:
        config = load_config(user_id=user_id, password=password)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    request = TableRequest(
        dataset=dataset,
        rows=list(rows),
        cols=list(cols),
        wafers=list(wafers),
    )

    if output is None:
        output = f"tablebuilder_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    click.echo(f"Dataset: {request.dataset}")
    click.echo(f"Rows: {', '.join(request.rows)}")
    if request.cols:
        click.echo(f"Cols: {', '.join(request.cols)}")
    if request.wafers:
        click.echo(f"Wafers: {', '.join(request.wafers)}")
    click.echo(f"Output: {output}")

    from tablebuilder.browser import TableBuilderSession, LoginError
    from tablebuilder.navigator import open_dataset, NavigationError
    from tablebuilder.table_builder import build_table, TableBuildError
    from tablebuilder.downloader import queue_and_download, DownloadError

    try:
        with TableBuilderSession(config, headless=not headed, knowledge=knowledge) as page:
            click.echo("Logged in to TableBuilder.")

            click.echo(f"Opening dataset: {request.dataset}")
            open_dataset(page, request.dataset, knowledge=knowledge)

            click.echo("Building table...")
            build_table(page, request, knowledge=knowledge)

            click.echo(f"Queuing and downloading to {output}...")
            queue_and_download(page, output, timeout=timeout, knowledge=knowledge)

            click.echo(f"Done! CSV saved to {output}")

    except LoginError as e:
        click.echo(f"Login error: {e}", err=True)
        sys.exit(1)
    except NavigationError as e:
        click.echo(f"Navigation error: {e}", err=True)
        sys.exit(1)
    except TableBuildError as e:
        click.echo(f"Table build error: {e}", err=True)
        sys.exit(1)
    except DownloadError as e:
        click.echo(f"Download error: {e}", err=True)
        sys.exit(1)
    finally:
        knowledge.save()


@cli.command()
@click.option("--user-id", default=None, help="ABS User ID (overrides .env).")
@click.option("--password", default=None, help="ABS password (overrides .env).")
@click.pass_context
def datasets(ctx, user_id, password):
    """List available datasets in TableBuilder."""
    knowledge = ctx.obj['knowledge']

    try:
        config = load_config(user_id=user_id, password=password)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    from tablebuilder.browser import TableBuilderSession, LoginError
    from tablebuilder.navigator import list_datasets

    try:
        with TableBuilderSession(config, headless=True, knowledge=knowledge) as page:
            datasets_list = list_datasets(page, knowledge=knowledge)
            for name in sorted(datasets_list):
                click.echo(name)
    except LoginError as e:
        click.echo(f"Login error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--dataset", default=None, help="Single dataset (fuzzy-matched). Omit for all.")
@click.option(
    "-o",
    "--output",
    default=None,
    help="Output markdown path. Defaults to ./data_dictionary_YYYYMMDD.md.",
)
@click.option("--headed", is_flag=True, help="Show browser window for debugging.")
@click.option("--user-id", default=None, help="ABS User ID (overrides .env).")
@click.option("--password", default=None, help="ABS password (overrides .env).")
@click.option(
    "--exclude-census/--include-census",
    default=True,
    help="Exclude Census datasets (default: exclude).",
)
@click.option("--resume/--no-resume", default=True, help="Resume from previous run.")
@click.option("--clear-cache", is_flag=True, help="Clear cached extractions.")
@click.pass_context
def dictionary(ctx, dataset, output, headed, user_id, password, exclude_census, resume, clear_cache):
    """Extract data dictionary from TableBuilder datasets."""
    import shutil
    from pathlib import Path

    from tablebuilder.browser import TableBuilderSession, LoginError
    from tablebuilder.dict_formatter import format_data_dictionary
    from tablebuilder.navigator import NavigationError, open_dataset, navigate_back_to_catalogue
    from tablebuilder.tree_extractor import (
        extract_all_datasets,
        extract_dataset_tree,
        DICT_CACHE_DIR,
    )

    knowledge = ctx.obj['knowledge']

    if clear_cache and DICT_CACHE_DIR.exists():
        shutil.rmtree(DICT_CACHE_DIR)
        click.echo("Cleared extraction cache.")

    if output is None:
        output = f"data_dictionary_{datetime.now().strftime('%Y%m%d')}.md"

    try:
        config = load_config(user_id=user_id, password=password)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    try:
        with TableBuilderSession(config, headless=not headed, knowledge=knowledge) as page:
            click.echo("Logged in to TableBuilder.")

            if dataset:
                # Single dataset mode
                click.echo(f"Opening dataset: {dataset}")
                open_dataset(page, dataset, knowledge=knowledge)
                tree = extract_dataset_tree(page, dataset, knowledge=knowledge)
                markdown = format_data_dictionary([tree])
                with open(output, 'w') as f:
                    f.write(markdown)
                click.echo(f"Dictionary saved to {output}")
                click.echo(
                    f"  {len(tree.geographies)} geographies, "
                    f"{len(tree.groups)} variable groups"
                )
            else:
                # Batch mode
                click.echo("Extracting data dictionary for all datasets...")
                trees = extract_all_datasets(
                    page,
                    exclude_census=exclude_census,
                    resume=resume,
                    knowledge=knowledge,
                )
                markdown = format_data_dictionary(trees)
                with open(output, 'w') as f:
                    f.write(markdown)
                click.echo(f"Done! Dictionary saved to {output}")
                click.echo(f"  {len(trees)} datasets extracted")

    except LoginError as e:
        click.echo(f"Login error: {e}", err=True)
        sys.exit(1)
    except NavigationError as e:
        click.echo(f"Navigation error: {e}", err=True)
        sys.exit(1)
    finally:
        knowledge.save()


@cli.command()
@click.pass_context
def doctor(ctx):
    """Show health status, known issues, and accumulated knowledge."""
    from tablebuilder.doctor import check_credentials, run_doctor

    knowledge = ctx.obj['knowledge']
    credentials_ok = check_credentials()
    report = run_doctor(knowledge, credentials_ok=credentials_ok)
    click.echo(report)
