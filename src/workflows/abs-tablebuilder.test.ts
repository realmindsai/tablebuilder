// src/workflows/abs-tablebuilder.test.ts
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { existsSync, unlinkSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';
import { randomUUID } from 'crypto';
import { chromium, type Browser, type Page } from 'playwright';
import { selectDataset } from '../shared/abs/navigator.js';
import { submitJsfForm } from '../shared/abs/jsf.js';

let browser: Browser;
let page: Page;

beforeAll(async () => {
  browser = await chromium.launch({ headless: true });
  page = await browser.newPage();
}, 30000);

afterAll(async () => {
  await browser.close();
});

// ---------------------------------------------------------------------------
// submitJsfForm: real browser, mock HTML, intercept form submit
//
// NOTE: HTMLFormElement.prototype.submit() does NOT dispatch the submit event,
// so we override it on the prototype to capture what was injected into the form
// before the submit call.
// ---------------------------------------------------------------------------

const TABLE_VIEW_HTML = `
<html><body>
  <form id="buttonForm" action="/fake-jsf-action" method="POST">
    <input id="buttonForm:addR" name="buttonForm:addR" value="Add to Row" type="submit" />
    <input id="buttonForm:addC" name="buttonForm:addC" value="Add to Col" type="submit" />
    <input id="buttonForm:addL" name="buttonForm:addL" value="Add to Wafer" type="submit" />
  </form>
  <input id="searchPattern" type="text" />
  <button id="searchButton">Search</button>
</body></html>`;

describe('submitJsfForm (real browser, mock HTML)', () => {
  it('injects a hidden input with correct name before form.submit()', async () => {
    await page.setContent(TABLE_VIEW_HTML);

    // Override HTMLFormElement.prototype.submit so we can inspect the injected
    // hidden input without triggering a real navigation.
    // (The native form.submit() does NOT dispatch a submit event, so an event
    // listener on 'submit' would never fire — we must patch the method itself.)
    await page.evaluate(() => {
      HTMLFormElement.prototype.submit = function (this: HTMLFormElement) {
        const hidden = this.querySelector('input[type=hidden]') as HTMLInputElement | null;
        (window as unknown as Record<string, unknown>).__hiddenName__ = hidden?.name ?? null;
        (window as unknown as Record<string, unknown>).__submitted__ = true;
      };
    });

    await submitJsfForm(page, 'row');

    const submitted = await page.evaluate(
      () => (window as unknown as Record<string, unknown>).__submitted__
    );
    const hiddenName = await page.evaluate(
      () => (window as unknown as Record<string, unknown>).__hiddenName__
    );

    expect(submitted).toBe(true);
    expect(hiddenName).toBe('buttonForm:addR');
  });

  it('col axis injects buttonForm:addC', async () => {
    await page.setContent(TABLE_VIEW_HTML);
    await page.evaluate(() => {
      HTMLFormElement.prototype.submit = function (this: HTMLFormElement) {
        const hidden = this.querySelector('input[type=hidden]') as HTMLInputElement | null;
        (window as unknown as Record<string, unknown>).__hiddenName__ = hidden?.name ?? null;
      };
    });
    await submitJsfForm(page, 'col');
    const name = await page.evaluate(
      () => (window as unknown as Record<string, unknown>).__hiddenName__
    );
    expect(name).toBe('buttonForm:addC');
  });
});

// ---------------------------------------------------------------------------
// selectDataset: real browser, mock catalogue HTML, intercept navigation
// ---------------------------------------------------------------------------

// The catalogue HTML includes a dblclick handler on each label that navigates
// to tableView.xhtml — matching what the real ABS site does.
//
// NOTE: page.setContent() leaves the page at about:blank, which blocks relative
// URL navigation. We route a fake domain so that dblclick-triggered navigation
// to /tableView.xhtml resolves correctly and page.waitForURL() can match it.
const CATALOGUE_HTML = `
<html><body>
  <div class="treeNodeElement">
    <span class="treeNodeExpander leaf"></span>
    <span class="label" ondblclick="location.href='/tableView.xhtml?id=1'">Census of Population and Housing 2021</span>
  </div>
  <div class="treeNodeElement">
    <span class="treeNodeExpander leaf"></span>
    <span class="label" ondblclick="location.href='/tableView.xhtml?id=2'">Employee Earnings and Hours 2023</span>
  </div>
</body></html>`;

const MOCK_ORIGIN = 'http://abs.test';

describe('selectDataset (real browser, mock catalogue)', () => {
  it('fuzzy-matches dataset name and resolves to matched string', async () => {
    // Serve catalogue from a fake origin so relative navigation works
    await page.route(`${MOCK_ORIGIN}/catalogue`, route => route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: CATALOGUE_HTML,
    }));

    // Route the tableView URL so waitForURL resolves without a real server
    await page.route(`${MOCK_ORIGIN}/tableView.xhtml*`, route => route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: '<html><body>Table View</body></html>',
    }));

    await page.goto(`${MOCK_ORIGIN}/catalogue`);

    const result = await selectDataset(page, 'census 2021');
    expect(result).toBe('Census of Population and Housing 2021');

    await page.unroute(`${MOCK_ORIGIN}/catalogue`);
    await page.unroute(`${MOCK_ORIGIN}/tableView.xhtml*`);
  }, 20000);
});

// ---------------------------------------------------------------------------
// queueDownload: real browser, mock openTable.xhtml with a download row
// ---------------------------------------------------------------------------

import { queueDownload, _impl } from '../shared/abs/queue-downloader.js';

const MOCK_QUEUE_ORIGIN = 'http://abs.queue.test';

describe('queueDownload poll-and-capture (real browser, mock pages)', () => {
  it('finds the matching row and writes the downloaded file', async () => {
    const tmpPath = join(tmpdir(), `queue-integration-${randomUUID()}.csv`);

    // We will capture the tableName that queueDownload generates internally
    // via the fill() stub, then build the mock HTML dynamically.
    let capturedTableName = '';

    const origLocator = page.locator.bind(page);
    page.locator = (selector: string) => {
      if (
        selector === '#downloadTableModeForm' ||
        selector === '#pageForm\\:retB' ||
        selector === '#downloadTableModeForm\\:downloadTableNameTxt' ||
        selector === '#downloadTableModeForm\\:queueTableButton'
      ) {
        const stub = {
          count: async () => 1,
          click: async () => {},
          fill: async (value: string) => {
            // Capture the table name so the mock page can echo it back
            if (selector === '#downloadTableModeForm\\:downloadTableNameTxt') {
              capturedTableName = value;
            }
          },
          first: function(this: typeof stub) { return this; },
        };
        return stub as unknown as ReturnType<typeof page.locator>;
      }
      return origLocator(selector);
    };

    // Stub _impl.sleep to avoid real delays from DIALOG_WAIT_MS / SUBMIT_SETTLE_MS / POLL_INTERVAL_MS
    const origSleep = _impl.sleep;
    _impl.sleep = async () => {};

    // Redirect goto(SAVED_TABLES_URL) to our mock origin
    const origGoto = page.goto.bind(page);
    page.goto = async (url: string, opts?: Parameters<typeof page.goto>[1]) => {
      if (url.includes('openTable.xhtml')) {
        return origGoto(`${MOCK_QUEUE_ORIGIN}/openTable.xhtml`, opts);
      }
      return origGoto(url, opts);
    };

    // Serve mock saved-tables page — built dynamically after capturedTableName is set
    await page.route(`${MOCK_QUEUE_ORIGIN}/openTable.xhtml`, route => {
      const mockHtml = `
<html><body>
  <table>
    <tr>
      <td>${capturedTableName || 'placeholder'}</td>
      <td>CSV</td>
      <td>Completed, <a href="${MOCK_QUEUE_ORIGIN}/download-csv">click here to download</a></td>
    </tr>
  </table>
</body></html>`;
      return route.fulfill({ status: 200, contentType: 'text/html', body: mockHtml });
    });

    // Serve mock CSV download
    await page.route(`${MOCK_QUEUE_ORIGIN}/download-csv`, route => route.fulfill({
      status: 200,
      contentType: 'text/csv',
      headers: { 'content-disposition': 'attachment; filename="table.csv"' },
      body: 'Sex,Count\nMale,12345\nFemale,23456\n',
    }));

    try {
      await queueDownload(page, tmpPath);
      expect(existsSync(tmpPath)).toBe(true);
    } finally {
      page.locator = origLocator;
      page.goto = origGoto;
      _impl.sleep = origSleep;
      if (existsSync(tmpPath)) unlinkSync(tmpPath);
      await page.unroute(`${MOCK_QUEUE_ORIGIN}/openTable.xhtml`);
      await page.unroute(`${MOCK_QUEUE_ORIGIN}/download-csv`);
    }
  }, 30000);
});
