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


def queue_and_download(
    page: Page,
    output_path: str,
    timeout: int = 600,
) -> None:
    """Select CSV format, queue the table, wait for completion, download."""
    table_name = generate_table_name()

    # Select CSV format from the dropdown
    format_dropdown = page.query_selector(
        "select[class*='format'], select[id*='format']"
    )
    if format_dropdown:
        format_dropdown.select_option(label="Comma Separated Value (.csv)")
    else:
        # Try clicking a format option directly
        csv_option = page.query_selector("text=CSV, text=Comma Separated")
        if csv_option:
            csv_option.click()

    page.wait_for_timeout(500)

    # Click "Queue table" button
    queue_button = page.get_by_text("Queue table").first
    if not queue_button:
        # Alternative text
        queue_button = page.get_by_text("Retrieve data").first
    if not queue_button:
        raise DownloadError("Cannot find the Queue/Retrieve button.")

    queue_button.click()
    page.wait_for_timeout(1000)

    # Enter table name in the dialog
    name_input = page.query_selector(
        "input[type='text']:visible, input[class*='table-name']"
    )
    if name_input:
        name_input.fill(table_name)

    # Confirm/OK
    ok_button = page.query_selector(
        "button:has-text('OK'), button:has-text('Save'), input[value='OK']"
    )
    if ok_button:
        ok_button.click()
    page.wait_for_timeout(2000)

    # Navigate to Saved and queued tables
    saved_link = page.query_selector(
        "text=Saved and queued tables, a:has-text('Saved')"
    )
    if saved_link:
        saved_link.click()
        page.wait_for_load_state("networkidle", timeout=10000)

    # Poll for completion
    poll_interval_ms = 5000
    elapsed_ms = 0
    max_ms = timeout * 1000

    while elapsed_ms < max_ms:
        # Look for "Completed" status next to our table name
        completed = page.query_selector(
            f"text=Completed >> .. >> text=download, "
            f"a:has-text('download')"
        )
        if completed:
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

    # Download the file
    with page.expect_download(timeout=30000) as download_info:
        completed.click()

    download = download_info.value
    download_path = Path(download.path())

    # Extract if zip, otherwise copy directly
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
