# Dataset Names + Variable Tree Reset — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two independent bugs: (1) the UI dataset picker shows mock names instead of the 131 real ABS dataset names from `dictionary.db`, and (2) the variable tree collapses after each JSF form submit causing subsequent variables to not be found.

**Architecture:** Bug 1 adds a `GET /api/datasets` Express route backed by `better-sqlite3` reading from `docs/explorer/data/dictionary.db`; the UI fetches real names on mount and falls back to mock data on failure. Bug 2 extracts the existing inline tree-expansion block in `navigator.ts` into a named helper `expandVariableGroups` and calls it again after each `submitJsfForm` when more variables remain.

**Tech Stack:** TypeScript, Express 5, better-sqlite3 (new), Playwright, Vitest, React (plain JS via CDN in UI files)

---

## File Map

| File | Change |
|------|--------|
| `package.json` | Add `better-sqlite3` (runtime) + `@types/better-sqlite3` (dev) |
| `src/server.ts` | Path resolution for `DICT_DB`; DB open at module level; new `GET /api/datasets` route |
| `src/server.test.ts` | New — unit tests for `/api/datasets` (mocked DB) |
| `src/server.datasets.integration.test.ts` | New — integration tests against real `dictionary.db` |
| `ui/form.jsx` | Guard `d.code` in fuzzy scoring (line 41) and display row (line 102) |
| `ui/app.jsx` | Fetch `/api/datasets` on mount, hydrate `window.DATASETS` |
| `src/shared/abs/navigator.ts` | Move `SKIP_GROUPS`/`isVarNode` to module scope; extract `expandVariableGroups`; export it; call it after each `submitJsfForm` |
| `src/shared/abs/navigator.test.ts` | Add `describe('expandVariableGroups')` block |

---

## Chunk 1: Bug 1 — Server-side dataset API

### Task 1: Install better-sqlite3

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Install the packages**

```bash
npm install better-sqlite3
npm install --save-dev @types/better-sqlite3
```

- [ ] **Step 2: Verify install**

```bash
npm ls better-sqlite3
```

Expected output includes `better-sqlite3@X.Y.Z`.

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```bash
npm test
```

Expected: all tests pass, no new failures.

---

### Task 2: Write failing tests for GET /api/datasets

**Files:**
- Create: `src/server.test.ts`

- [ ] **Step 1: Write the unit test file (mocked DB)**

Create `src/server.test.ts`:

```typescript
// src/server.test.ts
import { vi, describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { existsSync } from 'fs'; // gets the mocked version (vi.mock is hoisted)

// Mock better-sqlite3 so no real DB is opened.
// vi.mock is hoisted — runs before any imports below.
vi.mock('better-sqlite3', () => {
  const MOCK_ROWS = [
    { id: 1, name: 'Alpha Dataset' },
    { id: 2, name: 'Beta Dataset' },
  ];
  const MockDb = vi.fn().mockImplementation(() => ({
    prepare: vi.fn().mockReturnValue({ all: vi.fn().mockReturnValue(MOCK_ROWS) }),
  }));
  return { default: MockDb };
});

// Mock existsSync to return true so DICT_DB and UI_DIR both resolve.
vi.mock('fs', async (importOriginal) => {
  const mod = await importOriginal<typeof import('fs')>();
  return {
    ...mod,
    existsSync: vi.fn().mockReturnValue(true),
    realpathSync: vi.fn().mockReturnValue('/fake/server/path'),
  };
});

describe('GET /api/datasets — mocked DB', () => {
  let server: http.Server;
  let baseUrl: string;

  beforeAll(async () => {
    const { createServer } = await import('./server.js');
    const app = await createServer();
    server = http.createServer(app as any);
    await new Promise<void>(resolve => server.listen(0, resolve));
    baseUrl = `http://localhost:${(server.address() as AddressInfo).port}`;
  });

  afterAll(() => server.close());

  it('returns 200 with an array', async () => {
    const res = await fetch(`${baseUrl}/api/datasets`);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBe(true);
  });

  it('each entry has id, name, code:null, tag:null, year:null', async () => {
    const res = await fetch(`${baseUrl}/api/datasets`);
    const body = await res.json() as Record<string, unknown>[];
    expect(body.length).toBeGreaterThan(0);
    const first = body[0];
    expect(typeof first.id).toBe('number');
    expect(typeof first.name).toBe('string');
    expect(first.code).toBeNull();
    expect(first.tag).toBeNull();
    expect(first.year).toBeNull();
  });
});

// 503 case: existsSync returns false for dictionary.db path → dictDb is null
describe('GET /api/datasets — DB unavailable', () => {
  let server: http.Server;
  let baseUrl: string;

  beforeAll(async () => {
    // Change mock return value BEFORE resetModules so the fresh server.ts load
    // sees existsSync() → false and sets DICT_DB = null.
    vi.mocked(existsSync).mockReturnValue(false);
    vi.resetModules(); // Force server.ts to re-evaluate module-level DICT_DB
    const { createServer } = await import('./server.js');
    const app = await createServer();
    server = http.createServer(app as any);
    await new Promise<void>(resolve => server.listen(0, resolve));
    baseUrl = `http://localhost:${(server.address() as AddressInfo).port}`;
  });

  afterAll(() => server.close());

  it('returns 503 when dictionary.db is not found', async () => {
    const res = await fetch(`${baseUrl}/api/datasets`);
    expect(res.status).toBe(503);
    const body = await res.json() as { error: string };
    expect(typeof body.error).toBe('string');
  });
});
```

- [ ] **Step 2: Write the integration test file (real DB)**

Create `src/server.datasets.integration.test.ts`:

```typescript
// src/server.datasets.integration.test.ts
// Uses the real dictionary.db — no mocks. Run with: npm test
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { createServer } from './server.js';

describe('GET /api/datasets — real dictionary.db', () => {
  let server: http.Server;
  let baseUrl: string;

  beforeAll(async () => {
    const app = await createServer();
    server = http.createServer(app as any);
    await new Promise<void>(resolve => server.listen(0, resolve));
    baseUrl = `http://localhost:${(server.address() as AddressInfo).port}`;
  });

  afterAll(() => server.close());

  it('returns at least 100 dataset names', async () => {
    const res = await fetch(`${baseUrl}/api/datasets`);
    if (res.status === 503) {
      console.warn('dictionary.db not found — skipping integration test');
      return;
    }
    expect(res.status).toBe(200);
    const body = await res.json() as unknown[];
    expect(body.length).toBeGreaterThanOrEqual(100);
  });

  it('includes the canonical 2021 persons usual residence dataset', async () => {
    const res = await fetch(`${baseUrl}/api/datasets`);
    if (res.status === 503) return;
    const body = await res.json() as Array<{ name: string }>;
    expect(body.map(d => d.name)).toContain(
      '2021 Census - counting persons, place of usual residence'
    );
  });
});
```

- [ ] **Step 3: Run tests to confirm they fail (server has no /api/datasets yet)**

```bash
npm test -- src/server.test.ts src/server.datasets.integration.test.ts
```

Expected: FAIL — both tests in the mocked-DB suite fail with 404 on `/api/datasets`; the integration test also fails with 404.

---

### Task 3: Implement GET /api/datasets in server.ts

**Files:**
- Modify: `src/server.ts:1-21` (imports and path resolution)
- Modify: `src/server.ts:179-183` (after /api/health route)

- [ ] **Step 1: Add the better-sqlite3 import**

Add after the existing imports block (after line 14, before the blank line):

```typescript
import Database from 'better-sqlite3';
```

The full import section should now end with:
```typescript
import type { Credentials, Input } from './shared/abs/types.js';
import Database from 'better-sqlite3';
```

- [ ] **Step 2: Add DICT_DB path resolution after UI_DIR (line 21)**

After:
```typescript
const UI_DIR = existsSync(ui1) ? ui1 : join(__dirname, '..', '..', 'ui');
```

Add:
```typescript
const dictDb1 = join(__dirname, '..', 'docs', 'explorer', 'data', 'dictionary.db');
const dictDb2 = join(__dirname, '..', '..', 'docs', 'explorer', 'data', 'dictionary.db');
const DICT_DB = existsSync(dictDb1) ? dictDb1 : existsSync(dictDb2) ? dictDb2 : null;
const dictDb = DICT_DB ? new Database(DICT_DB, { readonly: true }) : null;
```

- [ ] **Step 3: Add the /api/datasets route after /api/health**

After the /api/health block (after line 182):
```typescript
// Dataset list (no auth) — serves real ABS names from dictionary.db for the UI picker
app.get('/api/datasets', (_req, res) => {
  if (!dictDb) { res.status(503).json({ error: 'Dataset dictionary unavailable' }); return; }
  const rows = dictDb.prepare('SELECT id, name FROM datasets ORDER BY name').all() as Array<{ id: number; name: string }>;
  res.json(rows.map(r => ({ id: r.id, name: r.name, code: null, tag: null, year: null })));
});
```

- [ ] **Step 4: Run the tests**

```bash
npm test -- src/server.test.ts
```

Expected: all tests in server.test.ts pass.

- [ ] **Step 5: Run all tests to confirm no regressions**

```bash
npm test
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add package.json package-lock.json src/server.ts src/server.test.ts src/server.datasets.integration.test.ts
git commit -m "feat: add GET /api/datasets backed by dictionary.db"
```

---

## Chunk 2: Bug 1 — UI-side dataset picker

### Task 4: Guard d.code in form.jsx

**Files:**
- Modify: `ui/form.jsx:41` (fuzzy score line)
- Modify: `ui/form.jsx:102` (display row line)

The real ABS datasets returned by `/api/datasets` have `code: null`. Without guards, the fuzzy scorer calls `window.fuzzyScore(needle, null)` and the display renders `null · null · null`.

- [ ] **Step 1: Guard the fuzzy score line (line 41)**

Change:
```javascript
.map(d => ({ d, s: window.fuzzyScore(needle, d.name) + window.fuzzyScore(needle, d.code) * 0.5 }))
```

To:
```javascript
.map(d => ({ d, s: window.fuzzyScore(needle, d.name) + window.fuzzyScore(needle, d.code ?? '') * 0.5 }))
```

- [ ] **Step 2: Guard the display row (line 102)**

Change:
```jsx
<span className="s">{d.code} · {d.tag} · {d.year}</span>
```

To:
```jsx
{d.code && <span className="s">{d.code} · {d.tag} · {d.year}</span>}
```

- [ ] **Step 3: Verify the UI file parses correctly (no JSX syntax error)**

```bash
node --input-type=module --eval "
import { readFileSync } from 'fs';
const src = readFileSync('ui/form.jsx', 'utf8');
console.log('form.jsx read OK, length:', src.length);
"
```

Expected: prints length without error.

- [ ] **Step 4: Commit**

```bash
git add ui/form.jsx
git commit -m "fix: guard d.code nulls in DatasetPicker for real ABS dataset entries"
```

---

### Task 5: Fetch real datasets on mount in app.jsx

**Files:**
- Modify: `ui/app.jsx` — add `useE` hook inside `App()` after line 629

- [ ] **Step 1: Add the fetch-on-mount effect**

Inside `function App()`, after `const isLive = true;` (line 629), add:

```javascript
// Hydrate dataset picker with real names from server; keep mock DATASETS on failure
useE(() => {
  fetch('/api/datasets')
    .then(r => { if (!r.ok) throw new Error(r.status.toString()); return r.json(); })
    .then(data => { window.DATASETS = data; })
    .catch(() => { /* keep existing window.DATASETS mock */ });
}, []);
```

- [ ] **Step 2: Start the dev server and verify the picker shows real ABS names**

```bash
npm run serve
```

Open `http://localhost:3000` in a browser. Type "census 2021" in the Dataset field. The dropdown should show real ABS names like `"2021 Census - counting persons, place of usual residence"` rather than `"Census 2021 Persons Usual Residence"`.

- [ ] **Step 3: Commit**

```bash
git add ui/app.jsx
git commit -m "feat: hydrate dataset picker from /api/datasets on mount"
```

---

## Chunk 3: Bug 2 — Variable tree re-expansion

### Task 6: Write failing test for expandVariableGroups

**Files:**
- Modify: `src/shared/abs/navigator.test.ts` — add new describe block

- [ ] **Step 1: Read the current test file structure**

Run: `cat -n src/shared/abs/navigator.test.ts`

Confirm it ends after the `fuzzyMatchDataset` describe block.

- [ ] **Step 2: Add the expandVariableGroups test at the end of navigator.test.ts**

First, **edit the existing import at line 1** of `navigator.test.ts` — change:
```typescript
import { fuzzyMatchDataset } from './navigator.js';
```
To:
```typescript
import { fuzzyMatchDataset, expandVariableGroups } from './navigator.js';
```

Then **append** the following block at the end of the file:

```typescript
// ── Helpers to build mock Playwright nodes ───────────────────────────────────

function makeNode(label: string, expanderCls: string) {
  const clickFn = vi.fn().mockResolvedValue(undefined);
  return {
    locator: (sel: string) => {
      if (sel === '.label') {
        return { first: () => ({ textContent: vi.fn().mockResolvedValue(label) }) };
      }
      // '.treeNodeExpander'
      return {
        first: () => ({
          getAttribute: vi.fn().mockResolvedValue(expanderCls),
          click: clickFn,
        }),
      };
    },
    _click: clickFn,
  };
}

// makePage returns a stable locator object so spies on .all and .count
// are the same references that expandVariableGroups calls internally.
function makePage(nodes: ReturnType<typeof makeNode>[]) {
  const allFn = vi.fn().mockResolvedValue(nodes);
  const countFn = vi.fn().mockResolvedValue(nodes.length);
  const stableLocator = { all: allFn, count: countFn };
  return {
    locator: (_sel: string) => stableLocator,
    _allFn: allFn,
  };
}

const noopReporter = () => {};

describe('expandVariableGroups', () => {
  it('clicks collapsed non-skip non-variable group nodes', async () => {
    const collapsed = makeNode('Demographic Characteristics', 'collapsed');
    const expanded = makeNode('Dwelling Characteristics', 'expanded');
    const page = makePage([collapsed, expanded]);

    await expandVariableGroups(page as any, noopReporter, new AbortController().signal);

    expect(collapsed._click).toHaveBeenCalledOnce();
    expect(expanded._click).not.toHaveBeenCalled();
  });

  it('does not click collapsed nodes in SKIP_GROUPS', async () => {
    const geo = makeNode('Geographical Classification', 'collapsed');
    const seifa = makeNode('SEIFA Index 2021', 'collapsed');
    const saved = makeNode('My Saved Tables', 'collapsed');
    const page = makePage([geo, seifa, saved]);

    await expandVariableGroups(page as any, noopReporter, new AbortController().signal);

    expect(geo._click).not.toHaveBeenCalled();
    expect(seifa._click).not.toHaveBeenCalled();
    expect(saved._click).not.toHaveBeenCalled();
  });

  it('does not click variable-level nodes (matching isVarNode pattern)', async () => {
    // Variable nodes look like "SEXP Sex (2)" — matched by isVarNode
    const varNode = makeNode('SEXP Sex (2)', 'collapsed');
    const page = makePage([varNode]);

    await expandVariableGroups(page as any, noopReporter, new AbortController().signal);

    expect(varNode._click).not.toHaveBeenCalled();
  });

  it('breaks after a round with no new expansions', async () => {
    // All nodes already expanded — anyExpanded stays false → loop breaks after round 0
    const expanded = makeNode('Demographic Characteristics', 'expanded');
    const page = makePage([expanded]);

    await expandVariableGroups(page as any, noopReporter, new AbortController().signal);

    // _allFn is the spy for .all() only. makePage's stableLocator also has a separate
    // countFn spy for .count() — both share the same locator object but are distinct spies.
    // .all() is called exactly once (round 0 only — loop breaks immediately after no expansions).
    expect(page._allFn).toHaveBeenCalledTimes(1);
  });

  it('throws CancelledError when signal is aborted', async () => {
    const node = makeNode('Demographic Characteristics', 'collapsed');
    const page = makePage([node]);
    const ac = new AbortController();
    ac.abort();

    await expect(
      expandVariableGroups(page as any, noopReporter, ac.signal)
    ).rejects.toThrow('cancelled');
  });
});
```

- [ ] **Step 3: Run to confirm failure (expandVariableGroups not yet exported)**

```bash
npm test -- src/shared/abs/navigator.test.ts
```

Expected: FAIL — `expandVariableGroups is not exported from './navigator.js'` (or similar import error).

---

### Task 7: Implement expandVariableGroups in navigator.ts

**Files:**
- Modify: `src/shared/abs/navigator.ts`

The changes are:
1. Move `SKIP_GROUPS` and `isVarNode` to module scope (after the import block)
2. Extract lines 335–356 into `export async function expandVariableGroups`
3. Replace the inline block with a call to the new helper
4. Convert the `for...of` loop to `for (let i = 0; ...)` to get an index
5. After `submitJsfForm`, call `expandVariableGroups` when more variables remain

- [ ] **Step 1: Add module-scope constants after the imports (after line 6)**

After:
```typescript
import { noopReporter, NEVER_ABORT, CancelledError, type PhaseReporter } from './reporter.js';
```

Add:
```typescript
const SKIP_GROUPS = ['geographical', 'my saved tables', 'seifa'];
const isVarNode = (t: string) =>
  /^[A-Z][A-Z0-9]{3,}\s/.test(t) ||
  /^[A-Z][A-Z0-9]{2,}\s.+\(\d+\)\s*$/.test(t);
```

- [ ] **Step 2: Add the expandVariableGroups function**

Add a new exported function immediately before `selectVariables` (just before line 290):

```typescript
export async function expandVariableGroups(
  page: Page,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<void> {
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
        console.log(`expandVariableGroups: round ${round} expanding group '${rawText}'`);
        reporter({ type: 'log', level: 'info', message: `  expanded ${rawText}` });
        await expander.click();
        await new Promise(r => setTimeout(r, 1500));
        anyExpanded = true;
      }
    }
    const total = await page.locator('.treeNodeElement').count();
    console.log(`expandVariableGroups: round ${round} done, total DOM nodes: ${total}`);
    if (!anyExpanded) break;
  }
}
```

- [ ] **Step 3: Run tests — confirm they are GREEN before refactoring**

```bash
npm test -- src/shared/abs/navigator.test.ts
```

Expected: all `expandVariableGroups` tests pass. The existing `fuzzyMatchDataset` tests also pass. The inline block inside `selectVariables` still exists alongside the new function — that is fine at this stage.

- [ ] **Step 4: Remove SKIP_GROUPS and isVarNode from inside selectVariables**

Inside `selectVariables`, find and delete the four lines (currently ~330–333). They are now at module scope so deleting the local copies is safe:
```typescript
  const SKIP_GROUPS = ['geographical', 'my saved tables', 'seifa'];
  const isVarNode = (t: string) =>
    /^[A-Z][A-Z0-9]{3,}\s/.test(t) ||
    /^[A-Z][A-Z0-9]{2,}\s.+\(\d+\)\s*$/.test(t);
```

- [ ] **Step 5: Replace the inline expansion block with a call to expandVariableGroups**

Inside `selectVariables`, find the `for (let round = 0; round < 5; round++)` block (currently lines 335–356) and replace the entire block — including its two `console.log` lines — with a single call:

```typescript
  await expandVariableGroups(page, reporter, signal);
```

Keep the two lines before it (console.log of topGroupLabels) and the two lines after it (reporter phase_complete) — only the `for (let round...)` block is replaced.

- [ ] **Step 6: Convert the check+submit for...of loop to an indexed for loop**

Find (currently ~line 380):
```typescript
  for (const { name, axis } of assignments) {
```

Replace with:
```typescript
  for (let i = 0; i < assignments.length; i++) {
    const { name, axis } = assignments[i];
```

The closing `}` brace stays as-is.

- [ ] **Step 7: Add the re-expansion call after submitJsfForm**

After:
```typescript
    await submitJsfForm(page, axis);
    reporter({ type: 'log', level: 'info', message: `  POST /TableBuilder/view/layout → 202 accepted for ${name}` });
```

Add:
```typescript
    // Re-expand the variable tree after page reload so the next variable is findable.
    // submitJsfForm already awaits waitForLoadState('load') so the DOM is stable here.
    if (i < assignments.length - 1) {
      await expandVariableGroups(page, reporter, signal);
    }
```

After this step the end of the loop should look like (confirm brace nesting is correct):
```typescript
    if (i < assignments.length - 1) {
      await expandVariableGroups(page, reporter, signal);
    }
  }  // ← closes the for (let i ...) loop

  reporter({ type: 'log', level: 'ok', message: '  ✓ all dimensions submitted' });
```

- [ ] **Step 8: Run the navigator tests**

```bash
npm test -- src/shared/abs/navigator.test.ts
```

Expected: all tests pass (both the existing fuzzyMatchDataset tests and the new expandVariableGroups tests).

- [ ] **Step 9: Run all tests**

```bash
npm test
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add src/shared/abs/navigator.ts src/shared/abs/navigator.test.ts
git commit -m "fix: re-expand variable tree after each JSF form submit"
```

---

## Final verification

- [ ] **Run the full test suite one last time**

```bash
npm test
```

Expected: all tests pass with no warnings.

- [ ] **Confirm the two bugs are fixed**

Bug 1 — Dataset picker: Start the server (`npm run serve`), open the UI, type in the dataset field. Confirm real ABS names appear (e.g. `"2021 Census - counting persons, place of usual residence"`).

Bug 2 — Tree reset: If you have ABS credentials, run an E2E test with two row variables (e.g. rows: `["Sex", "Age"]`). The second variable should be found and checked without `"Variable 'Age' not found in tree."` error.
