# ABOUTME: Retrieve table data and download CSV results from ABS TableBuilder.
# ABOUTME: Handles data retrieval, format selection, and direct or queued download.

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


def _retrieve_data(page: Page) -> None:
    """Click the Retrieve Data button and wait for table to populate.

    pageForm:retB is the Retrieve button. It sits behind the autoRetrieve
    overlay, so we use force click.
    """
    logger.info("Retrieving table data")
    page.locator(QUEUE_BUTTON.primary).click(force=True)

    # Wait for table to populate with numeric data
    for _wait in range(30):
        page.wait_for_timeout(2000)
        cells = page.query_selector_all('td')
        if any((c.text_content() or '').strip().replace(',', '').isdigit()
               for c in cells[:20]):
            logger.info("Data retrieved successfully")
            return

    logger.warning("Data retrieval may not have completed — proceeding anyway")


def _find_download_button(page: Page):
    """Find the 'Download table' button in the table view toolbar."""
    # Try known selectors
    for selector in [
        '#downloadControl\\:downloadButton',
        'input[value="Download table"]',
        'a[title="Download table"]',
    ]:
        btn = page.query_selector(selector)
        if btn:
            logger.debug("Found download button via: %s", selector)
            return btn

    # Try locator text match
    locator = page.locator('text="Download table"').first
    if locator.count() > 0:
        return locator

    # Dump available controls for debugging
    controls = page.evaluate("""() => {
        const els = document.querySelectorAll(
            'input[type=submit], input[type=button], button, a[class*=download], a[id*=download]'
        );
        return Array.from(els).map(e =>
            e.id + '|' + e.className + '|' + (e.value || e.textContent || '').substring(0, 50)
        );
    }""")
    logger.error("No download button found. Available controls: %s", controls)
    return None


def queue_and_download(
    page: Page,
    output_path: str,
    timeout: int = 1200,
    knowledge=None,
) -> None:
    """Retrieve table data and download as CSV.

    Flow:
    1. Select CSV from the format dropdown
    2. Click Retrieve Data (pageForm:retB) to populate the table
    3. Click Download table to get the CSV directly
    4. If direct download fails, fall back to queue flow
    """
    download_start = time.time()

    # Select CSV format from the download type dropdown
    format_select = find_element(page, FORMAT_DROPDOWN, knowledge)
    if format_select:
        page.select_option(FORMAT_DROPDOWN.primary, value='CSV')
        page.wait_for_timeout(500)
        logger.debug("Selected CSV format")

    # Retrieve data first
    _retrieve_data(page)

    # Try direct download via the Download table button
    download_btn = _find_download_button(page)
    if download_btn:
        logger.info("Attempting direct download")
        try:
            with page.expect_download(timeout=60000) as download_info:
                if hasattr(download_btn, 'evaluate'):
                    # ElementHandle — use force via JS
                    download_btn.evaluate("el => el.click()")
                else:
                    # Locator
                    download_btn.click(force=True)

            download = download_info.value
            _save_download(download, output_path)

            duration = time.time() - download_start
            logger.info("Download completed in %.1f seconds", duration)
            if knowledge is not None:
                knowledge.record_timing("queue_and_download", duration)
            return

        except PlaywrightTimeout:
            logger.warning("Direct download timed out — falling back to queue flow")

    # Fallback: queue flow for large tables
    _queue_and_poll_download(page, output_path, timeout, knowledge, download_start)


def _save_download(download, output_path: str) -> None:
    """Save a Playwright download to the output path, extracting from ZIP if needed."""
    download_path = Path(download.path())
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

    logger.info("Saved to %s", output_path)


def _queue_and_poll_download(
    page: Page,
    output_path: str,
    timeout: int,
    knowledge,
    start_time: float,
) -> None:
    """Queue a table and poll for download link (for large tables)."""
    table_name = generate_table_name()
    logger.info("Queuing table as '%s'", table_name)

    # Open the queue dialog
    queue_btn = find_element(page, QUEUE_BUTTON, knowledge)
    if not queue_btn:
        raise DownloadError("Cannot find the Queue/Retrieve button.")

    queue_btn.evaluate("el => el.click()")
    page.wait_for_timeout(3000)

    # Fill and submit the queue dialog
    name_input = find_element(page, QUEUE_NAME_INPUT, knowledge)
    if not name_input:
        raise DownloadError("Queue dialog name input not found.")

    name_input.evaluate(
        f"el => {{ el.value = '{table_name}'; "
        f"el.dispatchEvent(new Event('change')); }}"
    )

    submit_btn = find_element(page, QUEUE_SUBMIT, knowledge)
    if not submit_btn:
        raise DownloadError("Cannot find the queue submit button.")
    submit_btn.evaluate("el => el.click()")
    page.wait_for_timeout(3000)
    logger.info("Queue dialog submitted")

    # Navigate to saved tables and poll
    page.goto(SAVED_TABLES_URL, wait_until="networkidle", timeout=60000)

    poll_interval_ms = 5000
    elapsed_ms = 0
    max_ms = timeout * 1000
    download_link = None

    while elapsed_ms < max_ms:
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

    with page.expect_download(timeout=30000) as download_info:
        download_link.click()

    _save_download(download_info.value, output_path)

    duration = time.time() - start_time
    logger.info("Queue and download completed in %.1f seconds", duration)
    if knowledge is not None:
        knowledge.record_timing("queue_and_download", duration)


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
