# ABS Queue-Based Download Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a queue-based download step between direct download and DOM extraction in `downloadCsv`, producing the actual full ABS-generated CSV for tables that don't support direct Playwright download.

**Architecture:** `trySaveViaResponse` moves to a new shared `response-capture.ts` to avoid a circular import between `downloader.ts` and `queue-downloader.ts`. `queue-downloader.ts` exports one function (`queueDownload`) and a testability shim (`_impl`). `downloader.ts` calls `queueDownload` in its fallback chain. Unit tests mock `page` with `_impl.sleep` replacement. One new integration test uses real Playwright + mock HTML.

**Tech Stack:** TypeScript 5.8, Playwright (via `playwright` dev dep), vitest

**Spec:** `docs/superpowers/specs/2026-04-24-abs-queue-download-design.md`

---

## Chunk 1: Prep — extract `trySaveViaResponse` and clean up `downloader.ts`

### Task 1: Create `response-capture.ts`, update `downloader.ts`

**Files:**
- Create: `src/shared/abs/response-capture.ts`
- Modify: `src/shared/abs/downloader.ts`

`trySaveViaResponse` currently lives in `downloader.ts`. `queue-downloader.ts` needs it, but `downloader.ts` will also import `queueDownload` from `queue-downloader.ts` — creating a circular dependency. Breaking the cycle: move `trySaveViaResponse` to its own file that both modules import.

- [ ] **Step 1: Create `response-capture.ts`**

Create `src/shared/abs/response-capture.ts` with this exact content:

```typescript
// src/shared/abs/response-capture.ts
import { writeFile } from 'fs/promises';
import type { Page } from 'playwright-core';

export async function trySaveViaResponse(
  page: Page,
  clickFn: () => Promise<void>,
  tmpPath: string,
  waitMs = 15000,
): Promise<boolean> {
  return new Promise<boolean>(async (resolve) => {
    let saved = false;

    const responseHandler = async (response: {
      headers: () => Record<string, string>;
      body: () => Promise<Buffer>;
      url: () => string;
    }) => {
      if (saved) return;
      const headers = response.headers();
      const disp = headers['content-disposition'] ?? '';
      const type = headers['content-type'] ?? '';
      if (disp.includes('attachment') || type.includes('csv') || type.includes('zip') || type.includes('excel')) {
        try {
          const body = await response.body();
          await writeFile(tmpPath, body);
          saved = true;
          console.log(`trySaveViaResponse: captured response, content-type=${type}, size=${body.length}`);
          resolve(true);
        } catch { /* ignore */ }
      }
    };

    page.on('response', responseHandler);

    const dlPromise = page.waitForEvent('download', { timeout: waitMs })
      .then(async dl => {
        if (!saved) {
          await dl.saveAs(tmpPath);
          saved = true;
          console.log('trySaveViaResponse: captured via download event');
          resolve(true);
        }
      })
      .catch(() => { /* timeout */ });

    await clickFn();
    await dlPromise;

    await new Promise(r => setTimeout(r, 2000));
    page.off('response', responseHandler);
    if (!saved) resolve(false);
  });
}
```

- [ ] **Step 2: Update `downloader.ts` to import from `response-capture.ts`**

In `src/shared/abs/downloader.ts`:

a) **Remove** the entire `trySaveViaResponse` function (lines 41–84 in the current file — the `async function trySaveViaResponse(...)` block).

b) **Remove** `const SAVED_TABLES_URL = ...` (line 9 — no longer used in this file).

c) **Add** this import at the top (after existing imports):
```typescript
import { trySaveViaResponse } from './response-capture.js';
```

The `saveDownload` function on line 86 already calls `trySaveViaResponse` — this call continues to work via the new import. No other changes needed in `downloader.ts` for this step.

- [ ] **Step 3: Run tests — verify 17 still pass**

```bash
npm test
```

Expected: 17 tests pass, 0 fail.

- [ ] **Step 4: Build passes**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 5: Commit**

```bash
git add src/shared/abs/response-capture.ts src/shared/abs/downloader.ts
git commit -m "refactor: extract trySaveViaResponse to response-capture.ts, remove SAVED_TABLES_URL from downloader"
```

---

## Chunk 2: `queue-downloader.ts` (TDD)

### Task 2: Write failing unit tests

**Files:**
- Create: `src/shared/abs/queue-downloader.test.ts`

Tests drive through `queueDownload` with carefully mocked pages. The `_impl` object (exported from `queue-downloader.ts`) is used to replace `sleep` so the 10-minute poll loop can be exercised without real delays.

- [ ] **Step 1: Create `queue-downloader.test.ts`**

```typescript
// src/shared/abs/queue-downloader.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Page } from 'playwright-core';
import { queueDownload, _impl } from './queue-downloader.js';

// ─── mock helpers ────────────────────────────────────────────────────────────

function makeLocator(count = 1) {
  const loc = {
    count: vi.fn().mockResolvedValue(count),
    click: vi.fn().mockResolvedValue(undefined),
    fill: vi.fn().mockResolvedValue(undefined),
    first: vi.fn().mockReturnThis() as () => typeof loc,
  };
  return loc;
}

function makePage(opts: {
  dialogAppearsOnAttempt?: number; // 1 = first retB click, 2 = second click
  nameInputExists?: boolean;
  submitExists?: boolean;
  pollRowFound?: boolean;
} = {}): Page {
  const {
    dialogAppearsOnAttempt = 1,
    nameInputExists = true,
    submitExists = true,
    pollRowFound = true,
  } = opts;

  let clickCount = 0;

  return {
    locator: vi.fn().mockImplementation((selector: string) => {
      if (selector === '#pageForm\\:retB') {
        const loc = makeLocator(1);
        loc.click = vi.fn().mockImplementation(async () => { clickCount++; }) as typeof loc.click;
        return loc;
      }
      if (selector === '#downloadTableModeForm\\:downloadTableNameTxt') {
        return makeLocator(nameInputExists && clickCount >= dialogAppearsOnAttempt ? 1 : 0);
      }
      if (selector === '#downloadTableModeForm\\:queueTableButton') {
        return makeLocator(submitExists ? 1 : 0);
      }
      return makeLocator(1);
    }),
    evaluate: vi.fn().mockImplementation(async (_fn: unknown, args?: unknown) => {
      if (args && typeof args === 'object' && 'name' in (args as object)) {
        return { found: pollRowFound };
      }
      return undefined;
    }),
    goto: vi.fn().mockResolvedValue(undefined),
    reload: vi.fn().mockResolvedValue(undefined),
    on: vi.fn(),
    off: vi.fn(),
    waitForEvent: vi.fn().mockRejectedValue(new Error('timeout')),
  } as unknown as Page;
}

// ─── tests ───────────────────────────────────────────────────────────────────

describe('openQueueDialog — retry logic', () => {
  it('succeeds on first attempt when dialog opens immediately', async () => {
    const page = makePage({ dialogAppearsOnAttempt: 1, pollRowFound: true });
    await expect(queueDownload(page, '/tmp/test.csv')).resolves.toBeUndefined();
  });

  it('retries once when dialog does not open on first click', async () => {
    const page = makePage({ dialogAppearsOnAttempt: 2, pollRowFound: true });
    await expect(queueDownload(page, '/tmp/test.csv')).resolves.toBeUndefined();
  });

  it('throws after two failed attempts', async () => {
    const page = makePage({ dialogAppearsOnAttempt: 99, pollRowFound: false });
    await expect(queueDownload(page, '/tmp/test.csv')).rejects.toThrow(
      'Queue dialog did not open — cannot submit table to queue',
    );
  });
});

describe('fillAndSubmit — selector checks', () => {
  it('throws when name input is not found', async () => {
    const page = makePage({ dialogAppearsOnAttempt: 1, nameInputExists: false });
    await expect(queueDownload(page, '/tmp/test.csv')).rejects.toThrow(
      'Queue dialog name input (#downloadTableModeForm:downloadTableNameTxt) not found',
    );
  });

  it('throws when submit button is not found', async () => {
    const page = makePage({ dialogAppearsOnAttempt: 1, nameInputExists: true, submitExists: false });
    await expect(queueDownload(page, '/tmp/test.csv')).rejects.toThrow(
      'Queue dialog submit button (#downloadTableModeForm:queueTableButton) not found',
    );
  });
});

describe('pollForDownload — deadline', () => {
  let origSleep: typeof _impl.sleep;

  beforeEach(() => {
    origSleep = _impl.sleep;
    // Replace sleep to advance Date.now() without real delays.
    // Each call to _impl.sleep advances the clock by POLL_INTERVAL_MS (5000ms).
    let elapsed = 0;
    _impl.sleep = async (ms: number) => {
      elapsed += ms;
      vi.setSystemTime(Date.now() + ms);
    };
    vi.useFakeTimers({ now: Date.now() });
  });

  afterEach(() => {
    _impl.sleep = origSleep;
    vi.useRealTimers();
  });

  it('throws after 10-minute deadline with correct message', async () => {
    const page = makePage({ pollRowFound: false });
    await expect(queueDownload(page, '/tmp/test.csv')).rejects.toThrow(
      'Queue table did not complete within 10 minutes',
    );
  });
});
```

- [ ] **Step 2: Run — verify it fails**

```bash
npm test
```

Expected: FAIL — `Cannot find module './queue-downloader.js'`

- [ ] **Step 3: Commit the failing tests**

```bash
git add src/shared/abs/queue-downloader.test.ts
git commit -m "test: add failing unit tests for queue-downloader"
```

---

### Task 3: Implement `queue-downloader.ts`

**Files:**
- Create: `src/shared/abs/queue-downloader.ts`

Imports `trySaveViaResponse` from `./response-capture.js` (NOT from `./downloader.js`) — this avoids the circular dependency (`downloader.ts` will import `queueDownload` from this file in Task 4).

- [ ] **Step 1: Create `queue-downloader.ts`**

```typescript
// src/shared/abs/queue-downloader.ts
import type { Page } from 'playwright-core';
import { trySaveViaResponse } from './response-capture.js';

// ─── constants ───────────────────────────────────────────────────────────────

const SAVED_TABLES_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/tableView/openTable.xhtml';
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
    if (await page.locator(QUEUE_DIALOG_SELECTOR).count() > 0) return;
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
      const saved = await trySaveViaResponse(
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
      if (saved) return;
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
```

- [ ] **Step 2: Run tests — verify they pass**

```bash
npm test
```

Expected: 17 (existing) + 6 (queue unit tests) = 23 tests pass, 0 fail.

- [ ] **Step 3: Build passes**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add src/shared/abs/queue-downloader.ts
git commit -m "feat: add queue-downloader (openQueueDialog, fillAndSubmit, pollForDownload)"
```

---

## Chunk 3: Wire into `downloadCsv` + integration test

### Task 4: Update `downloadCsv` fallback chain

**Files:**
- Modify: `src/shared/abs/downloader.ts`

Insert `queueDownload` between direct download and DOM extraction. No circular import because `trySaveViaResponse` was already moved to `response-capture.ts` in Task 1.

- [ ] **Step 1: Add import to `downloader.ts`**

Add after the existing imports in `src/shared/abs/downloader.ts`:

```typescript
import { queueDownload } from './queue-downloader.js';
```

- [ ] **Step 2: Replace the fallback block in `downloadCsv`**

Find this block (the `if (!directSuccess)` section, currently ending at the `return` inside it):

```typescript
  if (!directSuccess) {
    // Direct download didn't fire — fall back to reading the table directly from the page DOM
    // This is the most reliable approach for ABS TableBuilder which uses JSF AJAX downloads
    const domSuccess = await readTableFromDom(page, resolvedPath);
    if (!domSuccess) {
      throw new Error('Could not download table: direct download and DOM extraction both failed.');
    }
    const content = await readFile(resolvedPath, 'utf-8');
    return { csvPath: resolvedPath, rowCount: countCsvRows(content) };
  }
```

Replace with:

```typescript
  if (!directSuccess) {
    // 2. Queue-based download — submit to ABS server queue, poll, download the completed file
    try {
      await queueDownload(page, tmpPath);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.log(`downloadCsv: queue download failed (${msg}), trying DOM extraction`);

      // 3. DOM extraction — last resort, reads whatever is rendered on the page
      const domSuccess = await readTableFromDom(page, resolvedPath);
      if (!domSuccess) {
        throw new Error('Could not download table: all methods failed.');
      }
      const content = await readFile(resolvedPath, 'utf-8');
      return { csvPath: resolvedPath, rowCount: countCsvRows(content) };
    }
  }
```

- [ ] **Step 3: Run tests — verify 23 still pass**

```bash
npm test
```

Expected: 23 tests pass, 0 fail.

- [ ] **Step 4: Build passes**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 5: Commit**

```bash
git add src/shared/abs/downloader.ts
git commit -m "feat: wire queueDownload into downloadCsv fallback chain"
```

---

### Task 5: Integration test — poll-and-capture with real browser

**Files:**
- Modify: `src/workflows/abs-tablebuilder.test.ts`

- [ ] **Step 1: Append the integration test**

Add to the end of `src/workflows/abs-tablebuilder.test.ts`:

```typescript
// ---------------------------------------------------------------------------
// queueDownload: real browser, mock openTable.xhtml with a download row
// ---------------------------------------------------------------------------

import { queueDownload } from '../shared/abs/queue-downloader.js';
import { existsSync, unlinkSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';
import { randomUUID } from 'crypto';

const MOCK_QUEUE_ORIGIN = 'http://abs.queue.test';
const QUEUE_TABLE_NAME = `abs_q_integration_${Date.now()}`;

// Mock saved-tables page with one matching row whose download link returns CSV.
const OPEN_TABLE_HTML = `
<html><body>
  <table>
    <tr>
      <td>${QUEUE_TABLE_NAME}</td>
      <td>CSV</td>
      <td>Completed, <a href="${MOCK_QUEUE_ORIGIN}/download-csv">click here to download</a></td>
    </tr>
  </table>
</body></html>`;

describe('queueDownload poll-and-capture (real browser, mock pages)', () => {
  it('finds the matching row and writes the downloaded file', async () => {
    const tmpPath = join(tmpdir(), `queue-integration-${randomUUID()}.csv`);

    // Serve mock saved-tables and download endpoints
    await page.route(`${MOCK_QUEUE_ORIGIN}/openTable.xhtml`, route => route.fulfill({
      status: 200, contentType: 'text/html', body: OPEN_TABLE_HTML,
    }));
    await page.route(`${MOCK_QUEUE_ORIGIN}/download-csv`, route => route.fulfill({
      status: 200,
      contentType: 'text/csv',
      headers: { 'content-disposition': 'attachment; filename="table.csv"' },
      body: 'Sex,Count\nMale,12345\nFemale,23456\n',
    }));

    // Stub the three dialog locators so openQueueDialog + fillAndSubmit succeed
    // without a real ABS dialog. These stubs implement only what queue-downloader
    // actually calls (count, click, fill, first). Intentional cast — Playwright
    // Locator has ~40 methods; we only need four.
    const origLocator = page.locator.bind(page);
    page.locator = (selector: string) => {
      if (
        selector === '#pageForm\\:retB' ||
        selector === '#downloadTableModeForm\\:downloadTableNameTxt' ||
        selector === '#downloadTableModeForm\\:queueTableButton'
      ) {
        const stub = {
          count: async () => 1,
          click: async () => {},
          fill: async () => {},
          first: function(this: typeof stub) { return this; },
        };
        return stub as unknown as ReturnType<typeof page.locator>;
      }
      return origLocator(selector);
    };

    // Redirect goto(SAVED_TABLES_URL) to our mock origin
    const origGoto = page.goto.bind(page);
    page.goto = async (url: string, opts?: Parameters<typeof page.goto>[1]) => {
      if (url.includes('openTable.xhtml')) {
        return origGoto(`${MOCK_QUEUE_ORIGIN}/openTable.xhtml`, opts);
      }
      return origGoto(url, opts);
    };

    try {
      await queueDownload(page, tmpPath);
      expect(existsSync(tmpPath)).toBe(true);
    } finally {
      page.locator = origLocator;
      page.goto = origGoto;
      if (existsSync(tmpPath)) unlinkSync(tmpPath);
      await page.unroute(`${MOCK_QUEUE_ORIGIN}/openTable.xhtml`);
      await page.unroute(`${MOCK_QUEUE_ORIGIN}/download-csv`);
    }
  }, 30000);
});
```

- [ ] **Step 2: Run tests — verify 24 total pass**

```bash
npm test
```

Expected: 17 (original) + 6 (queue unit tests) + 1 (this integration test) = 24 tests pass.

- [ ] **Step 3: Build passes**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add src/workflows/abs-tablebuilder.test.ts
git commit -m "test: add integration test for queueDownload poll-and-capture with mock browser"
```

---

## Final Verification

- [ ] **Full test suite**

```bash
npm test
```

Expected: 24 tests pass, 0 fail, no warnings.

- [ ] **Clean git log**

```bash
git log --oneline -6
```

Expected commits on top of the existing history:
```
<hash> test: add integration test for queueDownload poll-and-capture with mock browser
<hash> feat: wire queueDownload into downloadCsv fallback chain
<hash> feat: add queue-downloader (openQueueDialog, fillAndSubmit, pollForDownload)
<hash> test: add failing unit tests for queue-downloader
<hash> refactor: extract trySaveViaResponse to response-capture.ts, remove SAVED_TABLES_URL from downloader
```
