# Design: Connect TableBuilder UI to dictionary.db

**Date:** 2026-04-28
**Status:** Approved (awaiting user spec review)

---

## Problem

The TableBuilder runner UI at `https://tablebuilder.realmindsai.com.au/` shows
the same hardcoded list of 20 generic Census variables for every dataset. The
autocomplete dropdown is also capped at 7 entries (`form.jsx:126` —
`.slice(0, 7)`), which is what surfaced as "cultural diversity has only 7
variables".

We just rebuilt `dictionary.db` to contain 194 datasets, 2200 groups, 13992
variables, 108482 categories, plus geography classifications per dataset. None
of this data is reaching the form. The UI must read its picker contents from
the dictionary.

A second inconsistency is that geographies are stored as a JSON blob
(`datasets.geographies_json`) while every other dictionary entity is a real
table. We fix that as part of this change so the schema is internally
consistent. (User explicitly approved this widening of scope during the
brainstorm.)

---

## Architecture

Four layers change:

1. **DB schema (`assembler.ts`, `dictionary.db`)** — replace
   `datasets.geographies_json` with a normalized `geographies` table
   (mirrors `groups`).
2. **Server (`src/server.ts`)** — add a new metadata endpoint that returns
   groups, variables, and geographies for a dataset.
3. **UI (`ui/`)** — strip the hardcoded variable list, add a dataset-store
   cache, rewire the variable picker to be dataset-scoped, and add a
   geography selector. The variable picker gains a "Browse" modal alongside
   the existing inline autocomplete.
4. **Runner (`src/runner.ts` + `src/shared/abs/navigator.ts`)** — accept a
   `geography` field; if non-null, navigate into that classification release
   in the JSF tree before category selection.

Strict DB mode: the picker only offers what the dictionary contains. No free-
text variables. No fallback for the 4 datasets that failed to scrape — they
already don't appear in `/api/datasets`, so the form can't reach them.

---

## DB schema change

Drop `datasets.geographies_json`. Add:

```sql
CREATE TABLE geographies (
  id INTEGER PRIMARY KEY,
  dataset_id INTEGER NOT NULL REFERENCES datasets(id),
  label TEXT NOT NULL
);
CREATE INDEX idx_geographies_dataset ON geographies(dataset_id);
```

`assembler.ts` is updated to insert geographies as rows instead of stringifying
to JSON. The cache layer (`ExtractedDataset.geographies: string[]`) is
unchanged — only the assembly step changes.

**Migration / deployment** — `assembler.ts` already builds a fresh DB at
`<dbPath>.tmp` and atomically renames it (lines 77-128). No in-place migration
needed. After the code change we re-run `xvfb-run -a npx tsx
scripts/build-dict.ts --assemble-only` on totoro once to rebuild the DB from
the existing cache (no re-scrape needed; cache JSONs already carry the
geography lists). The new DB replaces the old atomically; the service is
restarted to pick it up.

**Server boot guard** — at startup, `src/server.ts` runs
`PRAGMA table_info(geographies)` against the open DB. If the table is missing
(old DB still in place), log a loud warning and have the metadata endpoint
return 503 with `{ error: 'Dictionary out of date — needs reassembly' }`.
This catches the deployment-order failure mode where new code meets old DB.

---

## New endpoint

`GET /api/datasets/:id/metadata` (no auth, matches `/api/datasets`):

```ts
{
  id: number;
  name: string;
  geographies: { id: number; label: string }[];
  groups: {
    id: number;
    label: string;
    variables: { id: number; code: string; label: string }[];
  }[];
}
```

Single SQLite read: dataset row, then groups joined to variables, then
geographies. Returns 404 with `{ error: 'Unknown dataset' }` if id is missing.
Returns 503 if `dictDb` is null or the boot guard tripped.

---

## UI changes

### Module convention

The existing UI mixes script-tag globals (`data.js` defines `const VARIABLES`,
read by JSX as `window.VARIABLES`) with one ES module (`applyEvent.js`,
loaded via `type="module"`). To avoid widening that inconsistency, new UI
files **follow the script-tag-globals convention**: `dataset-store.js`
exposes its API as `window.DatasetStore`, loaded via `<script
src="dataset-store.js"></script>` before the JSX.

### `ui/dataset-store.js` (new)

```js
window.DatasetStore = (() => {
  const cache = new Map(); // id → Promise<metadata>
  let currentRequestId = 0; // for race-handling in callers if they need it

  function loadMetadata(datasetId) {
    if (cache.has(datasetId)) return cache.get(datasetId);
    const p = fetch(`/api/datasets/${datasetId}/metadata`).then(r => {
      if (!r.ok) {
        cache.delete(datasetId); // don't cache failures
        throw new Error(`metadata fetch failed: ${r.status}`);
      }
      return r.json();
    }).catch(e => {
      cache.delete(datasetId);
      throw e;
    });
    cache.set(datasetId, p);
    return p;
  }

  return { loadMetadata };
})();
```

### `ui/data.js`

Delete the 20-entry `VARIABLES` constant. Keep `PHASES`, `SEED_HISTORY`, and
the formatting helpers untouched. The file becomes a 50-line UI helpers
module.

### `ui/form.jsx`

**Dataset change handler** — when the dataset id changes, fire
`window.DatasetStore.loadMetadata(id)`. Track the requested id in a ref; on
resolve, ignore the response if the user has since selected a different
dataset (handles the rapid-toggle race). Clear geography selection and both
variable buckets on dataset change.

**Geography control** — new `<select>` placed between the dataset picker and
the variable pickers. Single-select. Options come from `metadata.geographies`.
First option is `(no geography selected)` (value `""`). If
`metadata.geographies` is empty (rare), the select renders with just the
placeholder; submission is **not** blocked — null geography is always valid
and means "use ABS default". Geography changes do **not** clear variable
selections (geography only affects runner navigation, not which variables
exist).

**Variable picker payload shape** — internally, each variable bucket holds
`{ id, label }` objects, not bare strings. The submit payload sends them as
`{ id, label }` so the validator can verify the id resolves to a row in this
dataset and the runner can use `label` for JSF tree navigation. This protects
against the rare case of two variables in the same dataset sharing a label
(the id disambiguates).

**Inline autocomplete** — same input as today, reading from
`metadata.groups[*].variables`. Suggestions show `{group label} > {variable
label}` with the group as a section header. The dropdown caps at **50
suggestions** (sanity bound, not a true-count cap; eliminates the original
bug). Substring match against label and code.

**`<BrowseModal>`** (new component) — opened by an "Browse" button next to
each variable input. Renders a flat list of groups with collapsible variable
children (one level deep — groups → variables, no deeper). Variables already
in the bucket are pre-checked. No in-modal search in v1 (the inline
autocomplete already covers search). Click "Apply" → bucket replaces its
contents with the modal's checked set; "Cancel" → no change. Closes on
backdrop click (treated as Cancel).

### `ui/applyEvent.js` / form payload

Submit payload to `/api/run` gains:
- `variables: [{ id, label }, ...]` (was `string[]`)
- `geography: { id, label } | null`

`null` and a missing `geography` field are treated identically by the
validator and runner.

---

## Runner changes

### `src/runner.ts`

Validate the new `geography` field at request boundary (server-side, before
enqueue). Pass `geography` (or null) through to the runner pipeline.

### `src/shared/abs/navigator.ts`

Add `selectGeography(page, label)`. Called after `selectDataset` and before
category selection only if a geography is requested (non-null). When null,
the step is skipped entirely — runner uses ABS default. Implementation:

1. Use the JSF search box (`#searchPattern`) to filter for the geography
   label.
2. Click the matching tree node to navigate into that classification release.
3. Wait for the variable subtree to load (existing tree-stability poll).
4. If no match found within timeout: throw with `phase: 'geography'`.

### Phase list

`PHASES` in `ui/data.js` gains a `geography` step between `dataset` and
`tree`:

```
login → dataset → geography (conditional) → tree → check → submit → retrieve → download
```

The `geography` phase is only emitted when geography is non-null. SSE event
shape unchanged (just one new `id` value).

---

## Server-side validation

The `/api/run` body validator extends to:

- `dataset` (string) resolves to a row in `datasets`.
- Every entry in `variables[]` is `{ id, label }`; each `id` resolves to a
  row in `variables` whose `group_id` belongs to the resolved dataset.
- `geography` (if present and non-null) is `{ id, label }` and `id` resolves
  to a row in `geographies` whose `dataset_id` matches the resolved dataset.

Per-variable validation is duplicate work given the strict-DB picker, but
kept as defense-in-depth (cheap — single indexed lookup per variable, ~1 ms
total for typical 1-3 variable selections). Protects against client-side
modifications and stale UI bundles.

Any mismatch → 400 with `{ error, field }`.

---

## Error handling

| Failure | Behavior |
|---|---|
| `/api/datasets/:id/metadata` 404 | UI toast, revert dataset selection |
| `dictDb` null or `geographies` table missing | 503 from server, UI shows persistent error banner |
| Submit-time validation rejects | 400 with `{error, field}`, UI highlights field |
| Runner can't find geography in JSF tree | run fails with `phase: 'geography'`, surfaces in run history |
| Network error on metadata fetch | promise rejected, store entry removed, UI offers retry |
| Rapid dataset toggle (race) | stale resolves are ignored via ref-tracked currentDatasetId |

---

## Testing

### Unit (vitest)

- **`assembler.ts`** — geographies are inserted as rows; round-trip test on
  a fixture cache reads back via SELECT. Confirms `geographies_json` column
  is gone from the schema.
- **`dataset-store.js`** — fetches once per id; second call resolves from
  cache without a network hit; 404 surfaces as rejection and clears the
  cache entry so retries are possible.
- **Run validator** — accepts a known dataset+variables+geography; rejects
  unknown geography id, unknown variable id, unknown dataset name; treats
  missing `geography` field and `geography: null` identically.

### Integration (vitest + supertest, against fixture DB)

- `GET /api/datasets/:id/metadata` returns the expected shape for a real
  dataset id; geographies is non-empty for cultural-diversity-like datasets;
  groups have variables nested under them.
- 404 for an unknown id.
- 503 when `dictDb` is null.
- 503 when the `geographies` table is missing (boot-guard test against a
  pre-migration fixture DB).

### E2E (Playwright on the live UI)

- Pick "2021 Census - cultural diversity":
  - Geography dropdown contains "LGA (2021 Boundaries) (UR)".
  - Variable browse modal lists ≥10 groups.
  - Inline autocomplete returns **>7 results** for a broad query (e.g. "a")
    — direct regression assertion against the original `.slice(0, 7)` bug.
- Pick a dataset with no geographies (if any exist after the rebuild) →
  dropdown shows the `(no geography selected)` placeholder only; submit is
  not blocked.
- Submit a 1-variable run end-to-end → assert success in the SSE stream.
- Source-level assertion: `grep -c 'slice(0, 7)' ui/form.jsx` returns 0
  (no remaining hardcoded cap).

### Runner E2E (Playwright against real ABS)

One golden-path run with `geography = { id, label: "LGA (2021 Boundaries)
(UR)" }` and a single variable. Acceptance: the resulting CSV has **≥500
rows** (concrete LGA-level row count; Australia-level run yields ~10).
Skipped in CI; run manually after deployment.

---

## Out of scope

- **Backwards compat with `geographies_json`.** The column is dropped, not
  deprecated. Verified via grep that nothing else in the codebase reads it.
- **Custom variable input.** Strict DB mode. If a user needs a variable
  that's not in the dictionary, the fix is rescraping that dataset, not
  loosening the picker.
- **Re-scraping the 4 failed datasets.** They remain absent from the picker.
  Tracked separately (Net Overseas Migration, Children enrolled in
  preschool 2015, Cultural Activities 2013-14, Recent Migrants 2010).
- **Dataset-detail summary panel.** Showing category counts, totals, etc.
  could be added later but isn't needed to fix the picker.
- **Multi-geography selection.** Geography is single-select. ABS TableBuilder
  itself only honors one classification release per query.
- **Dictionary refresh without service restart.** The dataset-store cache
  lives until page reload; that's acceptable because DB rebuilds are rare
  and require a service restart anyway.
- **In-modal search in BrowseModal.** Inline autocomplete already covers
  search; modal is for browsing.
