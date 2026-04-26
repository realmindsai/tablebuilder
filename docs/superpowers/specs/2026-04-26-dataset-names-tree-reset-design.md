# Design: Dataset Names + Variable Tree Reset

**Date:** 2026-04-26
**Status:** Approved

---

## Problem

Two independent bugs prevent reliable multi-variable table builds against the real ABS TableBuilder site.

### Bug 1 — Mock dataset names in UI picker

`ui/data.js` contains a `DATASETS` array with simplified mock names (e.g. `"Census 2021 Persons Usual Residence"`). The real ABS catalogue uses a different vocabulary (e.g. `"2021 Census - counting persons, place of usual residence"`). When a user picks a dataset from the UI, the selected name is passed as the fuzzy-match query in `navigator.ts:fuzzyMatchDataset`. Because the mock name does not overlap well with real ABS names, the fuzzy matcher picks the wrong dataset.

`dictionary.db` (at `docs/explorer/data/dictionary.db`) already contains all 131+ real ABS dataset names. It is not currently used by the server or UI.

### Bug 2 — Variable tree collapses after JSF form submit

`selectVariables` (navigator.ts:290) expands the variable tree once before starting the check+submit loop. After `submitJsfForm` triggers a full JSF page reload, the ABS site resets the tree to its initial collapsed state. The loop then immediately calls `checkVariableCategories` for the next variable, but that variable's parent group is collapsed and the node is not in the DOM — so the function finds 0 nodes and throws.

---

## Architecture

Two independent fixes, non-overlapping file sets. Either can be shipped separately.

| Bug | Files changed |
|-----|--------------|
| 1 — Dataset names | `package.json`, `src/server.ts`, `ui/app.jsx` |
| 2 — Tree reset | `src/shared/abs/navigator.ts` only |

---

## Fix 1 — `GET /api/datasets` endpoint

### Dependency

Add `better-sqlite3` (runtime) and `@types/better-sqlite3` (dev).

### Path resolution

Mirror the existing `UI_DIR` dual-path pattern in `server.ts`:

```typescript
const db1 = join(__dirname, '..', 'docs', 'explorer', 'data', 'dictionary.db');
const db2 = join(__dirname, '..', '..', 'docs', 'explorer', 'data', 'dictionary.db');
const DICT_DB = existsSync(db1) ? db1 : db2;
```

### New route

```
GET /api/datasets        (no auth required — registered before requireAuth middleware, same block as /api/health)
→ 200  [{ id: number, name: string, code: null, tag: null, year: null }, ...]
        SELECT id, name FROM datasets ORDER BY name
→ 503  { error: string }  if DICT_DB not found at startup
```

`dictionary.db` has no `code`, `tag`, or `year` columns. The route returns `null` for those fields so the response objects are structurally compatible with the mock `DATASETS` entries that `form.jsx` expects.

The DB handle is opened once at server startup (not per-request). If the file does not exist the route returns 503; the server continues running for all other routes.

### UI (`ui/app.jsx`)

On mount, fetch `/api/datasets`. On success, replace the dataset picker option list with the real names. On failure (network error, 503, simulation mode), fall back to the existing `DATASETS` mock from `data.js`.

### UI (`ui/form.jsx`) — small guard change required

`DatasetPicker` currently references `d.code` in two places that must be guarded:

1. **Fuzzy scoring (line 41):**
   ```js
   window.fuzzyScore(needle, d.code ?? '') * 0.5
   ```
2. **Display row (line 102):**
   ```jsx
   {d.code && <span className="s">{d.code} · {d.tag} · {d.year}</span>}
   ```

These guards make the picker render cleanly for both real names (no code/tag/year) and mock names (all fields present).

The selected dataset name is passed unchanged to the runner as the `dataset` field, where `fuzzyMatchDataset` matches it against the live ABS catalogue — exact or near-exact with real names.

---

## Fix 2 — Re-expand variable tree after each form submit

### Root cause

The round-based group expansion (navigator.ts:335–356) runs once before the check+submit loop. It is not called again after `submitJsfForm` reloads the page.

### Change

Move the two local consts at navigator.ts:330–333 (`SKIP_GROUPS`, `isVarNode`) to module scope. Extract navigator.ts:335–356 into a named helper:

```typescript
async function expandVariableGroups(
  page: Page,
  reporter: PhaseReporter,
  signal: AbortSignal,
): Promise<void>
```

The helper uses the module-scope `SKIP_GROUPS` and `isVarNode`. It loops up to 5 rounds, breaking as soon as no new nodes are expanded — so on a post-reload tree with only top-level groups collapsed, it completes in one round (~1.5 s).

Call sites:
1. **Before the check+submit loop** — replaces the current inline block (behaviour unchanged).
2. **After each `submitJsfForm`** — only when more variables remain (i.e. not the last variable). For a single-variable run the condition is always false and the post-submit expand never runs, which is correct since there is no subsequent `checkVariableCategories` call.

`submitJsfForm` already awaits `waitForLoadState('load')` before returning, so the DOM is stable when `expandVariableGroups` is called. No extra sleep is needed.

### Loop shape after the fix

```
for each variable at index i:
  checkVariableCategories(page, name)
  submitJsfForm(page, axis)
  if (i < assignments.length - 1):
    expandVariableGroups(page, reporter, signal)
```

---

## Testing

### Bug 1

- **Unit:** mock `better-sqlite3`; assert `GET /api/datasets` returns `[{ id, name }]` and status 200; assert 503 when DB path missing.
- **Integration:** point at real `dictionary.db`; assert ≥ 100 rows returned; assert names include `"2021 Census - counting persons, place of usual residence"`.
- **UI simulation:** existing mock `DATASETS` fallback path continues to work when fetch fails.

### Bug 2

- **Unit:** mock a Playwright `page` with a mix of collapsed/expanded/leaf/skip nodes; assert `expandVariableGroups` clicks exactly the collapsed non-skip non-variable expanders; assert it breaks after a round with no new expansions.
- **E2E (`ABS_RUN_E2E=1`):** a two-variable run (e.g. rows: `["Sex", "Age"]`) completes without throwing `"Variable 'Age' not found in tree."`.

---

## Out of scope

- No changes to `fuzzyMatchDataset` logic.
- No changes to `checkVariableCategories` internals.
- No migration of `dictionary.db` to a different path (server resolves both dev and prod paths at runtime).
