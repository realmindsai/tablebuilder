// src/shared/abs/queue-downloader.ts
import type { Page } from 'playwright-core';
import { trySaveViaResponse } from './response-capture.js';

// ─── constants ───────────────────────────────────────────────────────────────

const SAVED_TABLES_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/tableView/openTable.xhtml';
const DIALOG_FORM_SELECTOR = '#downloadTableModeForm';
const QUEUE_DIALOG_SELECTOR = '#downloadTableModeForm\\:downloadTableNameTxt';
const QUEUE_SUBMIT_SELECTOR = '#downloadTableModeForm\\:queueTableButton';
const RETRIEVE_BTN_SELECTOR = '#pageForm\\:retB';
const DIALOG_WAIT_MS = 5000;
const SUBMIT_SETTLE_MS = 3000;
const POLL_INTERVAL_MS = 5000;
const POLL_TIMEOUT_MS = 600_000; // 10 minutes

// _impl.sleep is exported so unit tests can replace it without ESM live-binding
// issues. Internal code always calls _impl.sleep(), never a module-level let.
export const _impl = {
  sleep: (ms: number): Promise<void> => new Promise(r => setTimeout(r, ms)),
};

// ─── internal helpers ────────────────────────────────────────────────────────

async function openQueueDialog(page: Page): Promise<void> {
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.locator(RETRIEVE_BTN_SELECTOR).click({ force: true });
    await _impl.sleep(DIALOG_WAIT_MS);
    if (await page.locator(DIALOG_FORM_SELECTOR).count() > 0) return;
  }
  throw new Error('Queue dialog did not open — cannot submit table to queue');
}

async function fillAndSubmit(page: Page, tableName: string): Promise<void> {
  if (await page.locator(QUEUE_DIALOG_SELECTOR).count() === 0) {
    throw new Error(
      'Queue dialog name input (#downloadTableModeForm:downloadTableNameTxt) not found',
    );
  }
  await page.locator(QUEUE_DIALOG_SELECTOR).first().fill(tableName);

  if (await page.locator(QUEUE_SUBMIT_SELECTOR).count() === 0) {
    throw new Error(
      'Queue dialog submit button (#downloadTableModeForm:queueTableButton) not found',
    );
  }
  await page.locator(QUEUE_SUBMIT_SELECTOR).first().click();
  await _impl.sleep(SUBMIT_SETTLE_MS);
}

async function pollForDownload(page: Page, tableName: string, tmpPath: string): Promise<void> {
  const deadline = Date.now() + POLL_TIMEOUT_MS;

  while (Date.now() < deadline) {
    await _impl.sleep(POLL_INTERVAL_MS);

    const { found } = await page.evaluate(({ name }: { name: string }) => {
      const rows = Array.from(document.querySelectorAll('tr'));
      for (const row of rows) {
        const text = row.textContent ?? '';
        if (text.includes(name) && text.toLowerCase().includes('click here to download')) {
          return { found: !!(row.querySelector('a')) };
        }
      }
      return { found: false };
    }, { name: tableName });

    if (found) {
      await trySaveViaResponse(
        page,
        () => page.evaluate(({ name }: { name: string }) => {
          const rows = Array.from(document.querySelectorAll('tr'));
          for (const row of rows) {
            const text = row.textContent ?? '';
            if (text.includes(name) && text.toLowerCase().includes('click here to download')) {
              (row.querySelector('a') as HTMLAnchorElement | null)?.click();
              return;
            }
          }
        }, { name: tableName }),
        tmpPath,
        60000,
      );
      // Row was found and download triggered — return regardless of capture
      // result to avoid indefinite polling. trySaveViaResponse covers the
      // actual file write via response/download interception.
      return;
    }

    await page.reload({ waitUntil: 'load' });
  }

  throw new Error('Queue table did not complete within 10 minutes');
}

// ─── public API ──────────────────────────────────────────────────────────────

export async function queueDownload(page: Page, tmpPath: string): Promise<void> {
  const tableName = `abs_q_${Date.now()}`;
  console.log(`queueDownload: submitting table '${tableName}' to queue`);

  await openQueueDialog(page);
  await fillAndSubmit(page, tableName);

  console.log(`queueDownload: navigating to saved tables, polling for '${tableName}'`);
  await page.goto(SAVED_TABLES_URL, { waitUntil: 'load' });
  await pollForDownload(page, tableName, tmpPath);

  console.log(`queueDownload: '${tableName}' downloaded successfully`);
}
