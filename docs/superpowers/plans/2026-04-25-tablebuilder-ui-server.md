# Tablebuilder UI + Express SSE Server — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing ABS TableBuilder Playwright automation to a polished React web UI via an Express server that streams phase-by-phase progress using Server-Sent Events over a POST response body.

**Architecture:** A new `PhaseReporter` callback type is threaded through all existing helpers (auth, navigator, jsf, downloader). A new `runner.ts` extracts the orchestration so the Express server can call it directly with its own Playwright browser, while the existing Libretto workflow is unchanged in behaviour. The UI (`ui/`) is the design prototype with `useApiRunner` added alongside the existing `useRunner` simulation.

**Tech Stack:** TypeScript 5.8, Node.js ESM (`"type": "module"`), Express 4, Playwright (already installed), tsx (new dev dep), React 18 CDN (UI)

**Spec:** `docs/superpowers/specs/2026-04-25-tablebuilder-ui-server-design.md`

---

## File map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/shared/abs/reporter.ts` | PhaseReporter type, PhaseEvent union, noopReporter, NEVER_ABORT, CancelledError |
| Modify | `src/shared/abs/auth.ts` | Add reporter + signal to login/acceptTerms; emit login phase |
| Modify | `src/shared/abs/auth.test.ts` | Verify existing tests still pass after signature change |
| Modify | `src/shared/abs/navigator.ts` | Add reporter + signal; emit dataset/tree/check/submit phases |
| Modify | `src/shared/abs/navigator.test.ts` | Verify existing tests still pass |
| Modify | `src/shared/abs/jsf.ts` | Add reporter + signal to retrieveTable; emit retrieve phase |
| Modify | `src/shared/abs/jsf.test.ts` | Verify existing tests still pass |
| Modify | `src/shared/abs/downloader.ts` | Add reporter to downloadCsv; emit download phase |
| Create | `src/shared/abs/runner.ts` | `runTablebuilder(page, input, reporter, signal)` — extracted orchestration |
| Modify | `src/workflows/abs-tablebuilder.ts` | Delegate to runTablebuilder |
| Create | `src/server.ts` | Express server: static ui/, POST /api/run SSE, GET /api/health, run lock |
| Create | `src/server.test.ts` | Smoke tests: health 200, validation 400, concurrent 409 |
| Create | `ui/index.html` | Renamed from design's Tablebuilder.html |
| Create | `ui/app.jsx` | Design app.jsx + useApiRunner + applyEvent |
| Create | `ui/form.jsx` | Design form.jsx (unchanged) |
| Create | `ui/run.jsx` | Design run.jsx (unchanged) |
| Create | `ui/tweaks-panel.jsx` | Design tweaks-panel.jsx (unchanged) |
| Create | `ui/data.js` | Design data.js (unchanged) |
| Create | `ui/styles.css` | Design styles.css (unchanged) |
| Create | `ui/assets/rmai.css` | Design rmai.css (unchanged) |
| Create | `ui/assets/purple_circles_motif.svg` | Design SVG (unchanged) |

---

## Chunk 1: reporter.ts + dependencies

### Task 1: Install new dependencies

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Install express and tsx**

```bash
cd /Users/dewoller/code/libretto-automations
npm install express
npm install --save-dev @types/express tsx
```

Expected: `package.json` gains `"express"` in dependencies, `"@types/express"` and `"tsx"` in devDependencies.

- [ ] **Step 2: Add serve scripts to package.json**

Edit `package.json` scripts section — add two entries:

```json
"serve": "tsx src/server.ts",
"serve:prod": "node dist/server.js"
```

- [ ] **Step 3: Verify build still works**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: add express, @types/express, tsx; add serve scripts"
```

---

### Task 2: Create reporter.ts

**Files:**
- Create: `src/shared/abs/reporter.ts`

- [ ] **Step 1: Write reporter.ts**

```typescript
// src/shared/abs/reporter.ts

export type PhaseEvent =
  | { type: 'phase_start';    phaseId: string; phaseLabel: string; phaseSub: string }
  | { type: 'phase_complete'; phaseId: string; elapsed: number }
  | { type: 'phase_error';    phaseId: string; message: string }
  | { type: 'log';            level: 'info' | 'ok' | 'warn' | 'err' | 'phase'; message: string }
  | { type: 'complete';       result: { csvPath: string; dataset: string; rowCount: number } }
  | { type: 'error';          message: string };

export type PhaseReporter = (event: PhaseEvent) => void;

export const noopReporter: PhaseReporter = () => {};

// A signal that never aborts. Module-level singleton — one instance avoids GC-triggered abort.
const _neverAbortAC = new AbortController();
export const NEVER_ABORT: AbortSignal = _neverAbortAC.signal;

export class CancelledError extends Error {
  constructor() {
    super('Run cancelled by user');
    this.name = 'CancelledError';
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
npm run build
```

Expected: exits 0, `dist/shared/abs/reporter.js` exists.

- [ ] **Step 3: Commit**

```bash
git add src/shared/abs/reporter.ts
git commit -m "feat: add PhaseReporter type, noopReporter, NEVER_ABORT, CancelledError"
```

---

## Chunk 2: Instrument auth.ts

### Task 3: Add reporter + signal to login and acceptTerms

**Files:**
- Create: `src/shared/abs/instrumentation.test.ts` (TDD — written first)
- Modify: `src/shared/abs/auth.ts`
- Verify: `src/shared/abs/auth.test.ts` (no changes needed)

The existing `login` and `acceptTerms` functions get two new optional trailing parameters. `acceptTerms` is folded into the login phase — it does not emit its own `phase_start` / `phase_complete`.

- [ ] **Step 1: Write failing reporter tests (TDD — do this BEFORE modifying any helper)**

Create `src/shared/abs/instrumentation.test.ts`. This file accumulates reporter-event tests for all four helpers. Start with auth:

```typescript
// src/shared/abs/instrumentation.test.ts
import { describe, it, expect, vi } from 'vitest';
import type { Page } from 'playwright-core';
import type { PhaseEvent } from './reporter.js';

function collectReporter(): { events: PhaseEvent[]; reporter: (e: PhaseEvent) => void } {
  const events: PhaseEvent[] = [];
  return { events, reporter: (e) => events.push(e) };
}

// ── auth.ts ──────────────────────────────────────────────────────────────────

describe('login — reporter events', () => {
  function makeMockPage(finalUrl = 'https://tablebuilder.abs.gov.au/dataCatalogueExplorer.xhtml'): Page {
    return {
      goto: vi.fn().mockResolvedValue(null),
      fill: vi.fn().mockResolvedValue(undefined),
      click: vi.fn().mockResolvedValue(undefined),
      waitForURL: vi.fn().mockResolvedValue(undefined),
      url: vi.fn().mockReturnValue(finalUrl),
    } as unknown as Page;
  }

  it('emits phase_start login before phase_complete login', async () => {
    const { events, reporter } = collectReporter();
    const { login } = await import('./auth.js');
    await login(makeMockPage(), { userId: 'u', password: 'p' }, reporter);
    const starts = events.filter(e => e.type === 'phase_start').map(e => (e as { phaseId: string }).phaseId);
    const completes = events.filter(e => e.type === 'phase_complete').map(e => (e as { phaseId: string }).phaseId);
    expect(starts).toContain('login');
    expect(completes).toContain('login');
    expect(events.findIndex(e => e.type === 'phase_start')).toBeLessThan(events.findIndex(e => e.type === 'phase_complete'));
  });
});
```

- [ ] **Step 2: Run test — verify it fails**

```bash
npm test -- src/shared/abs/instrumentation.test.ts
```

Expected: FAIL — login emits no events (reporter parameter doesn't exist yet).

- [ ] **Step 3: Modify auth.ts**

Replace the entire file content:

```typescript
// src/shared/abs/auth.ts
import { config } from 'dotenv';
import { homedir } from 'os';
import { join } from 'path';
import type { Page } from 'playwright-core';
import type { Credentials } from './types.js';
import { noopReporter, NEVER_ABORT, CancelledError, type PhaseReporter } from './reporter.js';

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

export async function login(
  page: Page,
  creds: Credentials,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<void> {
  const t0 = Date.now();
  reporter({ type: 'phase_start', phaseId: 'login', phaseLabel: 'Logging in', phaseSub: 'auth · tablebuilder.abs.gov.au' });
  reporter({ type: 'log', level: 'phase', message: '» phase 1/7 — Logging in' });
  reporter({ type: 'log', level: 'info', message: '  connecting to tablebuilder.abs.gov.au...' });

  if (signal.aborted) throw new CancelledError();

  // JSF apps have long-polling — 'load' is more reliable than 'networkidle'
  await page.goto(LOGIN_URL, { waitUntil: 'load' });
  await page.fill('#loginForm\\:username2', creds.userId);
  await page.fill('#loginForm\\:password2', creds.password);
  await page.click('#loginForm\\:login2');
  await page.waitForURL(url => !url.href.includes('login.xhtml'), { timeout: 15000 });
  if (page.url().includes('login.xhtml')) {
    throw new Error(
      'Login failed — still on login page. Check TABLEBUILDER_USER_ID and TABLEBUILDER_PASSWORD.'
    );
  }

  reporter({ type: 'log', level: 'info', message: '  ✓ session cookie set · user=analyst' });

  // acceptTerms is part of login phase — no separate phase emitted
  await acceptTerms(page, reporter);

  reporter({ type: 'phase_complete', phaseId: 'login', elapsed: (Date.now() - t0) / 1000 });
}

export async function acceptTerms(page: Page, reporter: PhaseReporter = noopReporter): Promise<void> {
  if (!page.url().includes('terms.xhtml')) return;
  reporter({ type: 'log', level: 'info', message: '  accepting terms of use...' });
  await page.click('#termsForm\\:termsButton');
  await page.waitForURL(url => !url.href.includes('terms.xhtml'), { timeout: 10000 });
  if (!page.url().includes('dataCatalogueExplorer.xhtml')) {
    throw new Error('Terms acceptance did not reach data catalogue. URL: ' + page.url());
  }
  reporter({ type: 'log', level: 'ok', message: '  ✓ terms accepted' });
}
```

- [ ] **Step 2: Run tests — verify auth tests still pass**

```bash
npm test
```

Expected: all existing auth tests pass. The `login` and `acceptTerms` call sites in tests pass no reporter/signal — defaults apply.

- [ ] **Step 3: Commit**

```bash
git add src/shared/abs/auth.ts
git commit -m "feat: instrument auth.ts — emit login phase events, accept reporter + signal"
```

---

## Chunk 3: Instrument navigator.ts

### Task 4: Add reporter + signal to selectDataset and selectVariables

**Files:**
- Modify: `src/shared/abs/instrumentation.test.ts` (add navigator tests)
- Modify: `src/shared/abs/navigator.ts`
- Verify: `src/shared/abs/navigator.test.ts` (no changes needed)

- [ ] **Step 0: Add navigator reporter tests to instrumentation.test.ts (TDD — before modifying navigator.ts)**

Append to `src/shared/abs/instrumentation.test.ts`:

```typescript
// ── navigator.ts ─────────────────────────────────────────────────────────────

describe('selectDataset — reporter events', () => {
  it('emits phase_start dataset and phase_complete dataset', async () => {
    const { events, reporter } = collectReporter();
    const { selectDataset } = await import('./navigator.js');

    const DATASET_NAME = 'Census 2021 Persons Usual Residence';

    // Leaf node returned by listDatasets
    const mockLeafExpander = { getAttribute: vi.fn().mockResolvedValue('treeNodeExpander leaf') };
    const mockLeafLabelEl = { textContent: vi.fn().mockResolvedValue(DATASET_NAME) };
    const mockLeafNode = {
      locator: vi.fn().mockImplementation((sel: string) =>
        sel.includes('treeNodeExpander') ? { first: () => mockLeafExpander } : { first: () => mockLeafLabelEl }
      ),
    };

    // Target label element returned by the .treeNodeElement .label query
    const mockTargetLabel = {
      textContent: vi.fn().mockResolvedValue(DATASET_NAME),
      dblclick: vi.fn().mockResolvedValue(undefined),
    };

    const page = {
      waitForSelector: vi.fn().mockResolvedValue(null),
      waitForURL: vi.fn().mockResolvedValue(undefined),
      url: vi.fn().mockReturnValue('https://tablebuilder.abs.gov.au/tableView.xhtml'),
      evaluate: vi.fn().mockResolvedValue(null),
      locator: vi.fn().mockImplementation((sel: string) => {
        if (sel === '.treeNodeElement .label') return { all: vi.fn().mockResolvedValue([mockTargetLabel]) };
        if (sel === '.treeNodeExpander.collapsed') return { all: vi.fn().mockResolvedValue([]) }; // no collapsed nodes
        if (sel === '.treeNodeElement') return { all: vi.fn().mockResolvedValue([mockLeafNode]) };
        return { all: vi.fn().mockResolvedValue([]) };
      }),
    } as unknown as Page;

    await selectDataset(page, 'Census 2021', reporter);

    const starts = events.filter(e => e.type === 'phase_start').map(e => (e as { phaseId: string }).phaseId);
    const completes = events.filter(e => e.type === 'phase_complete').map(e => (e as { phaseId: string }).phaseId);
    expect(starts).toContain('dataset');
    expect(completes).toContain('dataset');
  });
});
```

- [ ] **Step 0b: Run test — verify it fails**

```bash
npm test -- src/shared/abs/instrumentation.test.ts
```

Expected: FAIL — `selectDataset` emits no events yet.

The key structure of `selectVariables` in the actual code is:
1. Pre-loop: wait for tree, stabilize, expand GROUP nodes via multiple rounds (this is the **tree phase**)
2. Variable loop: `checkVariableCategories` + `submitJsfForm` per variable

The three phases (tree, check, submit) are emitted as follows:
- **tree**: spans the entire pre-loop group expansion
- **check**: transitions from tree on the first variable's check; subsequent variables emit log events
- **submit**: transitions from check on the first variable's submit; completes after all submits

`expandAllCollapsed` (private, used in `listDatasets`) also gets a signal parameter.

- [ ] **Step 1: Modify navigator.ts**

Apply these changes to `src/shared/abs/navigator.ts`:

**1a. Add imports at top (after existing imports). Keep all existing imports — especially `import { submitJsfForm } from './jsf.js'` which is called inside `selectVariables`.**

```typescript
import { noopReporter, NEVER_ABORT, CancelledError, type PhaseReporter } from './reporter.js';
```

**1b. Change `expandAllCollapsed` signature to accept signal:**

```typescript
async function expandAllCollapsed(page: Page, maxMs = 30000, signal: AbortSignal = NEVER_ABORT): Promise<void> {
  const deadline = Date.now() + maxMs;
  let prevCount = -1;
  for (let round = 0; round < 50; round++) {
    if (Date.now() > deadline) break;
    if (signal.aborted) throw new CancelledError();
    const collapsed = await page.locator('.treeNodeExpander.collapsed').all();
    if (collapsed.length === 0) break;
    if (collapsed.length === prevCount) break;
    prevCount = collapsed.length;
    console.log(`expandAllCollapsed: round ${round}, ${collapsed.length} nodes`);
    for (const expander of collapsed) {
      if (Date.now() > deadline) break;
      if (signal.aborted) throw new CancelledError();
      try {
        await expander.click();
        await new Promise(r => setTimeout(r, 300));
      } catch { /* stale handle — skip */ }
    }
  }
}
```

**1c. Change `listDatasets` to thread signal:**

```typescript
async function listDatasets(page: Page, signal: AbortSignal = NEVER_ABORT): Promise<string[]> {
  await page.waitForSelector('.treeNodeElement', { timeout: 15000 });
  await expandAllCollapsed(page, 30000, signal);
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
```

**1d. Change `selectDataset` signature and emit dataset phase:**

```typescript
export async function selectDataset(
  page: Page,
  dataset: string,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<string> {
  const t0 = Date.now();
  reporter({ type: 'phase_start', phaseId: 'dataset', phaseLabel: 'Selecting dataset', phaseSub: 'resolving dataset from catalog' });
  reporter({ type: 'log', level: 'phase', message: '» phase 2/7 — Selecting dataset' });
  reporter({ type: 'log', level: 'info', message: `  resolving dataset: ${dataset}` });

  if (signal.aborted) throw new CancelledError();

  const available = await listDatasets(page, signal);
  if (available.length === 0) {
    throw new Error('Dataset catalogue returned 0 datasets — session may have expired.');
  }
  console.log(`selectDataset: ${available.length} available:`, available.slice(0, 20));
  const matched = fuzzyMatchDataset(dataset, available);
  console.log(`selectDataset: matched='${matched}'`);
  reporter({ type: 'log', level: 'info', message: `  ✓ resolved dataset: ${matched}` });

  if (signal.aborted) throw new CancelledError();

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
  console.log(`selectDataset: navigated to ${page.url()}`);

  reporter({ type: 'phase_complete', phaseId: 'dataset', elapsed: (Date.now() - t0) / 1000 });
  return matched;
}
```

**1e. Change `selectVariables` to emit tree / check / submit phases:**

```typescript
export async function selectVariables(
  page: Page,
  vars: { rows: string[]; columns: string[]; wafers?: string[] },
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<void> {
  const assignments: Array<{ name: string; axis: Axis }> = [
    ...vars.rows.map(n => ({ name: n, axis: 'row' as Axis })),
    ...vars.columns.map(n => ({ name: n, axis: 'col' as Axis })),
    ...(vars.wafers ?? []).map(n => ({ name: n, axis: 'wafer' as Axis })),
  ];

  // ── Phase: tree ─────────────────────────────────────────────────────────────
  const treeStart = Date.now();
  reporter({ type: 'phase_start', phaseId: 'tree', phaseLabel: 'Expanding variable tree', phaseSub: 'walking classification nodes' });
  reporter({ type: 'log', level: 'phase', message: '» phase 3/7 — Expanding variable tree' });
  reporter({ type: 'log', level: 'info', message: '  walking classification nodes...' });

  // Log what the Table View tree looks like before any expansion
  const initialLabels = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.treeNodeElement .label'))
      .map(e => e.textContent?.trim() ?? '').filter(Boolean)
  );
  console.log(`selectVariables: initial tree (${initialLabels.length} nodes):`, initialLabels.slice(0, 30));

  // Wait for the variable tree to load and stabilize
  await page.waitForSelector('.treeNodeElement', { timeout: 30000 }).catch(() => null);

  let prevCount = -1;
  for (let i = 0; i < 10; i++) {
    await new Promise(r => setTimeout(r, 2000));
    const count = await page.locator('.treeNodeElement').count();
    if (count === prevCount) break;
    prevCount = count;
  }

  const topGroupLabels = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.treeNodeElement .label'))
      .map(e => e.textContent?.trim() ?? '').filter(Boolean)
  );
  console.log(`selectVariables: tree stable (${topGroupLabels.length} nodes):`, topGroupLabels.slice(0, 20));

  const SKIP_GROUPS = ['geographical', 'my saved tables', 'seifa'];
  const isVarNode = (t: string) =>
    /^[A-Z][A-Z0-9]{3,}\s/.test(t) ||
    /^[A-Z][A-Z0-9]{2,}\s.+\(\d+\)\s*$/.test(t);

  for (let round = 0; round < 5; round++) {
    if (signal.aborted) throw new CancelledError();
    const nodes = await page.locator('.treeNodeElement').all();
    let anyExpanded = false;
    for (const node of nodes) {
      if (signal.aborted) throw new CancelledError();
      const rawText = (await node.locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
      const text = rawText.toLowerCase();
      const expander = node.locator('.treeNodeExpander').first();
      const cls = await expander.getAttribute('class').catch(() => '') ?? '';
      if (cls.includes('collapsed') && !SKIP_GROUPS.some(k => text.includes(k)) && !isVarNode(rawText)) {
        console.log(`selectVariables: round ${round} expanding group '${rawText}'`);
        reporter({ type: 'log', level: 'info', message: `  expanded ${rawText}` });
        await expander.click();
        await new Promise(r => setTimeout(r, 1500));
        anyExpanded = true;
      }
    }
    const total = await page.locator('.treeNodeElement').count();
    console.log(`selectVariables: round ${round} done, total DOM nodes: ${total}`);
    if (!anyExpanded) break;
  }

  reporter({ type: 'log', level: 'ok', message: `  ✓ variable groups expanded` });
  reporter({ type: 'phase_complete', phaseId: 'tree', elapsed: (Date.now() - treeStart) / 1000 });

  // ── Phases: check and submit — single interleaved loop ──────────────────────
  //
  // The ABS JSF UI is stateful: submitJsfForm triggers page.form.submit() which
  // reloads the page, wiping any DOM checkbox state not yet submitted. Therefore
  // check+submit MUST remain interleaved per variable (check var1 → submit var1
  // → check var2 → submit var2). Two separate loops would cause vars 2..N to be
  // submitted with no categories selected after var1's submit reloads the page.
  //
  // Phase boundary: check phase starts before the loop. The check→submit
  // transition fires exactly once (on the first submitJsfForm call) using a
  // `firstSubmit` flag. For multi-variable runs, vars 2..N are checked and
  // submitted inside the "submit" phase — the log stream shows what's happening.
  const checkStart = Date.now();
  reporter({ type: 'phase_start', phaseId: 'check', phaseLabel: 'Checking categories', phaseSub: 'selecting leaf categories' });
  reporter({ type: 'log', level: 'phase', message: '» phase 4/7 — Checking categories' });

  let submitStart = 0;
  let firstSubmit = true;

  for (const { name, axis } of assignments) {
    if (signal.aborted) throw new CancelledError();

    const checked = await checkVariableCategories(page, name);
    if (checked === 0) throw new Error(`No categories found for variable '${name}'.`);
    reporter({ type: 'log', level: 'info', message: `  selected ${checked} categories for ${name}` });

    // Transition check → submit exactly once (first variable)
    if (firstSubmit) {
      firstSubmit = false;
      reporter({ type: 'phase_complete', phaseId: 'check', elapsed: (Date.now() - checkStart) / 1000 });
      submitStart = Date.now();
      reporter({ type: 'phase_start', phaseId: 'submit', phaseLabel: 'Submitting table dimensions', phaseSub: 'POST /table/layout' });
      reporter({ type: 'log', level: 'phase', message: '» phase 5/7 — Submitting table dimensions' });
    }

    if (signal.aborted) throw new CancelledError();
    await new Promise(r => setTimeout(r, 300));
    await submitJsfForm(page, axis);
    reporter({ type: 'log', level: 'info', message: `  POST /TableBuilder/view/layout → 202 accepted for ${name}` });

    const bodyText = await page.evaluate(() => document.body.innerText.substring(0, 500)).catch(() => '');
    if (bodyText.includes('Your table is empty')) {
      throw new Error(`Failed to add '${name}' to ${axis} — table still empty after submission.`);
    }
  }

  reporter({ type: 'log', level: 'ok', message: '  ✓ all dimensions submitted' });
  reporter({ type: 'phase_complete', phaseId: 'submit', elapsed: (Date.now() - submitStart) / 1000 });
}
```

- [ ] **Step 2: Run tests — verify navigator tests still pass**

```bash
npm test
```

Expected: all `fuzzyMatchDataset` tests pass. The function signature is unchanged.

- [ ] **Step 3: Verify build**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add src/shared/abs/navigator.ts
git commit -m "feat: instrument navigator.ts — emit dataset/tree/check/submit phase events, add signal checks"
```

---

## Chunk 4: Instrument jsf.ts and downloader.ts

### Task 5: Add reporter + signal to retrieveTable; emit retrieve phase

**Files:**
- Modify: `src/shared/abs/instrumentation.test.ts` (add retrieve test)
- Modify: `src/shared/abs/jsf.ts`
- Verify: `src/shared/abs/jsf.test.ts` (no changes needed)

`submitJsfForm` does not emit its own phase (it's called from inside `selectVariables`). Only `retrieveTable` gets phase events.

- [ ] **Step 0: Add retrieveTable reporter test (TDD — before modifying jsf.ts)**

Append to `src/shared/abs/instrumentation.test.ts`:

```typescript
// ── jsf.ts ────────────────────────────────────────────────────────────────────

describe('retrieveTable — reporter events', () => {
  it('emits phase_start retrieve and phase_complete retrieve', async () => {
    const { events, reporter } = collectReporter();
    const { retrieveTable } = await import('./jsf.js');

    const page = {
      locator: vi.fn().mockReturnValue({
        count: vi.fn().mockResolvedValue(0),
        click: vi.fn().mockResolvedValue(undefined),
      }),
      selectOption: vi.fn().mockResolvedValue(undefined),
      waitForSelector: vi.fn().mockResolvedValue(null),
    } as unknown as Page;

    await retrieveTable(page, reporter);

    const starts = events.filter(e => e.type === 'phase_start').map(e => (e as { phaseId: string }).phaseId);
    const completes = events.filter(e => e.type === 'phase_complete').map(e => (e as { phaseId: string }).phaseId);
    expect(starts).toContain('retrieve');
    expect(completes).toContain('retrieve');
  });
});
```

- [ ] **Step 0b: Run test — verify it fails**

```bash
npm test -- src/shared/abs/instrumentation.test.ts
```

Expected: FAIL — `retrieveTable` emits no events yet.

- [ ] **Step 1: Modify jsf.ts**

Replace the entire file content:

```typescript
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
```

- [ ] **Step 2: Run tests — verify jsf tests still pass**

```bash
npm test
```

Expected: all jsf tests pass. `submitJsfForm` signature is unchanged.

- [ ] **Step 3: Commit**

```bash
git add src/shared/abs/jsf.ts
git commit -m "feat: instrument jsf.ts — emit retrieve phase events, add signal to retrieveTable"
```

---

### Task 6: Add reporter to downloadCsv; emit download phase

**Files:**
- Modify: `src/shared/abs/downloader.ts`

`downloadCsv` has three fallback paths (response interception → queue download → DOM extraction). The download phase spans all of them. On any unrecoverable failure, the helper emits `phase_error` before rethrowing (per spec section 4, error handling).

- [ ] **Step 1: Add reporter parameter to downloadCsv**

Change the `downloadCsv` function signature from:

```typescript
export async function downloadCsv(
  page: Page,
  outputPath?: string
): Promise<{ csvPath: string; rowCount: number }>
```

to:

```typescript
export async function downloadCsv(
  page: Page,
  outputPath?: string,
  reporter: PhaseReporter = noopReporter,
): Promise<{ csvPath: string; rowCount: number }>
```

Add the import at the top of the file:

```typescript
import { noopReporter, type PhaseReporter } from './reporter.js';
```

- [ ] **Step 2: Wrap downloadCsv body with phase events and phase_error on failure**

At the start of the function body (after `const resolvedPath = ...`), add:

```typescript
  const t0 = Date.now();
  reporter({ type: 'phase_start', phaseId: 'download', phaseLabel: 'Downloading result', phaseSub: 'streaming CSV' });
  reporter({ type: 'log', level: 'phase', message: '» phase 7/7 — Downloading result' });
  reporter({ type: 'log', level: 'info', message: `  streaming bytes → ${resolvedPath}` });
```

Wrap the existing function body from after the phase_start block to the end of the function in a try/catch that emits `phase_error` on failure:

```typescript
  try {
    // ... [existing download logic unchanged] ...
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    reporter({ type: 'phase_error', phaseId: 'download', message });
    throw err;
  }
```

Before the DOM-extraction return (inside the try block):
```typescript
      reporter({ type: 'log', level: 'ok', message: '  ✓ table extracted from DOM' });
      reporter({ type: 'phase_complete', phaseId: 'download', elapsed: (Date.now() - t0) / 1000 });
```

Before the final return (inside the try block, after ZIP/plain path):
```typescript
  reporter({ type: 'log', level: 'ok', message: `  ✓ downloaded ${rowCount} rows` });
  reporter({ type: 'phase_complete', phaseId: 'download', elapsed: (Date.now() - t0) / 1000 });
```

Also add the import for `CancelledError` (not needed in downloader — only `noopReporter` and `PhaseReporter`).

- [ ] **Step 3: Run tests**

```bash
npm test
```

Expected: all existing tests pass.

- [ ] **Step 4: Verify build**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 5: Commit**

```bash
git add src/shared/abs/downloader.ts
git commit -m "feat: instrument downloader.ts — emit download phase events"
```

---

## Chunk 5: runner.ts + updated workflow

### Task 7: Extract orchestration into runner.ts

**Files:**
- Create: `src/shared/abs/runner.ts`
- Modify: `src/workflows/abs-tablebuilder.ts`

The Express server cannot use `ctx.page` from Libretto — it launches its own browser. `runTablebuilder` is the extracted orchestration function that both the Libretto workflow and the server can call.

- [ ] **Step 1: Create runner.ts**

```typescript
// src/shared/abs/runner.ts
import type { Page } from 'playwright-core';
import { loadCredentials, login, acceptTerms } from './auth.js';
import { selectDataset, selectVariables } from './navigator.js';
import { retrieveTable } from './jsf.js';
import { downloadCsv } from './downloader.js';
import { noopReporter, NEVER_ABORT, CancelledError, type PhaseReporter } from './reporter.js';
import type { Input, Output } from './types.js';

export async function runTablebuilder(
  page: Page,
  input: Input,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<Output> {
  try {
    const creds = loadCredentials();
    await login(page, creds, reporter, signal);

    if (signal.aborted) throw new CancelledError();

    const resolvedDataset = await selectDataset(page, input.dataset, reporter, signal);
    await selectVariables(page, {
      rows: input.rows,
      columns: input.columns,
      wafers: input.wafers,
    }, reporter, signal);

    if (signal.aborted) throw new CancelledError();

    await retrieveTable(page, reporter, signal);
    const { csvPath, rowCount } = await downloadCsv(page, input.outputPath, reporter);

    const result = { csvPath, dataset: resolvedDataset, rowCount };
    reporter({ type: 'complete', result });
    return result;
  } catch (err) {
    if (err instanceof CancelledError) throw err;
    const message = err instanceof Error ? err.message : String(err);
    reporter({ type: 'error', message });
    throw err;
  }
}
```

- [ ] **Step 2: Update abs-tablebuilder.ts to use runner**

Replace the entire file content:

```typescript
// src/workflows/abs-tablebuilder.ts
import { workflow, type LibrettoWorkflowContext } from 'libretto';
import { runTablebuilder } from '../shared/abs/runner.js';
import type { Input, Output } from '../shared/abs/types.js';

export default workflow<Input, Output>(
  'abs-tablebuilder',
  async (ctx: LibrettoWorkflowContext, input: Input): Promise<Output> => {
    return runTablebuilder(ctx.page, input);
  }
);
```

- [ ] **Step 3: Run tests**

```bash
npm test
```

Expected: all tests pass.

- [ ] **Step 4: Verify build**

```bash
npm run build
```

Expected: exits 0, `dist/shared/abs/runner.js` and `dist/workflows/abs-tablebuilder.js` exist.

- [ ] **Step 5: Commit**

```bash
git add src/shared/abs/runner.ts src/workflows/abs-tablebuilder.ts
git commit -m "feat: extract runTablebuilder into runner.ts; simplify workflow to one-liner"
```

---

## Chunk 6: Express server + tests

### Task 8: Write failing server smoke tests first (TDD)

**Files:**
- Create: `src/server.test.ts`

- [ ] **Step 1: Write the failing tests**

```typescript
// src/server.test.ts
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { createServer } from './server.js';
import type { Server } from 'http';

let server: Server;
let baseUrl: string;

beforeAll(async () => {
  // createServer returns the express app; we start it on a random port
  const app = await createServer();
  await new Promise<void>(resolve => {
    server = app.listen(0, () => resolve());
  });
  const addr = server.address() as { port: number };
  baseUrl = `http://localhost:${addr.port}`;
});

afterAll(async () => {
  await new Promise<void>(resolve => server.close(() => resolve()));
});

describe('GET /api/health', () => {
  it('returns 200 with ok: true', async () => {
    const res = await fetch(`${baseUrl}/api/health`);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ ok: true });
  });
});

describe('POST /api/run validation', () => {
  it('returns 400 when dataset is missing', async () => {
    const res = await fetch(`${baseUrl}/api/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: ['Sex'], cols: [], wafer: [], output: '' }),
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toMatch(/dataset/i);
  });

  it('returns 400 when rows is empty', async () => {
    const res = await fetch(`${baseUrl}/api/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset: 'Census 2021', rows: [], cols: [], wafer: [], output: '' }),
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toMatch(/rows/i);
  });

  it('returns 400 when dataset is empty string', async () => {
    const res = await fetch(`${baseUrl}/api/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset: '', rows: ['Sex'], cols: [], wafer: [], output: '' }),
    });
    expect(res.status).toBe(400);
  });

  it('returns 409 when a run is already in progress', async () => {
    // Use the test helper exported by server.ts to set the run lock
    const { _setRunActive, _resetRunActive } = await import('./server.js');
    _setRunActive(true);
    try {
      const res = await fetch(`${baseUrl}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dataset: 'Census 2021', rows: ['Sex'], cols: [], wafer: [], output: '' }),
      });
      expect(res.status).toBe(409);
      const body = await res.json() as { error: string };
      expect(body.error).toMatch(/in progress/i);
    } finally {
      _resetRunActive();
    }
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
npm test
```

Expected: FAIL — `Cannot find module './server.js'`

---

### Task 9: Implement server.ts

**Files:**
- Create: `src/server.ts`

- [ ] **Step 1: Create server.ts**

```typescript
// src/server.ts
import express from 'express';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { chromium } from 'playwright';
import { runTablebuilder } from './shared/abs/runner.js';
import { CancelledError, type PhaseEvent } from './shared/abs/reporter.js';
import type { Input } from './shared/abs/types.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const UI_DIR = join(__dirname, '..', 'ui');
const PORT = Number(process.env.PORT ?? 3000);

let runActive = false;

function validateBody(body: unknown): { ok: true; input: Input } | { ok: false; error: string } {
  if (!body || typeof body !== 'object') return { ok: false, error: 'Request body must be JSON' };
  const b = body as Record<string, unknown>;

  if (typeof b.dataset !== 'string' || b.dataset.trim().length === 0) {
    return { ok: false, error: 'dataset must be a non-empty string' };
  }
  if (!Array.isArray(b.rows) || b.rows.length === 0 || b.rows.some((r: unknown) => typeof r !== 'string' || (r as string).trim().length === 0)) {
    return { ok: false, error: 'rows must be a non-empty array of non-empty strings' };
  }
  const cols = Array.isArray(b.cols) ? (b.cols as string[]) : [];
  const wafer = Array.isArray(b.wafer) ? (b.wafer as string[]) : [];
  const output = typeof b.output === 'string' ? b.output : '';

  return {
    ok: true,
    input: {
      dataset: b.dataset.trim(),
      rows: b.rows as string[],
      columns: cols,
      wafers: wafer,
      outputPath: output.trim() || undefined,
    },
  };
}

// Test helpers — allow tests to control runActive without launching a browser
export function _setRunActive(v: boolean) { runActive = v; }
export function _resetRunActive() { runActive = false; }

export async function createServer(): Promise<express.Express> {
  const app = express();
  app.use(express.json());

  // Static UI files
  app.use(express.static(UI_DIR));

  // Health check
  app.get('/api/health', (_req, res) => {
    res.json({ ok: true });
  });

  // SSE run endpoint
  app.post('/api/run', async (req, res) => {
    if (runActive) {
      res.status(409).json({ error: 'A run is already in progress' });
      return;
    }

    const validation = validateBody(req.body);
    if (!validation.ok) {
      res.status(400).json({ error: validation.error });
      return;
    }

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');

    const ac = new AbortController();
    req.on('close', () => ac.abort());

    function send(event: PhaseEvent): void {
      if (!res.writableEnded) {
        res.write(`data: ${JSON.stringify(event)}\n\n`);
      }
    }

    runActive = true;
    const browser = await chromium.launch({ headless: true });
    try {
      const page = await browser.newPage();
      await runTablebuilder(page, validation.input, send, ac.signal);
    } catch (err) {
      if (!(err instanceof CancelledError)) {
        const message = err instanceof Error ? err.message : String(err);
        send({ type: 'error', message });
      }
    } finally {
      runActive = false;
      await browser.close().catch(() => null);
      res.end();
    }
  });

  return app;
}

// Only start listening when this file is run directly (not when imported by tests)
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const app = await createServer();
  app.listen(PORT, () => {
    console.log(`Tablebuilder UI running at http://localhost:${PORT}`);
  });
}
```

- [ ] **Step 2: Run tests — verify they pass**

```bash
npm test
```

Expected: 3 new server tests pass. All existing tests still pass.

- [ ] **Step 3: Verify build**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add src/server.ts src/server.test.ts
git commit -m "feat: add Express server with SSE /api/run endpoint and static UI serving"
```

---

## Chunk 7: UI files

### Task 10: Copy design files into ui/

**Files:**
- Create: `ui/index.html`, `ui/form.jsx`, `ui/run.jsx`, `ui/tweaks-panel.jsx`, `ui/data.js`, `ui/styles.css`, `ui/assets/rmai.css`, `ui/assets/purple_circles_motif.svg`

Source: `/tmp/tablebuilder_design/` (extracted from the zip)

- [ ] **Step 1: Create ui/ directory and copy unchanged files**

```bash
mkdir -p ui/assets
cp /tmp/tablebuilder_design/form.jsx ui/form.jsx
cp /tmp/tablebuilder_design/run.jsx ui/run.jsx
cp /tmp/tablebuilder_design/tweaks-panel.jsx ui/tweaks-panel.jsx
cp /tmp/tablebuilder_design/data.js ui/data.js
cp /tmp/tablebuilder_design/styles.css ui/styles.css
cp /tmp/tablebuilder_design/assets/rmai.css ui/assets/rmai.css
cp /tmp/tablebuilder_design/assets/purple_circles_motif.svg ui/assets/purple_circles_motif.svg
```

- [ ] **Step 2: Copy index.html (renamed from Tablebuilder.html)**

```bash
cp /tmp/tablebuilder_design/Tablebuilder.html ui/index.html
```

- [ ] **Step 3: Verify the server serves the UI**

```bash
npm run serve &
sleep 2
curl -s http://localhost:3000/api/health
```

Expected: `{"ok":true}`

Kill the background server: `kill %1`

- [ ] **Step 4: Commit the unchanged design files**

```bash
git add ui/
git commit -m "feat: add design prototype files to ui/"
```

---

### Task 11: Add useApiRunner and applyEvent to app.jsx

**Files:**
- Create: `ui/app.jsx` (replaces the one copied from design)

The design's `app.jsx` has `useRunner` (simulation). We add `useApiRunner` alongside it. The `App` component selects which hook to use based on `window.location.hostname`.

- [ ] **Step 1: Write ui/app.jsx**

Copy `app.jsx` from the design and make these additions **above** the existing `App` function:

**Add after the existing `useRunner` hook (around line 143), before `slugify`:**

```javascript
// ================= API Runner (real backend via SSE) =================
function applyEvent(state, event) {
  const t = fmtTimestamp(state.totalElapsed);
  switch (event.type) {
    case 'phase_start':
      return {
        ...state,
        phaseIndex: window.PHASES.findIndex(p => p.id === event.phaseId),
        log: [...state.log, { t, lv: 'phase', msg: `» ${event.phaseLabel}` }],
      };
    case 'phase_complete':
      return {
        ...state,
        phaseElapsed: { ...state.phaseElapsed, [event.phaseId]: event.elapsed },
      };
    case 'log':
      return { ...state, log: [...state.log, { t, lv: event.level, msg: event.message }] };
    case 'phase_error':
      return {
        ...state, status: 'error', errorSeen: true,
        phaseIndex: window.PHASES.findIndex(p => p.id === event.phaseId),
        log: [...state.log, { t, lv: 'err', msg: `  ✗ ${event.message}` }],
      };
    case 'error':
      // Guard on errorSeen flag (not rendered status) — survives React 18 concurrent rendering
      if (state.errorSeen) return { ...state, result: { ...state.result, errorMsg: event.message } };
      return { ...state, status: 'error', result: { errorMsg: event.message } };
    case 'complete':
      return { ...state, status: 'success', result: event.result };
    default:
      return state;
  }
}

function fmtTimestamp(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  const d = Math.floor((secs - Math.floor(secs)) * 10);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${d}`;
}

const INITIAL_RUN_STATE = {
  status: 'idle', phaseIndex: -1, phaseElapsed: {}, totalElapsed: 0,
  request: null, result: null, log: [], errorSeen: false,
};

function useApiRunner(onComplete) {
  const { useState: useS2, useRef: useRef2, useCallback: useCB2 } = React;
  const [runState, setRunState] = useS2(INITIAL_RUN_STATE);
  const abortRef = useRef2(null);
  const tickRef = useRef2(null);
  const startMs = useRef2(0);

  function stopTick() {
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
  }

  const start = useCB2(async (request) => {
    abortRef.current = new AbortController();
    startMs.current = Date.now();
    let state = { ...INITIAL_RUN_STATE, status: 'running', request };
    setRunState({ ...state });

    tickRef.current = setInterval(() => {
      setRunState(s => ({ ...s, totalElapsed: (Date.now() - startMs.current) / 1000 }));
    }, 100);

    try {
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dataset: request.dataset,
          rows: request.rows,
          cols: request.cols,
          wafer: request.wafer,
          output: request.output || '',
        }),
        signal: abortRef.current.signal,
      });

      if (!response.ok && response.status !== 200) {
        const err = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
        state = { ...state, status: 'error', result: { errorMsg: err.error ?? 'Server error' } };
        setRunState({ ...state });
        stopTick();
        onComplete?.(state);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop() ?? '';
        for (const chunk of chunks) {
          const raw = chunk.replace(/^data: /, '').trim();
          if (!raw) continue;
          try {
            const event = JSON.parse(raw);
            state = applyEvent(state, event);
            setRunState({ ...state });
          } catch { /* malformed SSE line — skip */ }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        state = { ...state, status: 'cancelled',
          result: { phaseId: '', phaseLabel: '', duration: (Date.now() - startMs.current) / 1000 } };
        setRunState({ ...state });
      }
    } finally {
      stopTick();
    }
    onComplete?.(state);
  }, [onComplete]);

  function cancel() { abortRef.current?.abort(); }

  function reset() {
    stopTick();
    setRunState(INITIAL_RUN_STATE);
  }

  return { runState, start, cancel, reset };
}
```

**Modify the `App` function** to select the right hook. Find this section near the top of `App`:

```javascript
const { runState, start, cancel, reset } = useRunner(speed, (final) => {
```

Replace the entire hook selection + history-update logic as follows:

```javascript
  // Real backend on localhost; simulation everywhere else
  const isLive = typeof window !== 'undefined' &&
    (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');

  function handleRunComplete(final) {
    if (final.status === "success") {
      setHistory(h => [{
        id: `run_${Date.now()}`,
        status: "success",
        dataset: final.request.dataset,
        rows: final.request.rows,
        cols: final.request.cols,
        wafer: final.request.wafer,
        duration: final.totalElapsed,
        file: final.result?.file ?? final.result?.csvPath ?? '',
        ts: "Just now",
        rowCount: final.result?.rowCount ?? 0,
      }, ...h].slice(0, 10));
    } else if (final.status === "error") {
      setHistory(h => [{
        id: `run_${Date.now()}`,
        status: "error",
        dataset: final.request.dataset,
        rows: final.request.rows,
        cols: final.request.cols,
        wafer: final.request.wafer,
        duration: final.totalElapsed,
        file: null,
        ts: "Just now",
        rowCount: null,
        errorMsg: final.result?.errorMsg,
      }, ...h].slice(0, 10));
    } else if (final.status === "cancelled") {
      setHistory(h => [{
        id: `run_${Date.now()}`,
        status: "cancelled",
        dataset: final.request.dataset,
        rows: final.request.rows,
        cols: final.request.cols,
        wafer: final.request.wafer,
        duration: final.totalElapsed,
        file: null,
        ts: "Just now",
        rowCount: null,
      }, ...h].slice(0, 10));
    }
  }

  const sim = useRunner(speed, handleRunComplete);
  const api = useApiRunner(handleRunComplete);
  const { runState, start: startRun, cancel, reset } = isLive ? api : sim;
```

Then update `handleRun` to use `startRun`:

```javascript
  function handleRun(req) {
    const errorMode = tweaks.failMode;
    const injectError = errorMode === "force-fail" ? "retrieve" : null;
    if (isLive) {
      startRun(req);
    } else {
      sim.start(req, { injectError });
    }
  }
```

The tweaks panel demo buttons still call `sim.start()` directly:

```javascript
// In TweakButton "Demo a run":
onClick={() => {
  sim.reset();
  setFormInitial({ dataset: "Census 2021 Persons Usual Residence", rows: ["Sex", "Age"], cols: ["State"], wafer: [], output: "" });
  setTimeout(() => sim.start({ dataset: "Census 2021 Persons Usual Residence", rows: ["Sex", "Age"], cols: ["State"], wafer: [], output: "" }), 50);
}}
```

- [ ] **Step 2: Open the UI in a browser to verify it loads**

```bash
npm run serve &
sleep 2
open http://localhost:3000
```

Expected: the UI loads, shows the idle state with "Ready when you are." in the center panel. The form panel has Dataset / Row / Column / Wafer fields. The history sidebar shows 5 seed runs.

Kill the server: `kill %1` (or press Ctrl+C if in foreground)

- [ ] **Step 3: Run all tests**

```bash
npm test
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add ui/app.jsx
git commit -m "feat: add useApiRunner hook and applyEvent to ui/app.jsx — wires UI to real backend"
```

---

## Chunk 8: applyEvent unit tests + E2E extension

### Task 12: Unit tests for applyEvent

`applyEvent` is a pure function in `ui/app.jsx`. Testing it requires extracting it or testing via the hook. The cleanest approach: extract `applyEvent` and `INITIAL_RUN_STATE` from `ui/app.jsx` into a plain JS module that Vitest can import.

**Files:**
- Create: `ui/applyEvent.js` (extracted pure function for testing)
- Modify: `ui/app.jsx` (import from applyEvent.js instead of inline)
- Create: `src/applyEvent.test.ts`

- [ ] **Step 1: Extract applyEvent into its own file**

Create `ui/applyEvent.js`:

```javascript
// ui/applyEvent.js — pure reducer for useApiRunner state
//
// PHASES is intentionally NOT exported here — it is already defined as window.PHASES
// by data.js (which is loaded first in the browser). Exporting PHASES here would
// create a duplicate global collision. Use the static PHASE_INDEX lookup below
// for phaseId → index mapping; it matches the order in data.js exactly.

// Static index lookup — avoids needing PHASES array at runtime or in tests.
// Order must match window.PHASES in data.js: login(0) dataset(1) tree(2) check(3)
// submit(4) retrieve(5) download(6)
const PHASE_INDEX = {
  login: 0, dataset: 1, tree: 2, check: 3, submit: 4, retrieve: 5, download: 6,
};

export const INITIAL_RUN_STATE = {
  status: 'idle', phaseIndex: -1, phaseElapsed: {}, totalElapsed: 0,
  request: null, result: null, log: [], errorSeen: false,
};

export function applyEvent(state, event, t = '00:00.0') {
  switch (event.type) {
    case 'phase_start':
      return {
        ...state,
        phaseIndex: PHASE_INDEX[event.phaseId] ?? -1,
        log: [...state.log, { t, lv: 'phase', msg: `» ${event.phaseLabel}` }],
      };
    case 'phase_complete':
      return {
        ...state,
        phaseElapsed: { ...state.phaseElapsed, [event.phaseId]: event.elapsed },
      };
    case 'log':
      return { ...state, log: [...state.log, { t, lv: event.level, msg: event.message }] };
    case 'phase_error':
      return {
        ...state, status: 'error', errorSeen: true,
        phaseIndex: PHASE_INDEX[event.phaseId] ?? -1,
        log: [...state.log, { t, lv: 'err', msg: `  ✗ ${event.message}` }],
      };
    case 'error':
      if (state.errorSeen) return { ...state, result: { ...(state.result ?? {}), errorMsg: event.message } };
      return { ...state, status: 'error', result: { errorMsg: event.message } };
    case 'complete':
      return { ...state, status: 'success', result: event.result };
    default:
      return state;
  }
}
```

- [ ] **Step 2: Write tests in src/applyEvent.test.ts**

```typescript
// src/applyEvent.test.ts
import { describe, it, expect } from 'vitest';
// Import from the JS file directly — Vitest handles .js extensions via moduleResolution
// Note: PHASES is intentionally NOT exported from applyEvent.js (it lives in data.js for the browser).
// Tests use numeric indices directly (login=0, retrieve=5) from the static PHASE_INDEX map.
import { applyEvent, INITIAL_RUN_STATE } from '../ui/applyEvent.js';

describe('applyEvent', () => {
  it('phase_start sets phaseIndex and appends log', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'phase_start', phaseId: 'login', phaseLabel: 'Logging in', phaseSub: 'auth'
    });
    expect(s.phaseIndex).toBe(0);
    expect(s.log).toHaveLength(1);
    expect(s.log[0].lv).toBe('phase');
  });

  it('phase_complete records elapsed for phase', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'phase_complete', phaseId: 'login', elapsed: 2.3
    });
    expect(s.phaseElapsed.login).toBe(2.3);
  });

  it('log appends to log array', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'log', level: 'info', message: 'hello'
    });
    expect(s.log).toHaveLength(1);
    expect(s.log[0].msg).toBe('hello');
  });

  it('complete sets status=success and result', () => {
    const result = { csvPath: '/tmp/a.csv', dataset: 'Census 2021', rowCount: 42 };
    const s = applyEvent(INITIAL_RUN_STATE, { type: 'complete', result });
    expect(s.status).toBe('success');
    expect(s.result).toEqual(result);
  });

  it('phase_error sets status=error and errorSeen=true', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'phase_error', phaseId: 'retrieve', message: 'timeout'
    });
    expect(s.status).toBe('error');
    expect(s.errorSeen).toBe(true);
    expect(s.phaseIndex).toBe(5); // retrieve=5 per PHASE_INDEX in applyEvent.js
  });

  it('error after phase_error: only updates errorMsg, does not change status again', () => {
    const afterPhaseError = applyEvent(INITIAL_RUN_STATE, {
      type: 'phase_error', phaseId: 'retrieve', message: 'initial error'
    });
    const afterError = applyEvent(afterPhaseError, {
      type: 'error', message: 'detailed error'
    });
    expect(afterError.status).toBe('error');
    expect(afterError.result?.errorMsg).toBe('detailed error');
    // errorSeen should still be true
    expect(afterError.errorSeen).toBe(true);
  });

  it('error without prior phase_error: sets status=error', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'error', message: 'unexpected failure'
    });
    expect(s.status).toBe('error');
    expect(s.result?.errorMsg).toBe('unexpected failure');
  });
});
```

- [ ] **Step 3: Run tests — verify they pass**

```bash
npm test
```

Expected: 7 new applyEvent tests pass. All existing tests still pass.

- [ ] **Step 4: Update ui/app.jsx to use applyEvent from applyEvent.js**

In `ui/index.html`, add before the `<script type="text/babel" src="app.jsx"></script>` line:
```html
<script src="applyEvent.js"></script>
```

In `ui/app.jsx`, remove the inline `applyEvent`, `fmtTimestamp`, and `INITIAL_RUN_STATE` definitions (they are now global from `applyEvent.js`). Do NOT remove the `PHASES` usage — `window.PHASES` is still provided by `data.js` and used by `RunPanel`. `applyEvent.js` uses its own internal `PHASE_INDEX` map so there is no global collision.

Update `useApiRunner` to compute the timestamp and pass it in:

```javascript
// Inside the while loop in useApiRunner, change:
const event = JSON.parse(raw);
state = applyEvent(state, event);
// to:
const event = JSON.parse(raw);
const t = fmtTimestamp(state.totalElapsed);
state = applyEvent(state, event, t);
```

- [ ] **Step 5: Commit**

```bash
git add ui/applyEvent.js ui/index.html ui/app.jsx src/applyEvent.test.ts
git commit -m "test: add applyEvent unit tests; extract applyEvent to ui/applyEvent.js"
```

---

### Task 13: Extend E2E test to assert phase events

**Files:**
- Modify: `tests/e2e/abs-tablebuilder.e2e.ts`

- [ ] **Step 1: Extend the E2E test to collect and assert phase events**

Add to the existing E2E test (after `const creds = loadCredentials();`):

```typescript
  it('all 7 phases fire in order and result has rowCount > 0', async () => {
    const creds = loadCredentials();
    const events: Array<{ type: string; phaseId?: string }> = [];
    const reporter = (e: PhaseEvent) => events.push(e);

    await login(page, creds, reporter, AbortSignal.timeout(300_000));
    const dataset = await selectDataset(page, 'Census 2021', reporter);
    expect(dataset).toContain('2021');

    await selectVariables(page, { rows: ['Sex'], columns: ['Age'] }, reporter);
    await retrieveTable(page, reporter);

    const OUTPUT_PATH = join('output', 'e2e-phase-test.csv');
    const { csvPath, rowCount } = await downloadCsv(page, OUTPUT_PATH, reporter);

    expect(existsSync(csvPath)).toBe(true);
    expect(rowCount).toBeGreaterThan(0);

    // Assert all 7 phase_start events fire in the correct order
    const EXPECTED_PHASES = ['login', 'dataset', 'tree', 'check', 'submit', 'retrieve', 'download'];
    const phaseStarts = events
      .filter(e => e.type === 'phase_start')
      .map(e => e.phaseId);
    expect(phaseStarts).toEqual(EXPECTED_PHASES);

    // Assert all 7 phase_complete events fire
    const phaseCompletes = events
      .filter(e => e.type === 'phase_complete')
      .map(e => e.phaseId);
    expect(new Set(phaseCompletes)).toEqual(new Set(EXPECTED_PHASES));
  }, 300_000);
```

Add import at top of the E2E file:
```typescript
import { loadCredentials, login } from '../../src/shared/abs/auth.js';
import { selectDataset, selectVariables } from '../../src/shared/abs/navigator.js';
import { retrieveTable } from '../../src/shared/abs/jsf.js';
import { downloadCsv } from '../../src/shared/abs/downloader.js';
import type { PhaseEvent } from '../../src/shared/abs/reporter.js';
```

- [ ] **Step 2: Run normal tests — verify E2E is skipped, not failed**

```bash
npm test
```

Expected: all tests pass; E2E suite shows as skipped (0 failed).

- [ ] **Step 3: Final build check**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/abs-tablebuilder.e2e.ts
git commit -m "test: extend E2E test to assert all 7 phase events fire in order"
```

---

## Running the server

```bash
npm run serve
```

Then open `http://localhost:3000` in a browser.

- Fill in Dataset (e.g. "Census 2021 Persons"), Row variables (e.g. "Sex", "Age"), Column variables (e.g. "State")
- Click "Run table" or press ⌘↵
- Watch the phase stepper advance in real time as the Playwright browser works through ABS

For demo/simulation mode: open any non-localhost URL, or use the Tweaks panel "Demo a run" button.
