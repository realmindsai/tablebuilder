// src/shared/abs/jsf.ts
import type { Page } from 'playwright-core';
import type { Axis } from './types.js';
import { noopReporter, NEVER_ABORT, CancelledError, type PhaseReporter } from './reporter.js';

const AXIS_SELECTORS: Record<Axis, string> = {
  row: '#buttonForm\\:addR',
  col: '#buttonForm\\:addC',
  wafer: '#buttonForm\\:addL',
};

// submitJsfForm owns the post-submit wait. Callers do not add extra waits.
// No phase events here — called from inside selectVariables which owns the submit phase.
export async function submitJsfForm(page: Page, axis: Axis): Promise<void> {
  const selector = AXIS_SELECTORS[axis];
  await page.evaluate((sel: string) => {
    const btn = document.querySelector<HTMLInputElement>(sel);
    if (!btn || !btn.form) throw new Error(`Axis button not found: ${sel}`);
    const hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.name = btn.name;
    hidden.value = btn.value;
    btn.form.appendChild(hidden);
    btn.form.submit();
  }, selector);
  try {
    await page.waitForLoadState('load', { timeout: 15000 });
  } catch {
    await new Promise(r => setTimeout(r, 5000));
  }
}

export async function retrieveTable(
  page: Page,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<void> {
  const t0 = Date.now();
  reporter({ type: 'phase_start', phaseId: 'retrieve', phaseLabel: 'Retrieving table data', phaseSub: 'ABS is computing the table' });
  reporter({ type: 'log', level: 'phase', message: '» phase 6/7 — Retrieving table data' });

  // Select CSV format BEFORE retrieve (matches Python's queue_and_download order)
  const fmtExists = await page.locator('#downloadControl\\:downloadType').count() > 0;
  console.log(`retrieveTable: format dropdown exists=${fmtExists}`);
  await page.selectOption('#downloadControl\\:downloadType', 'CSV').catch(() => null);

  if (signal.aborted) throw new CancelledError();

  reporter({ type: 'log', level: 'info', message: '  waiting on ABS compute engine… this may take a moment' });

  // #pageForm:retB is the Retrieve Data button — force-click past any overlay
  await page.locator('#pageForm\\:retB').click({ force: true });

  // Wait up to 3 minutes for the download button to appear after retrieve click.
  // ABS retrieval is async — cancel button may show for 30s-2min during processing.
  const dlSelectors = [
    '#downloadControl\\:downloadButton',
    'input[value="Download table"]',
    'a[title="Download table"]',
  ];
  const dlCssOrChain = dlSelectors.join(', ');

  console.log('retrieveTable: waiting for download controls...');

  // Race the selector wait against the abort signal
  const abortPromise = new Promise<false>(resolve =>
    signal.addEventListener('abort', () => resolve(false), { once: true })
  );
  const found = await Promise.race([
    page.waitForSelector(dlCssOrChain, { timeout: 90_000 }).then(() => true).catch(() => false),
    abortPromise,
  ]);

  if (signal.aborted) throw new CancelledError();

  if (found) {
    console.log('retrieveTable: download controls appeared — retrieval complete');
    reporter({ type: 'log', level: 'ok', message: '  ✓ ABS retrieval complete — download controls visible' });
  } else {
    console.log('retrieveTable: 3-minute wait expired — proceeding anyway');
    reporter({ type: 'log', level: 'warn', message: '  ⚠ retrieval timeout — attempting download anyway' });
  }

  reporter({ type: 'phase_complete', phaseId: 'retrieve', elapsed: (Date.now() - t0) / 1000 });
}
