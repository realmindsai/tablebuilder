# ABOUTME: Queue tables, poll for completion, and download CSV results.
# ABOUTME: Handles queue submission, status polling, and zip extraction.

import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from tablebuilder.logging_config import get_logger
from tablebuilder.resilience import find_element
from tablebuilder.selectors import (
    FORMAT_DROPDOWN,
    QUEUE_BUTTON,
    QUEUE_DIALOG,
    QUEUE_NAME_INPUT,
    QUEUE_SUBMIT,
)

logger = get_logger("tablebuilder.downloader")


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
    knowledge=None,
) -> None:
    """Queue the table, wait for completion, download CSV.

    The queue flow on the TableBuilder UI:
    1. Click the "Queue table" button (pageForm:retB) on the table view
    2. A dialog appears with a name field (downloadTableModeForm)
    3. Fill the name, click submit in the dialog
    4. Navigate to the saved/queued tables page
    5. Poll for "Completed, click here to download" link
    6. Click to download ZIP, extract CSV
    """
    queue_start = time.time()
    table_name = generate_table_name()
    logger.info("Queuing table as '%s'", table_name)

    # Select CSV format from the download type dropdown (default is EXCEL_2007)
    format_select = find_element(page, FORMAT_DROPDOWN, knowledge)
    if format_select:
        page.select_option(FORMAT_DROPDOWN.primary, value='CSV')
        page.wait_for_timeout(500)
        logger.debug("Selected CSV format")

    # Click the Queue table button on the table view page
    queue_btn = find_element(page, QUEUE_BUTTON, knowledge)
    if not queue_btn:
        raise DownloadError("Cannot find the 'Queue table' button.")

    queue_btn.click()
    page.wait_for_timeout(3000)

    # The queue dialog should appear
    dialog = find_element(page, QUEUE_DIALOG, knowledge)
    if dialog and dialog.is_visible():
        # Fill the table name
        name_input = find_element(page, QUEUE_NAME_INPUT, knowledge)
        if name_input:
            name_input.fill(table_name)

        # Submit the dialog
        submit_btn = find_element(page, QUEUE_SUBMIT, knowledge)
        if not submit_btn:
            raise DownloadError("Cannot find the queue submit button in dialog.")
        submit_btn.click()
        page.wait_for_timeout(3000)
        logger.info("Queue dialog submitted")
    else:
        raise DownloadError(
            "Queue dialog did not appear after clicking 'Queue table'. "
            "The table may need data before queuing."
        )

    # Navigate to the saved/queued tables page
    page.goto(SAVED_TABLES_URL, wait_until="networkidle")

    # Poll for completion — look for "click here to download" link
    poll_interval_ms = 5000
    elapsed_ms = 0
    max_ms = timeout * 1000
    download_link = None

    while elapsed_ms < max_ms:
        # Find the row for our specific table, then look for its download link
        rows = page.query_selector_all('tr')
        for row in rows:
            row_text = row.text_content() or ''
            if table_name in row_text and 'click here to download' in row_text.lower():
                download_link = row.query_selector('a')
                break

        if download_link:
            break

        page.wait_for_timeout(poll_interval_ms)
        elapsed_ms += poll_interval_ms
        page.reload()
        page.wait_for_load_state("networkidle", timeout=10000)
        logger.debug("Polling for table completion (%ds elapsed)", elapsed_ms // 1000)
    else:
        raise DownloadError(
            f"Table did not complete within {timeout} seconds. "
            "Check 'Saved and queued tables' in TableBuilder manually."
        )

    logger.info("Table ready for download")

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
            if extracted != output:
                shutil.move(str(extracted), str(output))
    else:
        shutil.copy2(download_path, output)

    queue_duration = time.time() - queue_start
    logger.info("Queue and download completed in %.1f seconds", queue_duration)
    if knowledge is not None:
        knowledge.record_timing("queue_and_download", queue_duration)


def cleanup_saved_table(page: Page, table_name: str) -> None:
    """Delete a saved table from the queue to keep things tidy."""
    try:
        table_row = page.get_by_text(table_name).first
        if table_row:
            delete_btn = table_row.locator(".. >> button:has-text('Delete')")
            if delete_btn.count() > 0:
                delete_btn.click()
                confirm = page.query_selector(
                    "button:has-text('OK'), button:has-text('Yes')"
                )
                if confirm:
                    confirm.click()
    except Exception:
        pass  # Cleanup failure is not critical
