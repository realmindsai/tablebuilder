# ABOUTME: Click CLI entry point for the tablebuilder command.
# ABOUTME: Provides fetch, datasets, variables, and doctor subcommands.

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
@click.argument("dataset")
@click.option("--user-id", default=None, help="ABS User ID (overrides .env).")
@click.option("--password", default=None, help="ABS password (overrides .env).")
def variables(dataset, user_id, password):
    """List variables in a TableBuilder dataset."""
    click.echo("Not yet implemented.")
    sys.exit(1)


@cli.command()
@click.pass_context
def doctor(ctx):
    """Show health status, known issues, and accumulated knowledge."""
    from tablebuilder.doctor import check_credentials, run_doctor

    knowledge = ctx.obj['knowledge']
    credentials_ok = check_credentials()
    report = run_doctor(knowledge, credentials_ok=credentials_ok)
    click.echo(report)
