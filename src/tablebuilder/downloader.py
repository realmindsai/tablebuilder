# ABOUTME: Queue tables, poll for completion, and download CSV results.
# ABOUTME: Handles format selection, queue submission, status polling, and zip extraction.

import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


class DownloadError(Exception):
    """Raised when table download fails."""


def generate_table_name() -> str:
    """Generate a unique table name with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = uuid4().hex[:6]
    return f"tb_{timestamp}_{short_id}"


SAVED_TABLES_URL = (
    "https://tablebuilder.abs.gov.au/webapi/jsf/tableView/openTable.xhtml"
)


def queue_and_download(
    page: Page,
    output_path: str,
    timeout: int = 600,
) -> None:
    """Select CSV format, queue the table, wait for completion, download."""
    table_name = generate_table_name()

    # Select CSV format from the download type dropdown
    page.select_option('#downloadControl\\:downloadType', value='CSV')
    page.wait_for_timeout(500)

    # Click the queue/download large table button
    queue_btn = page.query_selector('#downloadControl\\:downloadLargeTableButton')
    if not queue_btn:
        raise DownloadError("Cannot find the queue table button.")
    queue_btn.click()
    page.wait_for_timeout(1000)

    # Fill the table name in the queue dialog
    page.fill('#downloadTableModeForm\\:downloadTableNameTxt', table_name)

    # Submit the queue dialog
    submit_btn = page.query_selector(
        '#downloadTableModeForm\\:queueTableButton'
    )
    if not submit_btn:
        raise DownloadError("Cannot find the queue submit button.")
    submit_btn.click()
    page.wait_for_timeout(2000)

    # Navigate to the saved/queued tables page
    page.goto(SAVED_TABLES_URL, wait_until="networkidle")

    # Poll for completion — look for "click here to download" link
    poll_interval_ms = 5000
    elapsed_ms = 0
    max_ms = timeout * 1000
    download_link = None

    while elapsed_ms < max_ms:
        # Find link containing "click here to download"
        links = page.query_selector_all('a')
        for link in links:
            link_text = (link.text_content() or '').lower()
            if 'click here to download' in link_text:
                download_link = link
                break

        if download_link:
            break

        page.wait_for_timeout(poll_interval_ms)
        elapsed_ms += poll_interval_ms
        page.reload()
        page.wait_for_load_state("networkidle", timeout=10000)
    else:
        raise DownloadError(
            f"Table did not complete within {timeout} seconds. "
            "Check 'Saved and queued tables' in TableBuilder manually."
        )

    # Download the file (triggers a ZIP download)
    with page.expect_download(timeout=30000) as download_info:
        download_link.click()

    download = download_info.value
    download_path = Path(download.path())

    # Extract CSV from the downloaded ZIP
    output = Path(output_path)
    if zipfile.is_zipfile(download_path):
        with zipfile.ZipFile(download_path) as zf:
            csv_files = [f for f in zf.namelist() if f.endswith(".csv")]
            if not csv_files:
                raise DownloadError("Downloaded zip contains no CSV files.")
            zf.extract(csv_files[0], output.parent)
            extracted = output.parent / csv_files[0]
            extracted.rename(output)
    else:
        shutil.copy2(download_path, output)


def cleanup_saved_table(page: Page, table_name: str) -> None:
    """Delete a saved table from the queue to keep things tidy."""
    try:
        # Find the table row with our name and click delete
        table_row = page.get_by_text(table_name).first
        if table_row:
            delete_btn = table_row.locator(".. >> button:has-text('Delete')")
            if delete_btn.count() > 0:
                delete_btn.click()
                # Confirm deletion
                confirm = page.query_selector(
                    "button:has-text('OK'), button:has-text('Yes')"
                )
                if confirm:
                    confirm.click()
    except Exception:
        pass  # Cleanup failure is not critical
