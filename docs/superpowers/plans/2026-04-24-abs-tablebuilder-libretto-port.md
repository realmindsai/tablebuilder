# ABS TableBuilder → Libretto Port: Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the ABS TableBuilder browser automation from Python to a typed TypeScript Libretto workflow taking `{ dataset, rows, columns, wafers? }` as input and returning a CSV file path.

**Architecture:** Thin `abs-tablebuilder.ts` workflow delegates to four helpers in `src/shared/abs/` — auth (login), jsf (JSF form submission + table retrieval), navigator (dataset/variable selection, depends on jsf), downloader (CSV download). Playwright `page` from `ctx.page` flows through each helper in sequence.

**Implementation order matters:** `jsf.ts` must be created before `navigator.ts` because navigator imports submitJsfForm from jsf.

**Tech Stack:** TypeScript 5.8, Libretto 0.6.4, playwright-core (via libretto), dotenv (NEW), vitest (NEW), playwright (NEW dev dep for tests), adm-zip (NEW)

**Source reference:** `/Users/dewoller/code/rmai/tablebuilder/src/tablebuilder/` — port logic from `config.py`, `browser.py`, `navigator.py`, `table_builder.py`, `downloader.py`, `selectors.py`

---

## Chunk 1: Project Setup

### Task 1: Install dependencies and configure vitest

**Files:**
- Modify: `package.json`
- Create: `vitest.config.ts`
- Modify: `tsconfig.json`

- [ ] **Step 1: Install runtime and dev dependencies**

```bash
cd /Users/dewoller/code/libretto-automations
npm install dotenv adm-zip
npm install --save-dev vitest playwright @types/adm-zip
```

`playwright` (full package, not `-core`) is required as a dev dep so integration and E2E tests can launch a real Chromium browser. `playwright-core` (the transitive dep from libretto) does not bundle browser binaries.

- [ ] **Step 2: Install Chromium browser binary**

```bash
npx playwright install chromium
```

Expected: downloads Chromium to local cache. Without this, `chromium.launch()` in tests throws `"Executable doesn't exist"`.

- [ ] **Step 3: Add test scripts to package.json**

Edit `package.json` scripts section — add these three entries:
```json
"test": "vitest run",
"test:watch": "vitest",
"test:e2e": "ABS_RUN_E2E=1 vitest run tests/e2e"
```

- [ ] **Step 4: Create vitest.config.ts**

```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Include unit and integration tests under src/; exclude e2e by default.
    // Run e2e separately via: npm run test:e2e
    include: ['src/**/*.test.ts'],
    exclude: ['tests/**'],
  },
});
```

- [ ] **Step 5: Update tsconfig.json**

Extend `include` to cover the tests directory. Do NOT add `rootDir` — TypeScript TS6059 fires if `rootDir` is set to `src` while `tests/**` is also included.

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist"
  },
  "include": ["src/**/*.ts", "tests/**/*.ts"]
}
```

- [ ] **Step 6: Verify vitest runs with zero tests**

```bash
npm test
```

Expected: `Test Files: 0 passed`, exits 0.

- [ ] **Step 7: Commit**

```bash
git add package.json package-lock.json tsconfig.json vitest.config.ts
git commit -m "chore: add dotenv, adm-zip, vitest, playwright; configure test runner"
```

---

### Task 2: Create directory structure and types.ts

**Files:**
- Create: `src/shared/abs/types.ts`

- [ ] **Step 1: Create types.ts**

```typescript
// src/shared/abs/types.ts

export interface Input {
  dataset: string;
  rows: string[];
  columns: string[];
  wafers?: string[];
  outputPath?: string;
}

export interface Output {
  csvPath: string;
  dataset: string;
  rowCount: number;
}

export interface Credentials {
  userId: string;
  password: string;
}

export type Axis = 'row' | 'col' | 'wafer';
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
npm run build
```

Expected: exits 0, `dist/shared/abs/types.js` exists.

- [ ] **Step 3: Commit**

```bash
git add src/shared/abs/types.ts
git commit -m "feat: add shared ABS types (Input, Output, Credentials, Axis)"
```

---

## Chunk 2: auth.ts (TDD)

### Task 3: Credential loading + login

**Files:**
- Create: `src/shared/abs/auth.test.ts`
- Create: `src/shared/abs/auth.ts`

**Source reference:** `config.py:load_config()`, `browser.py:TableBuilderSession._login()`

- [ ] **Step 1: Write failing auth unit tests**

```typescript
// src/shared/abs/auth.test.ts
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { loadCredentials } from './auth.js';

describe('loadCredentials', () => {
  const saved = {
    id: process.env.TABLEBUILDER_USER_ID,
    pw: process.env.TABLEBUILDER_PASSWORD,
  };

  beforeEach(() => {
    delete process.env.TABLEBUILDER_USER_ID;
    delete process.env.TABLEBUILDER_PASSWORD;
  });

  afterEach(() => {
    if (saved.id) process.env.TABLEBUILDER_USER_ID = saved.id;
    else delete process.env.TABLEBUILDER_USER_ID;
    if (saved.pw) process.env.TABLEBUILDER_PASSWORD = saved.pw;
    else delete process.env.TABLEBUILDER_PASSWORD;
  });

  it('returns credentials when both env vars are set', () => {
    process.env.TABLEBUILDER_USER_ID = 'testuser';
    process.env.TABLEBUILDER_PASSWORD = 'testpass';
    expect(loadCredentials()).toEqual({ userId: 'testuser', password: 'testpass' });
  });

  it('throws containing TABLEBUILDER_USER_ID when userId is missing', () => {
    process.env.TABLEBUILDER_PASSWORD = 'testpass';
    expect(() => loadCredentials()).toThrow('TABLEBUILDER_USER_ID');
  });

  it('throws containing TABLEBUILDER_PASSWORD when password is missing', () => {
    process.env.TABLEBUILDER_USER_ID = 'testuser';
    expect(() => loadCredentials()).toThrow('TABLEBUILDER_PASSWORD');
  });
});
```

- [ ] **Step 2: Run test — verify it fails**

```bash
npm test
```

Expected: FAIL — `Cannot find module './auth.js'`

- [ ] **Step 3: Implement auth.ts**

```typescript
// src/shared/abs/auth.ts
import { config } from 'dotenv';
import { homedir } from 'os';
import { join } from 'path';
import type { Page } from 'playwright-core';
import type { Credentials } from './types.js';

const ENV_PATH = join(homedir(), '.tablebuilder', '.env');
const LOGIN_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/login.xhtml';

export function loadCredentials(): Credentials {
  config({ path: ENV_PATH, override: false });
  const userId = process.env.TABLEBUILDER_USER_ID;
  const password = process.env.TABLEBUILDER_PASSWORD;
  if (!userId) {
    throw new Error('TABLEBUILDER_USER_ID not found in ~/.tablebuilder/.env or environment');
  }
  if (!password) {
    throw new Error('TABLEBUILDER_PASSWORD not found in ~/.tablebuilder/.env or environment');
  }
  return { userId, password };
}

export async function login(page: Page, creds: Credentials): Promise<void> {
  await page.goto(LOGIN_URL, { waitUntil: 'networkidle' });
  await page.fill('#loginForm\\:username2', creds.userId);
  await page.fill('#loginForm\\:password2', creds.password);
  await page.click('#loginForm\\:login2');
  await page.waitForLoadState('networkidle', { timeout: 15000 });
  if (page.url().includes('login.xhtml')) {
    throw new Error(
      'Login failed — still on login page. Check TABLEBUILDER_USER_ID and TABLEBUILDER_PASSWORD.'
    );
  }
}

export async function acceptTerms(page: Page): Promise<void> {
  if (!page.url().includes('terms.xhtml')) return;
  await page.click('#termsForm\\:termsButton');
  await page.waitForLoadState('networkidle', { timeout: 10000 });
  if (!page.url().includes('dataCatalogueExplorer.xhtml')) {
    throw new Error('Terms acceptance did not reach data catalogue. URL: ' + page.url());
  }
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
npm test
```

Expected: 3 tests pass, 0 fail.

- [ ] **Step 5: Commit**

```bash
git add src/shared/abs/auth.ts src/shared/abs/auth.test.ts
git commit -m "feat: add auth helpers (loadCredentials, login, acceptTerms)"
```

---

## Chunk 3: jsf.ts (TDD)

### Task 4: JSF form submission + table retrieval

**Files:**
- Create: `src/shared/abs/jsf.test.ts`
- Create: `src/shared/abs/jsf.ts`

**Must come before navigator.ts** — navigator imports submitJsfForm from jsf.

**Source reference:** `table_builder.py:_submit_axis_button()`, `downloader.py:_retrieve_data()`

Key insight from Python: Axis buttons (`#buttonForm:addR` etc.) do not respond to direct `.click()`. They require JSF-style form submission: append a hidden input carrying the button's `name`/`value` to the form, then call `form.submit()`. This triggers the server-side JSF action. `submitJsfForm` owns the post-submit wait — callers do not call any additional wait function.

- [ ] **Step 1: Write failing jsf unit tests**

```typescript
// src/shared/abs/jsf.test.ts
import { describe, it, expect, vi } from 'vitest';
import type { Page } from 'playwright-core';
import { submitJsfForm } from './jsf.js';

function makeMockPage(): Page {
  return {
    evaluate: vi.fn().mockResolvedValue(undefined),
    waitForLoadState: vi.fn().mockResolvedValue(undefined),
  } as unknown as Page;
}

describe('submitJsfForm', () => {
  it('calls page.evaluate once for row axis', async () => {
    const page = makeMockPage();
    await submitJsfForm(page, 'row');
    expect(page.evaluate).toHaveBeenCalledOnce();
  });

  it('passes #buttonForm\\:addR selector for row axis', async () => {
    const page = makeMockPage();
    await submitJsfForm(page, 'row');
    const [, arg] = (page.evaluate as ReturnType<typeof vi.fn>).mock.calls[0] as [unknown, string];
    expect(arg).toBe('#buttonForm\\:addR');
  });

  it('passes #buttonForm\\:addC selector for col axis', async () => {
    const page = makeMockPage();
    await submitJsfForm(page, 'col');
    const [, arg] = (page.evaluate as ReturnType<typeof vi.fn>).mock.calls[0] as [unknown, string];
    expect(arg).toBe('#buttonForm\\:addC');
  });

  it('passes #buttonForm\\:addL selector for wafer axis', async () => {
    const page = makeMockPage();
    await submitJsfForm(page, 'wafer');
    const [, arg] = (page.evaluate as ReturnType<typeof vi.fn>).mock.calls[0] as [unknown, string];
    expect(arg).toBe('#buttonForm\\:addL');
  });

  it('calls waitForLoadState after evaluate', async () => {
    const page = makeMockPage();
    await submitJsfForm(page, 'row');
    expect(page.waitForLoadState).toHaveBeenCalledWith('networkidle', { timeout: 15000 });
  });
});
```

- [ ] **Step 2: Run test — verify it fails**

```bash
npm test
```

Expected: FAIL — `Cannot find module './jsf.js'`

- [ ] **Step 3: Implement jsf.ts**

```typescript
// src/shared/abs/jsf.ts
import type { Page } from 'playwright-core';
import type { Axis } from './types.js';

const AXIS_SELECTORS: Record<Axis, string> = {
  row: '#buttonForm\\:addR',
  col: '#buttonForm\\:addC',
  wafer: '#buttonForm\\:addL',
};

// submitJsfForm owns the post-submit wait. Callers do not add extra waits.
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
    await page.waitForLoadState('networkidle', { timeout: 15000 });
  } catch {
    // Page navigated before networkidle settled — wait a fixed interval as fallback
    await new Promise(r => setTimeout(r, 5000));
  }
}

export async function retrieveTable(page: Page): Promise<void> {
  // #pageForm:retB is the Retrieve Data button — force-click past any overlay
  await page.locator('#pageForm\\:retB').click({ force: true });

  // Poll for numeric data in table cells (up to 60s)
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 2000));
    const hasData = await page.evaluate(() => {
      const cells = Array.from(document.querySelectorAll('td')).slice(0, 20);
      return cells.some(c => /^\d[\d,]*$/.test((c.textContent ?? '').trim()));
    });
    if (hasData) return;
  }
  // Not a hard failure — proceed and let downloadCsv surface any issue
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
npm test
```

Expected: 3 auth + 5 jsf = 8 tests pass, 0 fail.

- [ ] **Step 5: Commit**

```bash
git add src/shared/abs/jsf.ts src/shared/abs/jsf.test.ts
git commit -m "feat: add JSF form submission helpers (submitJsfForm, retrieveTable)"
```

---

## Chunk 4: navigator.ts (TDD)

### Task 5: Fuzzy match + dataset/variable navigation

**Files:**
- Create: `src/shared/abs/navigator.test.ts`
- Create: `src/shared/abs/navigator.ts`

**Prerequisite:** jsf.ts must exist (Task 4 complete) — navigator imports submitJsfForm from it.

**Source reference:** `navigator.py:fuzzy_match_dataset()`, `navigator.py:list_datasets()`, `navigator.py:open_dataset()`, `table_builder.py:add_variable()`, `table_builder.py:_label_matches()`, `table_builder.py:_check_variable_categories()`

- [ ] **Step 1: Write failing navigator unit tests**

`fuzzyMatchDataset` is a pure function — testable without a browser.

```typescript
// src/shared/abs/navigator.test.ts
import { describe, it, expect } from 'vitest';
import { fuzzyMatchDataset } from './navigator.js';

const AVAILABLE = [
  'Census of Population and Housing 2021',
  'Census of Population and Housing 2016',
  'Employee Earnings and Hours 2023',
];

describe('fuzzyMatchDataset', () => {
  it('exact match returns same string', () => {
    expect(fuzzyMatchDataset('Census of Population and Housing 2021', AVAILABLE))
      .toBe('Census of Population and Housing 2021');
  });

  it('case-insensitive match', () => {
    expect(fuzzyMatchDataset('census of population and housing 2021', AVAILABLE))
      .toBe('Census of Population and Housing 2021');
  });

  it('word substring match — all query words must appear', () => {
    expect(fuzzyMatchDataset('earnings hours 2023', AVAILABLE))
      .toBe('Employee Earnings and Hours 2023');
  });

  it('year-tolerant match picks dataset with closest year', () => {
    expect(fuzzyMatchDataset('census 2022', AVAILABLE))
      .toBe('Census of Population and Housing 2021');
  });

  it('throws with "No dataset matching" when no match', () => {
    expect(() => fuzzyMatchDataset('xyz nonsense', AVAILABLE))
      .toThrow('No dataset matching');
  });

  it('error message includes available dataset names', () => {
    expect(() => fuzzyMatchDataset('xyz', AVAILABLE))
      .toThrow('Census of Population');
  });
});
```

- [ ] **Step 2: Run test — verify it fails**

```bash
npm test
```

Expected: FAIL — `Cannot find module './navigator.js'`

- [ ] **Step 3: Implement navigator.ts**

```typescript
// src/shared/abs/navigator.ts
import type { Page } from 'playwright-core';
import type { Axis } from './types.js';
import { submitJsfForm } from './jsf.js';

// ---------------------------------------------------------------------------
// Fuzzy match (pure function — no browser)
// ---------------------------------------------------------------------------

export function fuzzyMatchDataset(query: string, available: string[]): string {
  const q = query.toLowerCase();

  for (const name of available) {
    if (name === query) return name;
  }
  for (const name of available) {
    if (name.toLowerCase() === q) return name;
  }

  const words = q.split(/\s+/);
  for (const name of available) {
    if (words.every(w => name.toLowerCase().includes(w))) return name;
  }

  const tokens = q.match(/\w+/g) ?? [];
  for (const name of available) {
    const nameTokenStr = (name.match(/\w+/g) ?? []).join(' ').toLowerCase();
    if (tokens.every(t => nameTokenStr.includes(t))) return name;
  }

  const nonYearTokens = tokens.filter(t => !/^\d{4}$/.test(t));
  if (nonYearTokens.length < tokens.length && nonYearTokens.length > 0) {
    const candidates = available.filter(name => {
      const nts = (name.match(/\w+/g) ?? []).join(' ').toLowerCase();
      return nonYearTokens.every(t => nts.includes(t));
    });
    if (candidates.length === 1) return candidates[0];
    if (candidates.length > 1) {
      const queryYears = tokens.filter(t => /^\d{4}$/.test(t)).map(Number);
      if (queryYears.length > 0) {
        const target = Math.max(...queryYears);
        candidates.sort((a, b) => {
          const yearsA = (a.match(/\d{4}/g) ?? []).map(Number);
          const yearsB = (b.match(/\d{4}/g) ?? []).map(Number);
          const distA = yearsA.length ? Math.min(...yearsA.map(y => Math.abs(y - target))) : 9999;
          const distB = yearsB.length ? Math.min(...yearsB.map(y => Math.abs(y - target))) : 9999;
          return distA - distB;
        });
      }
      return candidates[0];
    }
  }

  throw new Error(
    `No dataset matching '${query}'. Available datasets:\n` +
    available.map(n => `  - ${n}`).join('\n')
  );
}

// ---------------------------------------------------------------------------
// Tree helpers
// ---------------------------------------------------------------------------

async function expandAllCollapsed(page: Page): Promise<void> {
  let prevCount = -1;
  for (let round = 0; round < 50; round++) {
    const collapsed = await page.locator('.treeNodeExpander.collapsed').all();
    if (collapsed.length === 0) break;
    if (collapsed.length === prevCount) break;
    prevCount = collapsed.length;
    for (const expander of collapsed) {
      try {
        await expander.click();
        await new Promise(r => setTimeout(r, 1000));
      } catch { /* stale handle — skip */ }
    }
  }
}

async function listDatasets(page: Page): Promise<string[]> {
  await expandAllCollapsed(page);
  const nodes = await page.locator('.treeNodeElement').all();
  const names: string[] = [];
  for (const node of nodes) {
    const expander = node.locator('.treeNodeExpander').first();
    const cls = await expander.getAttribute('class').catch(() => '');
    if (cls?.includes('leaf')) {
      const text = (await node.locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
      if (text) names.push(text);
    }
  }
  return names;
}

// ---------------------------------------------------------------------------
// Dataset selection
// ---------------------------------------------------------------------------

export async function selectDataset(page: Page, dataset: string): Promise<string> {
  const available = await listDatasets(page);
  if (available.length === 0) {
    throw new Error('Dataset catalogue returned 0 datasets — session may have expired.');
  }
  const matched = fuzzyMatchDataset(dataset, available);

  const labels = await page.locator('.treeNodeElement .label').all();
  let target = null;
  for (const lbl of labels) {
    if ((await lbl.textContent())?.trim() === matched) {
      target = lbl;
      break;
    }
  }
  if (!target) {
    throw new Error(`Found '${matched}' in dataset list but cannot locate it in the UI.`);
  }

  await target.dblclick();
  await page.waitForURL('**/tableView.xhtml*', { timeout: 15000 });
  return matched;
}

// ---------------------------------------------------------------------------
// Variable selection
// ---------------------------------------------------------------------------

function labelMatches(uiText: string, varName: string): boolean {
  if (uiText === varName) return true;
  const spaceIdx = uiText.indexOf(' ');
  if (spaceIdx > 0 && uiText.slice(spaceIdx + 1) === varName) return true;
  return false;
}

function isVariableNode(labelText: string): boolean {
  // ABS variable headers look like "SEXP Sex (2)" — code prefix + digit-only count
  return /^[A-Z][A-Z0-9]{2,}\s.+\(\d+\)\s*$/.test(labelText);
}

async function searchVariable(page: Page, varName: string): Promise<void> {
  await page.fill('#searchPattern', '');
  await page.fill('#searchPattern', varName);
  const btn = page.locator('#searchButton').first();
  if (await btn.count() > 0) {
    await btn.click();
  } else {
    await page.keyboard.press('Enter');
  }
  await new Promise(r => setTimeout(r, 1000));
}

async function checkVariableCategories(page: Page, varName: string): Promise<number> {
  const nodes = await page.locator('.treeNodeElement').all();
  const nameUpper = varName.toUpperCase();

  let targetIdx = -1;
  for (let i = 0; i < nodes.length; i++) {
    const text = (await nodes[i].locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
    const cls = await nodes[i].locator('.treeNodeExpander').first().getAttribute('class').catch(() => '') ?? '';
    if ((labelMatches(text, varName) || text.toUpperCase().startsWith(nameUpper + ' ')) && !cls.includes('leaf')) {
      targetIdx = i;
      break;
    }
  }

  if (targetIdx < 0) throw new Error(`Variable '${varName}' not found in tree.`);

  let checked = 0;
  for (let i = targetIdx + 1; i < nodes.length; i++) {
    const cls = await nodes[i].locator('.treeNodeExpander').first().getAttribute('class').catch(() => '') ?? '';
    if (cls.includes('leaf')) {
      const cb = nodes[i].locator('input[type=checkbox]').first();
      if (await cb.count() > 0 && !(await cb.isChecked())) {
        await cb.click();
        await new Promise(r => setTimeout(r, 200));
      }
      if (await cb.count() > 0) checked++;
    } else {
      const text = (await nodes[i].locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
      if (isVariableNode(text)) break;
    }
  }

  return checked;
}

export async function selectVariables(
  page: Page,
  vars: { rows: string[]; columns: string[]; wafers?: string[] }
): Promise<void> {
  const assignments: Array<{ name: string; axis: Axis }> = [
    ...vars.rows.map(n => ({ name: n, axis: 'row' as Axis })),
    ...vars.columns.map(n => ({ name: n, axis: 'col' as Axis })),
    ...(vars.wafers ?? []).map(n => ({ name: n, axis: 'wafer' as Axis })),
  ];

  for (const { name, axis } of assignments) {
    await searchVariable(page, name);
    await expandAllCollapsed(page);
    await new Promise(r => setTimeout(r, 500));

    const checked = await checkVariableCategories(page, name);
    if (checked === 0) throw new Error(`No categories found for variable '${name}'.`);

    await new Promise(r => setTimeout(r, 300));
    // submitJsfForm owns the post-submit networkidle wait — no extra wait here
    await submitJsfForm(page, axis);

    const bodyText = await page.evaluate(() => document.body.innerText.substring(0, 500));
    if (bodyText.includes('Your table is empty')) {
      throw new Error(`Failed to add '${name}' to ${axis} — table still empty after submission.`);
    }
  }
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
npm test
```

Expected: 3 auth + 5 jsf + 6 navigator = 14 tests pass, 0 fail.

- [ ] **Step 5: Commit**

```bash
git add src/shared/abs/navigator.ts src/shared/abs/navigator.test.ts
git commit -m "feat: add navigator helpers (fuzzyMatchDataset, selectDataset, selectVariables)"
```

---

## Chunk 5: downloader.ts + workflow orchestrator

### Task 6: CSV downloader

**Files:**
- Create: `src/shared/abs/downloader.ts`

**Source reference:** `downloader.py:queue_and_download()`, `downloader.py:_save_download()`

No unit test for downloader — the download-intercept path requires a real browser event. Coverage is in the integration test (Task 8). The large-table error path is explicitly specified: throw with a clear message, do not queue.

- [ ] **Step 1: Implement downloader.ts**

```typescript
// src/shared/abs/downloader.ts
import { mkdir, writeFile, readFile } from 'fs/promises';
import { dirname, join } from 'path';
import { tmpdir } from 'os';
import { randomUUID } from 'crypto';
import AdmZip from 'adm-zip';
import type { Page } from 'playwright-core';

function defaultOutputPath(): string {
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  return join('output', `abs-tablebuilder-${ts}.csv`);
}

async function ensureDir(filePath: string): Promise<void> {
  await mkdir(dirname(filePath), { recursive: true });
}

async function extractCsvFromZip(zipPath: string, outputPath: string): Promise<void> {
  const zip = new AdmZip(zipPath);
  const entry = zip.getEntries().find(e => e.entryName.endsWith('.csv'));
  if (!entry) throw new Error('Downloaded ZIP contains no CSV file.');
  const csvBytes = zip.readFile(entry);
  if (!csvBytes) throw new Error('Failed to read CSV from ZIP.');
  await ensureDir(outputPath);
  await writeFile(outputPath, csvBytes);
}

function countCsvRows(csv: string): number {
  const lines = csv.split('\n').filter(l => l.trim().length > 0);
  return Math.max(0, lines.length - 1); // subtract header row
}

const DOWNLOAD_BTN_SELECTORS = [
  '#downloadControl\\:downloadButton',
  'input[value="Download table"]',
  'a[title="Download table"]',
];

export async function downloadCsv(
  page: Page,
  outputPath?: string
): Promise<{ csvPath: string; rowCount: number }> {
  const resolvedPath = outputPath ?? defaultOutputPath();
  await ensureDir(resolvedPath);

  await page.selectOption('#downloadControl\\:downloadType', 'CSV');
  await new Promise(r => setTimeout(r, 500));

  let downloadBtn = null;
  for (const sel of DOWNLOAD_BTN_SELECTORS) {
    const el = page.locator(sel).first();
    if (await el.count() > 0) {
      downloadBtn = el;
      break;
    }
  }

  if (!downloadBtn) {
    throw new Error(
      'Table too large for direct download — queue-based download not supported in this version.'
    );
  }

  const tmpPath = join(tmpdir(), `abs-download-${randomUUID()}`);

  try {
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 60000 }),
      downloadBtn.click({ force: true }),
    ]);
    await download.saveAs(tmpPath);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.toLowerCase().includes('timeout')) {
      throw new Error(
        'Table too large for direct download — queue-based download not supported in this version.'
      );
    }
    throw err;
  }

  const fileBuffer = await readFile(tmpPath);
  const isZip = fileBuffer[0] === 0x50 && fileBuffer[1] === 0x4b; // PK magic bytes

  if (isZip) {
    await extractCsvFromZip(tmpPath, resolvedPath);
  } else {
    await ensureDir(resolvedPath);
    await writeFile(resolvedPath, fileBuffer);
  }

  const content = await readFile(resolvedPath, 'utf-8');
  return { csvPath: resolvedPath, rowCount: countCsvRows(content) };
}
```

- [ ] **Step 2: Build to verify no TypeScript errors**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 3: Commit**

```bash
git add src/shared/abs/downloader.ts
git commit -m "feat: add CSV downloader (downloadCsv with ZIP extraction, large-table error)"
```

---

### Task 7: Workflow orchestrator

**Files:**
- Create: `src/workflows/abs-tablebuilder.ts`

- [ ] **Step 1: Verify LibrettoWorkflowContext is exported by libretto**

```bash
grep -r "LibrettoWorkflowContext" node_modules/libretto/dist/ | head -5
```

If the type is not found, check what the existing `rosanna-3br-apartments.ts` imports and use the same pattern.

- [ ] **Step 2: Implement the workflow orchestrator**

```typescript
// src/workflows/abs-tablebuilder.ts
import { workflow, type LibrettoWorkflowContext } from 'libretto';
import { loadCredentials, login, acceptTerms } from '../shared/abs/auth.js';
import { selectDataset, selectVariables } from '../shared/abs/navigator.js';
import { retrieveTable } from '../shared/abs/jsf.js';
import { downloadCsv } from '../shared/abs/downloader.js';
import type { Input, Output } from '../shared/abs/types.js';

export default workflow<Input, Output>(
  'abs-tablebuilder',
  async (ctx: LibrettoWorkflowContext, input): Promise<Output> => {
    const { page } = ctx;

    const creds = loadCredentials();
    await login(page, creds);
    await acceptTerms(page);

    const resolvedDataset = await selectDataset(page, input.dataset);
    await selectVariables(page, {
      rows: input.rows,
      columns: input.columns,
      wafers: input.wafers,
    });

    await retrieveTable(page);
    const { csvPath, rowCount } = await downloadCsv(page, input.outputPath);

    return { csvPath, dataset: resolvedDataset, rowCount };
  }
);
```

- [ ] **Step 3: Build to verify no TypeScript errors**

```bash
npm run build
```

Expected: exits 0, `dist/workflows/abs-tablebuilder.js` exists.

- [ ] **Step 4: Commit**

```bash
git add src/workflows/abs-tablebuilder.ts
git commit -m "feat: add abs-tablebuilder Libretto workflow orchestrator"
```

---

## Chunk 6: Integration + E2E Tests

### Task 8: Integration test (real browser, mock HTML)

**Files:**
- Create: `src/workflows/abs-tablebuilder.test.ts`

Strategy: launch real Playwright Chromium via `playwright` dev dep, set mock HTML with `page.setContent()`, and test the two most complex helpers — `submitJsfForm` (JSF hidden input injection) and `selectDataset` (fuzzy match + dblclick). For `selectDataset`, we mock the URL navigation using `page.route` so `waitForURL` resolves without a real ABS server.

- [ ] **Step 1: Write the integration test**

```typescript
// src/workflows/abs-tablebuilder.test.ts
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { chromium, type Browser, type Page } from 'playwright';
import { selectDataset } from '../shared/abs/navigator.js';
import { submitJsfForm } from '../shared/abs/jsf.js';

let browser: Browser;
let page: Page;

beforeAll(async () => {
  browser = await chromium.launch({ headless: true });
  page = await browser.newPage();
});

afterAll(async () => {
  await browser.close();
});

// ---------------------------------------------------------------------------
// submitJsfForm: real browser, mock HTML, intercept form submit
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

    // Intercept the form submit so the page doesn't navigate
    await page.evaluate(() => {
      const form = document.getElementById('buttonForm') as HTMLFormElement;
      form.addEventListener('submit', e => {
        e.preventDefault();
        const hidden = form.querySelector('input[type=hidden]') as HTMLInputElement | null;
        (window as Record<string, unknown>).__hiddenName__ = hidden?.name ?? null;
        (window as Record<string, unknown>).__submitted__ = true;
      });
    });

    await submitJsfForm(page, 'row');

    const submitted = await page.evaluate(
      () => (window as Record<string, unknown>).__submitted__
    );
    const hiddenName = await page.evaluate(
      () => (window as Record<string, unknown>).__hiddenName__
    );

    expect(submitted).toBe(true);
    expect(hiddenName).toBe('buttonForm:addR');
  });

  it('col axis injects buttonForm:addC', async () => {
    await page.setContent(TABLE_VIEW_HTML);
    await page.evaluate(() => {
      const form = document.getElementById('buttonForm') as HTMLFormElement;
      form.addEventListener('submit', e => {
        e.preventDefault();
        const hidden = form.querySelector('input[type=hidden]') as HTMLInputElement | null;
        (window as Record<string, unknown>).__hiddenName__ = hidden?.name ?? null;
      });
    });
    await submitJsfForm(page, 'col');
    const name = await page.evaluate(
      () => (window as Record<string, unknown>).__hiddenName__
    );
    expect(name).toBe('buttonForm:addC');
  });
});

// ---------------------------------------------------------------------------
// selectDataset: real browser, mock catalogue HTML, intercept navigation
// ---------------------------------------------------------------------------

const CATALOGUE_HTML = `
<html><body>
  <div class="treeNodeElement">
    <span class="treeNodeExpander leaf"></span>
    <span class="label">Census of Population and Housing 2021</span>
  </div>
  <div class="treeNodeElement">
    <span class="treeNodeExpander leaf"></span>
    <span class="label">Employee Earnings and Hours 2023</span>
  </div>
</body></html>`;

describe('selectDataset (real browser, mock catalogue)', () => {
  it('fuzzy-matches dataset name and resolves to matched string', async () => {
    await page.setContent(CATALOGUE_HTML);

    // Route the tableView URL so waitForURL resolves without a real server
    await page.route('**/tableView.xhtml*', route => route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: '<html><body>Table View</body></html>',
    }));

    const result = await selectDataset(page, 'census 2021');
    expect(result).toBe('Census of Population and Housing 2021');

    await page.unroute('**/tableView.xhtml*');
  });
});
```

- [ ] **Step 2: Run tests — verify they pass**

```bash
npm test
```

Expected: 14 previous + 3 new integration = 17 tests pass, 0 fail.

- [ ] **Step 3: Commit**

```bash
git add src/workflows/abs-tablebuilder.test.ts
git commit -m "test: add integration tests with real browser for submitJsfForm and selectDataset"
```

---

### Task 9: E2E test scaffold

**Files:**
- Create: `tests/e2e/abs-tablebuilder.e2e.ts`

- [ ] **Step 1: Write E2E test (skipped by default)**

```typescript
// tests/e2e/abs-tablebuilder.e2e.ts
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { chromium, type Browser, type Page } from 'playwright';
import { existsSync, unlinkSync, readFileSync } from 'fs';
import { join } from 'path';
import { loadCredentials, login, acceptTerms } from '../../src/shared/abs/auth.js';
import { selectDataset, selectVariables } from '../../src/shared/abs/navigator.js';
import { retrieveTable } from '../../src/shared/abs/jsf.js';
import { downloadCsv } from '../../src/shared/abs/downloader.js';

const RUN_E2E = process.env.ABS_RUN_E2E === '1';

describe.skipIf(!RUN_E2E)('ABS TableBuilder E2E', () => {
  let browser: Browser;
  let page: Page;
  const OUTPUT_PATH = join('output', 'e2e-test-result.csv');

  beforeAll(async () => {
    browser = await chromium.launch({ headless: true });
    page = await browser.newPage();
  });

  afterAll(async () => {
    await browser.close();
    if (existsSync(OUTPUT_PATH)) unlinkSync(OUTPUT_PATH);
  });

  it('fetches a Census 2021 table and downloads it as CSV', async () => {
    const creds = loadCredentials();
    await login(page, creds);
    await acceptTerms(page);

    const dataset = await selectDataset(page, 'Census 2021');
    expect(dataset).toContain('2021');

    await selectVariables(page, {
      rows: ['Sex'],
      columns: ['Age'],
    });

    await retrieveTable(page);
    const { csvPath, rowCount } = await downloadCsv(page, OUTPUT_PATH);

    expect(existsSync(csvPath)).toBe(true);
    expect(rowCount).toBeGreaterThan(0);
    expect(readFileSync(csvPath, 'utf-8')).toContain('Male');
  }, 300_000); // 5-minute timeout for live ABS site
});
```

- [ ] **Step 2: Run normal tests — verify E2E suite is skipped, not failed**

```bash
npm test
```

Expected: 17 tests pass, E2E suite shows as skipped (0 failed).

- [ ] **Step 3: Final build check**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/abs-tablebuilder.e2e.ts
git commit -m "test: add E2E test scaffold (skipped unless ABS_RUN_E2E=1)"
```

---

## Running the Workflow

```bash
npx libretto run src/workflows/abs-tablebuilder.ts \
  --params '{"dataset":"Census 2021","rows":["Sex"],"columns":["Age"]}'
```

E2E test against live ABS:

```bash
ABS_RUN_E2E=1 npm run test:e2e
```
