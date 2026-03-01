# ABOUTME: Click CLI entry point for the tablebuilder command.
# ABOUTME: Provides fetch, datasets, variables subcommands.

import sys
from datetime import datetime

import click

from tablebuilder.config import ConfigError, load_config
from tablebuilder.models import TableRequest


@click.group()
def cli():
    """Download data from ABS TableBuilder."""


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
def fetch(dataset, rows, cols, wafers, output, headed, user_id, password, timeout):
    """Fetch a table from ABS TableBuilder and download as CSV."""
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
        with TableBuilderSession(config, headless=not headed) as page:
            click.echo("Logged in to TableBuilder.")

            click.echo(f"Opening dataset: {request.dataset}")
            open_dataset(page, request.dataset)

            click.echo("Building table...")
            build_table(page, request)

            click.echo(f"Queuing and downloading to {output}...")
            queue_and_download(page, output, timeout=timeout)

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


@cli.command()
@click.option("--user-id", default=None, help="ABS User ID (overrides .env).")
@click.option("--password", default=None, help="ABS password (overrides .env).")
def datasets(user_id, password):
    """List available datasets in TableBuilder."""
    try:
        config = load_config(user_id=user_id, password=password)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    from tablebuilder.browser import TableBuilderSession, LoginError
    from tablebuilder.navigator import list_datasets

    try:
        with TableBuilderSession(config, headless=True) as page:
            datasets_list = list_datasets(page)
            for name in sorted(datasets_list):
                click.echo(name)
    except LoginError as e:
        click.echo(f"Login error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("dataset")
@click.option("--user-id", default=None, help="ABS User ID (overrides .env).")
@click.option("--password", default=None, help="ABS password (overrides .env).")
def variables(dataset, user_id, password):
    """List variables in a TableBuilder dataset."""
    click.echo("Not yet implemented.")
    sys.exit(1)
