# Runner UI ↔ dictionary.db Integration Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded variable list and `.slice(0, 7)` cap in the TableBuilder UI with dataset-aware pickers fed by `dictionary.db`. Add geography selection that drives the runner. Normalize geographies into a real table.

**Architecture:** Four-layer change — DB schema (drop `geographies_json`, add `geographies` table), server (new metadata endpoint + boot guard + extended validator), runner (`selectGeography` step), UI (dataset-store cache + dataset-aware autocomplete + geography select + browse modal).

**Tech Stack:** TypeScript ESM, better-sqlite3, Express, vitest + supertest, Playwright. JSX-no-build UI loaded via Babel-standalone with `window.*` globals convention.

**Spec:** `docs/superpowers/specs/2026-04-28-runner-ui-db-integration-design.md`

---

## File Map

| File | Change |
|------|--------|
| `src/dict-builder/assembler.ts` | Drop `geographies_json` column, add `geographies` table + insert step |
| `src/dict-builder/assembler.test.ts` | Add geography round-trip tests |
| `src/server.ts` | Add boot guard, `/api/datasets/:id/metadata` endpoint, extended validator |
| `src/server.test.ts` (or new `metadata.test.ts`) | Tests for endpoint + validator |
| `src/shared/abs/navigator.ts` | Add `selectGeography(page, label)` |
| `src/runner.ts` | Pass geography through, call `selectGeography` when set |
| `ui/dataset-store.js` | NEW — `window.DatasetStore.loadMetadata(id)` |
| `ui/dataset-store.test.js` | NEW — vitest unit tests via JSDOM |
| `ui/data.js` | Delete `VARIABLES`; add `geography` to `PHASES` |
| `ui/index.html` | Add `<script src="dataset-store.js">` before JSX |
| `ui/form.jsx` | Drop `.slice(0, 7)`; metadata-driven autocomplete; payload `{id,label}`; group headers |
| `ui/app.jsx` | Add geography state; clear-on-dataset-change; race ref; payload includes geography |
| `ui/browse-modal.jsx` | NEW — tree picker for variables |
| `tests/e2e/picker.spec.ts` (or similar) | E2E Playwright tests against the UI |

---

## Chunks

- **Chunk 1: DB schema** — Tasks 1-2
- **Chunk 2: Server (endpoint + validator + boot guard)** — Tasks 3-5
- **Chunk 3: Runner** — Task 6
- **Chunk 4: UI plumbing** — Tasks 7-8
- **Chunk 5: UI form rewire** — Tasks 9-12
- **Chunk 6: E2E + deploy** — Tasks 13-14

---

## Chunk 1: DB schema

### Task 1: Update assembler to write geographies as rows

**Files:**
- Modify: `src/dict-builder/assembler.ts`
- Modify: `src/dict-builder/assembler.test.ts`

**Context:** `assembler.ts:9` defines `SCHEMA_SQL`. Currently `datasets` has `geographies_json TEXT NOT NULL DEFAULT '[]'`. We replace that column with a separate `geographies` table. The insert step at line 105-107 currently `JSON.stringify(d.geographies)`s into `geographies_json`; we change it to insert one row per geography label into the new table.

- [ ] **Step 1: Write failing test for geographies table**

In `src/dict-builder/assembler.test.ts`, add:

```ts
import Database from 'better-sqlite3';

it('writes geographies as rows in geographies table', async () => {
  const cacheDir = await mkdtemp(...);  // existing pattern
  const fixture: ExtractedDataset = {
    dataset_name: '2021 Census - test',
    geographies: ['Australia (UR)', 'LGA (2021 Boundaries) (UR)'],
    groups: [{ label: 'G', path: 'G', variables: [{ code: 'X', label: 'X', categories: [], category_count: 0 }] }],
  };
  await writeSuccess(cacheDir, fixture);
  const dbPath = join(cacheDir, 'test.db');
  await build(cacheDir, dbPath);
  const db = new Database(dbPath, { readonly: true });
  const rows = db.prepare('SELECT label FROM geographies WHERE dataset_id = 1 ORDER BY id').all();
  expect(rows).toEqual([{ label: 'Australia (UR)' }, { label: 'LGA (2021 Boundaries) (UR)' }]);
  db.close();
});

it('does not have geographies_json column', async () => {
  const cacheDir = await mkdtemp(...);
  await writeSuccess(cacheDir, { dataset_name: 'T', geographies: [], groups: [] });
  const dbPath = join(cacheDir, 'test.db');
  await build(cacheDir, dbPath);
  const db = new Database(dbPath, { readonly: true });
  const cols = db.prepare("PRAGMA table_info(datasets)").all() as Array<{name:string}>;
  expect(cols.find(c => c.name === 'geographies_json')).toBeUndefined();
  db.close();
});
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd /Users/dewoller/code/rmai/tablebuilder
npx vitest run src/dict-builder/assembler.test.ts
```
Expected: 2 new tests fail.

- [ ] **Step 3: Update SCHEMA_SQL in assembler.ts**

Replace the `datasets` definition and add the new `geographies` table:

```ts
const SCHEMA_SQL = `
CREATE TABLE datasets (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE geographies (
  id INTEGER PRIMARY KEY,
  dataset_id INTEGER NOT NULL REFERENCES datasets(id),
  label TEXT NOT NULL
);
CREATE TABLE groups (
  id INTEGER PRIMARY KEY,
  dataset_id INTEGER NOT NULL REFERENCES datasets(id),
  label TEXT NOT NULL,
  path TEXT NOT NULL
);
CREATE TABLE variables (
  id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES groups(id),
  code TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL,
  category_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE categories (
  id INTEGER PRIMARY KEY,
  variable_id INTEGER NOT NULL REFERENCES variables(id),
  label TEXT NOT NULL
);
CREATE INDEX idx_geographies_dataset ON geographies(dataset_id);
CREATE INDEX idx_groups_dataset ON groups(dataset_id);
CREATE INDEX idx_variables_group ON variables(group_id);
CREATE INDEX idx_categories_variable ON categories(variable_id);
`;
```

Update `insertDataset` prepare call:

```ts
const insertDataset = db.prepare(
  'INSERT INTO datasets (name, summary) VALUES (?, ?)',
);
const insertGeography = db.prepare(
  'INSERT INTO geographies (dataset_id, label) VALUES (?, ?)',
);
```

Update the per-dataset transaction to insert geographies as rows:

```ts
const datasetId = insertDataset.run(d.dataset_name, '').lastInsertRowid as number;
for (const geo of d.geographies) {
  insertGeography.run(datasetId, geo);
}
for (const g of d.groups) {
  // ... existing
}
```

- [ ] **Step 4: Run all assembler tests — expect pass**

```bash
npx vitest run src/dict-builder/assembler.test.ts
```
Expected: all tests pass, including the new two.

- [ ] **Step 5: Run full test suite to catch regressions**

```bash
npm test
```
Expected: all pass.

- [ ] **Step 6: Type-check**

```bash
npx tsc --noEmit
```
Expected: zero errors.

- [ ] **Step 7: Commit**

```bash
git add src/dict-builder/assembler.ts src/dict-builder/assembler.test.ts
git commit -m "$(cat <<'EOF'
feat(assembler): normalize geographies into separate table

Replaces datasets.geographies_json blob with a geographies table
mirroring the groups/variables/categories pattern. Cache layer is
unchanged — only assembly inserts as rows now.

Co-Authored-By: <author>
EOF
)"
```

### Task 2: Reassemble totoro DB

**Context:** Cache JSONs already carry geography lists; only the assembly step needs rerunning. `--assemble-only` is the right flag.

- [ ] **Step 1: Push to GitHub**

```bash
git push origin main
```

- [ ] **Step 2: Pull on totoro and reassemble**

```bash
ssh totoro_ts 'cd /tank/code/tablebuilder && git pull && xvfb-run -a npx tsx scripts/build-dict.ts --assemble-only'
```

- [ ] **Step 3: Verify schema**

```bash
ssh totoro_ts 'sqlite3 /tank/code/tablebuilder/docs/explorer/data/dictionary.db "SELECT name FROM sqlite_master WHERE type=\"table\";"'
```
Expected: includes `geographies`, does not include `geographies_json` (column-level — verify via `PRAGMA table_info(datasets)`).

```bash
ssh totoro_ts 'sqlite3 /tank/code/tablebuilder/docs/explorer/data/dictionary.db "SELECT count(*) FROM geographies; SELECT count(DISTINCT dataset_id) FROM geographies;"'
```
Expected: ≥1000 total geographies, ≥150 datasets with at least one geography.

- [ ] **Step 4: DO NOT restart service yet** — server still expects old schema. Service restart happens in Chunk 2.

---

## Chunk 2: Server (endpoint + validator + boot guard)

### Task 3: Boot guard for `geographies` table

**Files:**
- Modify: `src/server.ts`
- Modify: `src/server.test.ts` (or create `src/metadata.test.ts`)

**Context:** Server should detect if the DB is missing the `geographies` table at startup and serve 503 from the metadata endpoint with a clear message. The existing pattern at `server.ts:27` opens `dictDb`; we add a flag right after.

- [ ] **Step 1: Write failing test**

```ts
it('reports schema-out-of-date when geographies table is missing', async () => {
  // Build a fixture DB with the OLD schema (geographies_json column)
  const oldDb = new Database(':memory:');
  oldDb.exec(`CREATE TABLE datasets (id INTEGER PRIMARY KEY, name TEXT, geographies_json TEXT)`);
  // ... insert one dataset
  // App startup with this DB
  const app = createApp({ dictDb: oldDb });  // assuming injectable
  const r = await request(app).get('/api/datasets/1/metadata');
  expect(r.status).toBe(503);
  expect(r.body.error).toMatch(/out of date|reassembly/i);
});
```

If the server isn't currently structured for injection, refactor `createApp(deps)` minimally — only what's needed to inject `dictDb`. Don't refactor more.

- [ ] **Step 2: Implement the guard**

In `src/server.ts` after line 27:

```ts
function hasGeographiesTable(db: Database.Database | null): boolean {
  if (!db) return false;
  const row = db.prepare(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='geographies'"
  ).get();
  return row != null;
}
const dictReady = hasGeographiesTable(dictDb);
if (dictDb && !dictReady) {
  console.warn('[server] dictionary.db is missing the geographies table — needs reassembly');
}
```

Then in the metadata endpoint (added in Task 4), check `dictReady` first.

- [ ] **Step 3: Run test — expect pass**

```bash
npx vitest run <test file>
```

- [ ] **Step 4: Commit**

```bash
git add <files>
git commit -m "feat(server): add boot guard for geographies table"
```

### Task 4: Add `/api/datasets/:id/metadata` endpoint

**Files:**
- Modify: `src/server.ts`
- Modify: server tests

**Context:** Endpoint sits between `/api/datasets` (line 190) and `/api/run` (line 197). No auth, mirrors `/api/datasets`.

- [ ] **Step 1: Write failing tests**

```ts
it('returns metadata for a known dataset', async () => {
  const r = await request(app).get('/api/datasets/1/metadata');
  expect(r.status).toBe(200);
  expect(r.body).toMatchObject({
    id: 1,
    name: expect.any(String),
    geographies: expect.arrayContaining([
      expect.objectContaining({ id: expect.any(Number), label: expect.any(String) }),
    ]),
    groups: expect.arrayContaining([
      expect.objectContaining({
        id: expect.any(Number),
        label: expect.any(String),
        variables: expect.arrayContaining([
          expect.objectContaining({ id: expect.any(Number), code: expect.any(String), label: expect.any(String) }),
        ]),
      }),
    ]),
  });
});

it('returns 404 for unknown dataset id', async () => {
  const r = await request(app).get('/api/datasets/999999/metadata');
  expect(r.status).toBe(404);
  expect(r.body.error).toBe('Unknown dataset');
});

it('returns 503 when dictDb is null', async () => {
  const app = createApp({ dictDb: null });
  const r = await request(app).get('/api/datasets/1/metadata');
  expect(r.status).toBe(503);
});
```

- [ ] **Step 2: Implement endpoint**

After line 194 in `src/server.ts`:

```ts
app.get('/api/datasets/:id/metadata', (req, res) => {
  if (!dictDb) { res.status(503).json({ error: 'Dataset dictionary unavailable' }); return; }
  if (!dictReady) { res.status(503).json({ error: 'Dictionary out of date — needs reassembly' }); return; }

  const id = Number(req.params.id);
  if (!Number.isFinite(id)) { res.status(400).json({ error: 'id must be a number' }); return; }

  const dataset = dictDb.prepare('SELECT id, name FROM datasets WHERE id = ?').get(id) as { id: number; name: string } | undefined;
  if (!dataset) { res.status(404).json({ error: 'Unknown dataset' }); return; }

  const geographies = dictDb.prepare(
    'SELECT id, label FROM geographies WHERE dataset_id = ? ORDER BY id'
  ).all(id) as Array<{ id: number; label: string }>;

  const groupRows = dictDb.prepare(
    'SELECT id, label FROM groups WHERE dataset_id = ? ORDER BY id'
  ).all(id) as Array<{ id: number; label: string }>;

  const variablesByGroup = dictDb.prepare(
    'SELECT id, group_id, code, label FROM variables WHERE group_id IN (SELECT id FROM groups WHERE dataset_id = ?) ORDER BY label'
  ).all(id) as Array<{ id: number; group_id: number; code: string; label: string }>;

  const groups = groupRows.map(g => ({
    id: g.id,
    label: g.label,
    variables: variablesByGroup
      .filter(v => v.group_id === g.id)
      .map(v => ({ id: v.id, code: v.code, label: v.label })),
  }));

  res.json({ id: dataset.id, name: dataset.name, geographies, groups });
});
```

- [ ] **Step 3: Run tests, type-check, commit**

```bash
npx vitest run
npx tsc --noEmit
git add src/server.ts <test file>
git commit -m "feat(server): add GET /api/datasets/:id/metadata"
```

### Task 5: Extend `/api/run` validator for geography + variable ids

**Files:**
- Modify: `src/server.ts` (`validateBody` at line 47)
- Modify: server tests

**Context:** Today validator handles `dataset`, `rows`, `cols`, `wafer` as string arrays. We change all three buckets to `Array<{id: number; label: string}>` and add `geography: {id, label} | null`. Validator additionally checks each id resolves in the DB for the given dataset.

- [ ] **Step 1: Write failing tests**

```ts
it('accepts {id,label} objects in rows/cols/wafer', () => { /* ... */ });
it('rejects unknown variable id', () => { /* ... */ });
it('rejects unknown geography id', () => { /* ... */ });
it('treats null geography and missing geography identically', () => { /* ... */ });
```

- [ ] **Step 2: Update `validateBody` and `Input` type**

```ts
interface Input {
  dataset: string;
  rows: Array<{ id: number; label: string }>;
  columns: Array<{ id: number; label: string }>;
  wafers: Array<{ id: number; label: string }>;
  geography: { id: number; label: string } | null;
  outputPath?: string;
}

function isVarRef(x: unknown): x is { id: number; label: string } {
  return !!x && typeof x === 'object'
    && typeof (x as any).id === 'number'
    && typeof (x as any).label === 'string'
    && (x as any).label.trim().length > 0;
}

function validateBody(body: unknown): { ok: true; input: Input } | { ok: false; error: string; field?: string } {
  // ... existing dataset check
  for (const field of ['rows', 'cols', 'wafer'] as const) {
    const v = (b as any)[field];
    if (field === 'rows' && (!Array.isArray(v) || v.length === 0)) {
      return { ok: false, error: 'rows must be non-empty', field: 'rows' };
    }
    if (Array.isArray(v) && !v.every(isVarRef)) {
      return { ok: false, error: `${field} entries must be {id, label}`, field };
    }
  }
  const geography = b.geography === null || b.geography === undefined
    ? null
    : isVarRef(b.geography) ? b.geography : 'INVALID';
  if (geography === 'INVALID') return { ok: false, error: 'geography must be {id, label} or null', field: 'geography' };
  // ...build input
}
```

DB validation happens at `/api/run` handler (after `validateBody`):

```ts
if (dictDb && dictReady) {
  const dsRow = dictDb.prepare('SELECT id FROM datasets WHERE name = ?').get(validation.input.dataset) as {id:number}|undefined;
  if (!dsRow) { res.status(400).json({ error: 'Unknown dataset', field: 'dataset' }); return; }
  const allVarIds = [...validation.input.rows, ...validation.input.columns, ...validation.input.wafers].map(v => v.id);
  if (allVarIds.length) {
    const rows = dictDb.prepare(`
      SELECT v.id FROM variables v JOIN groups g ON g.id = v.group_id
      WHERE g.dataset_id = ? AND v.id IN (${allVarIds.map(() => '?').join(',')})
    `).all(dsRow.id, ...allVarIds) as {id:number}[];
    if (rows.length !== allVarIds.length) {
      res.status(400).json({ error: 'Unknown variable id for this dataset', field: 'variables' });
      return;
    }
  }
  if (validation.input.geography) {
    const g = dictDb.prepare('SELECT id FROM geographies WHERE id = ? AND dataset_id = ?').get(validation.input.geography.id, dsRow.id);
    if (!g) { res.status(400).json({ error: 'Unknown geography for this dataset', field: 'geography' }); return; }
  }
}
```

- [ ] **Step 3: Run tests, type-check, commit**

---

## Chunk 3: Runner

### Task 6: Add `selectGeography` and wire into runner

**Files:**
- Modify: `src/shared/abs/navigator.ts`
- Modify: `src/runner.ts`
- Modify: existing runner test (if applicable; otherwise gate on E2E)

**Context:** `selectDataset` already exists in `navigator.ts`. Geography selection follows: open the JSF tree, locate the geography release node by label, click it. Re-uses `expandAllCollapsed` patterns.

- [ ] **Step 1: Implement `selectGeography(page, label)`**

Add to `src/shared/abs/navigator.ts`:

```ts
export async function selectGeography(page: Page, label: string, reporter?: PhaseReporter): Promise<void> {
  reporter?.phase('geography', 'selecting geography release');
  const searchBox = page.locator('#searchPattern, input[id*="searchPattern"]').first();
  if (!(await searchBox.isVisible().catch(() => false))) {
    throw new Error(`selectGeography: search box not visible — geography selection requires tableView page`);
  }
  await searchBox.fill(label);
  await page.waitForTimeout(800);  // JSF AJAX debounce
  // The geography tree node should now be visible. Click the leaf with this label.
  const node = page.locator('.treeNodeContent', { hasText: label }).first();
  if (!(await node.isVisible({ timeout: 10_000 }).catch(() => false))) {
    throw new Error(`selectGeography: no tree node found for "${label}"`);
  }
  await node.click();
  await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => null);
  // Clear the search so the user can see the full variable tree afterward
  await searchBox.fill('');
}
```

(Implementation may need adjustment based on actual JSF DOM — start here and refine during E2E. Mark with TODO if a follow-up is needed.)

- [ ] **Step 2: Wire into runner**

In `src/runner.ts`, after `selectDataset` and before category selection:

```ts
if (input.geography) {
  await selectGeography(page, input.geography.label, reporter);
}
```

- [ ] **Step 3: Type-check, commit**

```bash
npx tsc --noEmit
git add src/shared/abs/navigator.ts src/runner.ts
git commit -m "feat(runner): selectGeography step navigates JSF to chosen release"
```

(Real verification deferred to runner E2E in Chunk 6.)

---

## Chunk 4: UI plumbing

### Task 7: Create `dataset-store.js` + tests

**Files:**
- Create: `ui/dataset-store.js`
- Create: `ui/dataset-store.test.js`

- [ ] **Step 1: Write failing tests**

```js
// vitest, JSDOM environment
import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('DatasetStore.loadMetadata', () => {
  beforeEach(() => {
    delete window.DatasetStore;
    require('./dataset-store.js');  // populates window.DatasetStore
    global.fetch = vi.fn();
  });

  it('fetches once per id and caches', async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => ({ id: 1, name: 'x', geographies: [], groups: [] }) });
    const a = await window.DatasetStore.loadMetadata(1);
    const b = await window.DatasetStore.loadMetadata(1);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(a).toEqual(b);
  });

  it('rejects on non-OK and clears cache', async () => {
    fetch.mockResolvedValueOnce({ ok: false, status: 404 });
    await expect(window.DatasetStore.loadMetadata(1)).rejects.toThrow(/404/);
    fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1, name: 'x', geographies: [], groups: [] }) });
    const r = await window.DatasetStore.loadMetadata(1);  // retry should hit fetch again
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
```

- [ ] **Step 2: Implement `ui/dataset-store.js`**

```js
window.DatasetStore = (() => {
  const cache = new Map();
  function loadMetadata(datasetId) {
    if (cache.has(datasetId)) return cache.get(datasetId);
    const p = fetch(`/api/datasets/${datasetId}/metadata`)
      .then(r => {
        if (!r.ok) {
          cache.delete(datasetId);
          throw new Error(`metadata fetch failed: ${r.status}`);
        }
        return r.json();
      })
      .catch(e => { cache.delete(datasetId); throw e; });
    cache.set(datasetId, p);
    return p;
  }
  return { loadMetadata };
})();
```

- [ ] **Step 3: Run tests, commit**

### Task 8: Wire dataset-store.js into index.html

**Files:**
- Modify: `ui/index.html`

- [ ] **Step 1: Add script tag**

Locate the line `<script src="data.js"></script>` (around line 18) and add immediately after:

```html
<script src="dataset-store.js"></script>
```

- [ ] **Step 2: Verify**

Smoketest: load the UI locally; in browser console `typeof window.DatasetStore.loadMetadata` should be `'function'`.

```bash
npm run serve  # or whatever starts dev server
# Then in browser console: window.DatasetStore.loadMetadata(1).then(console.log)
```

- [ ] **Step 3: Commit**

---

## Chunk 5: UI form rewire

### Task 9: Replace `window.VARIABLES` with metadata-driven autocomplete

**Files:**
- Modify: `ui/data.js` (delete `VARIABLES`, update `PHASES`)
- Modify: `ui/form.jsx`
- Modify: `ui/app.jsx`

**Context:** `form.jsx:120-127` has the `suggestions` useMemo with `.slice(0, 7)`. `app.jsx:114-116` defines the three buckets (`rows`, `cols`, `wafer`) initialized from `initial?.rows ?? []`.

- [ ] **Step 1: Update bucket type to `{id, label}` objects**

In `app.jsx:114-116`:

```jsx
const [rows, setRows] = useS(initial?.rows || []);    // now Array<{id, label}>
const [cols, setCols] = useS(initial?.cols || []);
const [wafer, setWafer] = useS(initial?.wafer || []);
```

(Type stays loose — JSX has no formal type.)

- [ ] **Step 2: Add metadata + race ref to form**

```jsx
const [metadata, setMetadata] = useS(null);
const [metaLoading, setMetaLoading] = useS(false);
const currentDatasetIdRef = useRef(null);

useEffect(() => {
  if (!datasetId) { setMetadata(null); return; }
  currentDatasetIdRef.current = datasetId;
  setMetaLoading(true);
  window.DatasetStore.loadMetadata(datasetId).then(m => {
    if (currentDatasetIdRef.current !== datasetId) return;  // stale
    setMetadata(m);
  }).catch(e => {
    if (currentDatasetIdRef.current !== datasetId) return;
    console.error('metadata load failed', e);
    setMetadata(null);
  }).finally(() => {
    if (currentDatasetIdRef.current === datasetId) setMetaLoading(false);
  });
}, [datasetId]);

// On dataset change, clear selections
useEffect(() => { setRows([]); setCols([]); setWafer([]); setGeography(null); }, [datasetId]);
```

- [ ] **Step 3: Rewrite TagInput suggestions to use metadata**

In `form.jsx`, the `TagInput` component (or wherever line 123-127 lives):

```jsx
const suggestions = useMemo(() => {
  if (!metadata) return [];
  const needle = draft.trim().toLowerCase();
  const taken = new Set(value.map(v => v.label.toLowerCase()));
  const out = [];
  for (const grp of metadata.groups) {
    for (const v of grp.variables) {
      if (taken.has(v.label.toLowerCase())) continue;
      if (needle && !v.label.toLowerCase().includes(needle) && !v.code.toLowerCase().includes(needle)) continue;
      out.push({ id: v.id, label: v.label, code: v.code, group: grp.label });
      if (out.length >= 50) break;
    }
    if (out.length >= 50) break;
  }
  return out;
}, [draft, value, metadata]);
```

(Note: `metadata` must be passed into `TagInput` as a prop. If it's a separate component, thread it through.)

The dropdown markup shows the group as a header before each suggestion or as a small label next to the suggestion text.

- [ ] **Step 4: Update `add(v)` to push `{id, label}`**

When the user picks a suggestion:

```jsx
function add(suggestion) {
  if (!suggestion) return;
  const exists = value.some(x => x.id === suggestion.id);
  if (exists) { setDraft(""); return; }
  onChange([...value, { id: suggestion.id, label: suggestion.label }]);
  setDraft("");
}
```

- [ ] **Step 5: Delete `VARIABLES` from `data.js`**

Remove lines 9-30. Keep `PHASES`, `SEED_HISTORY`, formatters.

- [ ] **Step 6: Update display anywhere that reads `.length` of bucket** — string vs object access. Search for `rows.length`, `cols.length`, `wafer.length` — these still work. Search for code that joins/maps bucket items as strings (e.g. `app.jsx:443 [...item.rows, ...item.cols].join(...)`):

```jsx
[...item.rows, ...item.cols].map(v => v.label).join(" × ")
```

- [ ] **Step 7: Update history/payload references**

Where the form payload is built (around `app.jsx:36-37, 137`):

```jsx
{
  dataset, rows, cols, wafer, geography,  // all already objects/objects-array
  // ...
}
```

History entries (`SEED_HISTORY`, run-result storage) — store `{id, label}` objects. Migrating any localStorage history is out of scope; users may see "[object Object]" in old history entries. Acceptable.

- [ ] **Step 8: Run tests, type-check, smoketest in browser**

```bash
npm test
npx tsc --noEmit
npm run serve  # manual: pick a dataset, autocomplete should populate from metadata
```

Manual checks:
- Pick "2021 Census - cultural diversity"
- Type "ancestry" in row picker → ≥1 result, group label visible
- Type "a" → many results (>>7), confirming the cap is gone
- `grep -c 'slice(0, 7)' ui/form.jsx` returns 0

- [ ] **Step 9: Commit**

### Task 10: Add geography `<select>` to form

**Files:**
- Modify: `ui/form.jsx`
- Modify: `ui/app.jsx` (add `geography` state + payload)

- [ ] **Step 1: Add geography state in app.jsx**

```jsx
const [geography, setGeography] = useS(null);  // {id, label} | null
```

- [ ] **Step 2: Render `<select>` in form.jsx**

Place between dataset picker and tag inputs:

```jsx
<label>
  Geography
  <select
    value={geography?.id ?? ""}
    onChange={e => {
      const id = e.target.value;
      if (!id) { setGeography(null); return; }
      const g = metadata.geographies.find(x => x.id === Number(id));
      setGeography(g ? { id: g.id, label: g.label } : null);
    }}
    disabled={!metadata || metaLoading}
  >
    <option value="">(no geography selected)</option>
    {metadata?.geographies?.map(g => (
      <option key={g.id} value={g.id}>{g.label}</option>
    ))}
  </select>
</label>
```

- [ ] **Step 3: Include in payload**

In `app.jsx` submit (line 32-39):

```jsx
fetch('/api/run', {
  method: 'POST',
  body: JSON.stringify({
    dataset: request.dataset,
    rows: request.rows,
    cols: request.cols,
    wafer: request.wafer,
    geography: request.geography,
  }),
});
```

- [ ] **Step 4: Smoketest, commit**

### Task 11: Add `<BrowseModal>` for variable selection

**Files:**
- Create: `ui/browse-modal.jsx`
- Modify: `ui/index.html` (add script tag)
- Modify: `ui/form.jsx` (add Browse button per bucket)

- [ ] **Step 1: Create `ui/browse-modal.jsx`**

Single component, rendered conditionally. Props: `metadata`, `selectedIds: Set<number>`, `onApply(newIds: Set<number>): void`, `onCancel(): void`.

UI: backdrop + dialog. Each group shown as a collapsible section (default collapsed). Each variable a checkbox. "Apply" button writes selection back. "Cancel" or backdrop click discards.

```jsx
window.BrowseModal = function BrowseModal({ metadata, initialSelected, onApply, onCancel }) {
  const [selected, setSelected] = React.useState(new Set(initialSelected));
  const [openGroups, setOpenGroups] = React.useState(new Set());
  // ... render
};
```

(Full component code — keep under 100 lines. Layout uses existing CSS classes if any; otherwise inline style.)

- [ ] **Step 2: Add script tag in index.html**

After `<script src="dataset-store.js"></script>`:

```html
<script type="text/babel" src="browse-modal.jsx"></script>
```

- [ ] **Step 3: Wire Browse button into TagInput in form.jsx**

```jsx
<button type="button" onClick={() => setBrowseOpen(true)}>Browse</button>
{browseOpen && metadata && (
  <window.BrowseModal
    metadata={metadata}
    initialSelected={new Set(value.map(v => v.id))}
    onApply={ids => {
      const lookup = new Map();
      for (const g of metadata.groups) for (const v of g.variables) lookup.set(v.id, v);
      onChange([...ids].map(id => ({ id, label: lookup.get(id).label })));
      setBrowseOpen(false);
    }}
    onCancel={() => setBrowseOpen(false)}
  />
)}
```

- [ ] **Step 4: Smoketest, commit**

Manual: open modal, expand "Cultural Diversity" group, check 2 variables, click Apply. Confirm both appear in the bucket as tags.

### Task 12: Update PHASES with geography step

**Files:**
- Modify: `ui/data.js`

- [ ] **Step 1: Insert `geography` between `dataset` and `tree`**

```js
const PHASES = [
  { id: "login",     label: "Logging in", ... },
  { id: "dataset",   label: "Selecting dataset", ... },
  { id: "geography", label: "Selecting geography", sub: "navigating classification release", est: 4.0 },
  { id: "tree",      label: "Expanding variable tree", ... },
  // ... rest
];
```

The runner emits the `geography` event only when a geography is selected; the UI's phase tracker should treat "skipped" the same as "completed" if no event arrives (existing pattern, no change).

- [ ] **Step 2: Commit**

---

## Chunk 6: E2E + deploy

### Task 13: E2E Playwright tests

**Files:**
- Create: `tests/e2e/picker.spec.ts`

**Context:** Tests run against the local Express server with the new dictionary.db. Login is required — read credentials from `.env` or skip with `test.skip` if absent.

- [ ] **Step 1: Write tests**

```ts
import { test, expect } from '@playwright/test';

const BASE = 'http://localhost:3000';

test('cultural diversity picker shows >7 results for "a"', async ({ page }) => {
  await page.goto(BASE);
  // login if redirected
  // ...
  await page.fill('input[placeholder*="Dataset"]', '2021 Census - cultural diversity');
  await page.click('text=2021 Census - cultural diversity');
  await page.waitForFunction(() => window.DatasetStore && document.querySelector('select[disabled]') === null);
  await page.fill('input[placeholder*="Sex, Age"]', 'a');
  const items = await page.locator('.ac__item').all();
  expect(items.length).toBeGreaterThan(7);
});

test('geography dropdown contains LGA (2021 Boundaries)', async ({ page }) => {
  // similar setup
  const opts = await page.locator('select option').allTextContents();
  expect(opts).toEqual(expect.arrayContaining([
    expect.stringMatching(/LGA \(2021 Boundaries\)/)
  ]));
});

test('browse modal lists ≥10 groups', async ({ page }) => {
  // similar setup
  await page.click('button:has-text("Browse")');
  const groups = await page.locator('.browse-group-header').all();
  expect(groups.length).toBeGreaterThanOrEqual(10);
});

test('source: no slice(0, 7) remains in form.jsx', async () => {
  const fs = await import('fs/promises');
  const text = await fs.readFile('ui/form.jsx', 'utf8');
  expect(text).not.toContain('slice(0, 7)');
});
```

- [ ] **Step 2: Run E2E**

```bash
npm run serve &
npx playwright test tests/e2e/picker.spec.ts
```

Expected: 4 pass.

- [ ] **Step 3: Commit**

### Task 14: Deploy to totoro + manual smoketest

**Context:** This is a manual operational step — DO NOT delegate to a subagent. Run with the user.

- [ ] **Step 1: Push everything**

```bash
git push origin main
```

- [ ] **Step 2: Deploy on totoro**

```bash
ssh totoro_ts 'cd /tank/code/tablebuilder && git pull && sudo systemctl restart tablebuilder.service && sleep 2 && sudo systemctl status tablebuilder.service --no-pager -l | head -5'
```

- [ ] **Step 3: Hit the live URL**

Browse to `https://tablebuilder.realmindsai.com.au/`, log in, pick "2021 Census - cultural diversity":
- Geography dropdown shows ~25 options including "LGA (2021 Boundaries) (UR)"
- Type "a" in row picker → many results (no longer 7)
- Browse button opens modal with all 10 groups
- Submit a 1-variable run (Sex) without geography → succeeds

- [ ] **Step 4: Run runner E2E with geography (manual)**

Submit a run with `geography = LGA (2021 Boundaries) (UR)` and `rows = [Sex]`. Wait for completion. Inspect the resulting CSV — assert ≥500 rows (LGA-level).

If `selectGeography` fails on real ABS DOM: capture the page state, refine the locator, ship a fix.

---

## Verification (final)

Acceptance criteria from spec:

- [ ] DB has `geographies` table; `geographies_json` column gone (Tasks 1-2)
- [ ] `GET /api/datasets/:id/metadata` returns expected shape (Task 4)
- [ ] Server boot guard returns 503 if `geographies` missing (Task 3)
- [ ] `/api/run` validator rejects unknown variable/geography ids (Task 5)
- [ ] Cultural-diversity picker shows >7 results for broad query (Task 9 + Task 13)
- [ ] `.slice(0, 7)` is gone from form.jsx (Task 9 + Task 13)
- [ ] Browse modal lists ≥10 groups for cultural diversity (Task 11 + Task 13)
- [ ] Runner navigates to LGA when selected; result CSV has ≥500 rows (Task 6 + Task 14)
