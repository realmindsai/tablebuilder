# Design: Connect TableBuilder UI to dictionary.db

**Date:** 2026-04-28
**Status:** Approved (awaiting user spec review)

---

## Problem

The TableBuilder runner UI at `https://tablebuilder.realmindsai.com.au/` shows the
same hardcoded list of 20 generic Census variables for every dataset. The
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
consistent.

---

## Architecture

Three layers change:

1. **DB schema (`assembler.ts`, `dictionary.db`)** — replace
   `datasets.geographies_json` with a normalized `geographies` table
   (mirrors `groups`).
2. **Server (`src/server.ts`)** — add a new metadata endpoint that returns
   groups, variables, and geographies for a dataset.
3. **UI (`ui/`)** — strip the hardcoded variable list, add a dataset-store
   cache, rewire the variable picker to be dataset-scoped, and add a
   geography selector. The variable picker gains a "browse" modal alongside
   the existing inline autocomplete.
4. **Runner (`src/runner.ts` + `src/shared/abs/navigator.ts`)** — accept a
   `geography` field, navigate into that classification release in the JSF
   tree before selecting categories.

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
unchanged — only the assembly step changes. After the code change we re-run
`xvfb-run -a npx tsx scripts/build-dict.ts --assemble-only` on totoro once to
rebuild the DB from the existing cache (no re-scrape needed; cache JSONs
already carry the geography lists).

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
Returns 503 if `dictDb` is null (matches existing pattern in `/api/datasets`).

---

## UI changes

### `ui/dataset-store.js` (new)

Tiny fetch+cache module:

```js
const cache = new Map();
export function loadMetadata(datasetId) {
  if (cache.has(datasetId)) return cache.get(datasetId);
  const p = fetch(`/api/datasets/${datasetId}/metadata`).then(r => {
    if (!r.ok) throw new Error(`metadata fetch failed: ${r.status}`);
    return r.json();
  });
  cache.set(datasetId, p);
  return p;
}
```

Errors are not cached — a rejected promise is removed from the cache so
retries are possible. (The cache is keyed by id and never stale within a
session because the DB only changes on service restart.)

### `ui/data.js`

Delete the 20-entry `VARIABLES` constant. Keep `PHASES` and the formatting
helpers untouched.

### `ui/form.jsx`

- When the dataset selection changes, fire `loadMetadata(id)`. While the
  promise is pending, show "loading variables…" / "loading geographies…"
  placeholders and disable submit.
- Geography control: a new `<select>` placed between the dataset picker and
  the variable pickers. Single-select. Options come from
  `metadata.geographies`. First option is `(no geography selected)` — null is
  valid (runner uses ABS default).
- Variable picker (row + column buckets): the existing input keeps inline
  autocomplete behavior, but now reads from `metadata.groups[*].variables`.
  Suggestions show the parent group label as a section header.
  `.slice(0, 7)` is removed — no upper bound on dropdown length beyond what
  the user types.
- New `<BrowseModal>` component opened by an "Browse all" button next to
  each variable input. Renders a collapsible tree of groups with
  checkable leaves. On close, selected variables are added to the bucket.
- When dataset changes: clear the geography selection and both variable
  buckets (selections are dataset-scoped).

### `ui/applyEvent.js` / form payload

Submit payload to `/api/run` gains `geography: { id, label } | null`.
`dataset` and `variables[]` keep their current string shape so the runner's
input contract stays compatible.

---

## Runner changes

### `src/runner.ts`

Validate the new `geography` field at request boundary (server-side, before
enqueue). Pass `geography.label` through to the runner pipeline.

### `src/shared/abs/navigator.ts`

Add `selectGeography(page, label)`. Called after `selectDataset` and before
category selection if a geography is requested. Implementation:

1. Use the JSF search box (`#searchPattern`) to filter for the geography
   label.
2. Click the matching tree node to navigate into that classification release.
3. Wait for the variable subtree to load (existing tree-stability poll).
4. If no match found within timeout: throw with `phase: 'geography'`.

The runner phase list (`PHASES` in `ui/data.js`) gains a `geography` step
between `dataset` and `tree`.

---

## Server-side validation

The `/api/run` body validator (already exists for `dataset` + `variables`)
extends to:

- `dataset` resolves to a row in `datasets`.
- Every entry in `variables[]` matches a `variables.label` in some group of
  that dataset.
- `geography` (if present) is `{ id, label }` and `id` resolves to a row in
  `geographies` whose `dataset_id` matches the resolved dataset.

Any mismatch → 400 with `{ error, field }`.

---

## Error handling

| Failure | Behavior |
|---|---|
| `/api/datasets/:id/metadata` 404 | UI toast, revert dataset selection |
| `dictDb` null | 503 from server, UI shows persistent error banner |
| Submit-time validation rejects | 400 with `{error, field}`, UI highlights field |
| Runner can't find geography in JSF tree | run fails with `phase: 'geography'`, surfaces in run history |
| Network error on metadata fetch | promise rejected, store entry removed, UI offers retry |

---

## Testing

### Unit (vitest)

- **`assembler.ts`** — geographies are inserted as rows; round-trip test on a
  fixture cache reads back via SELECT. Confirms `geographies_json` column is
  gone.
- **`dataset-store.js`** — fetches once per id; second call resolves from
  cache without a network hit; 404 surfaces as rejection and clears cache.
- **Run validator** — accepts a known dataset+variables+geography; rejects
  unknown geography, unknown variable, unknown dataset.

### Integration (vitest + supertest, against fixture DB)

- `GET /api/datasets/:id/metadata` returns the expected shape for a real
  dataset id; geographies is non-empty for cultural-diversity-like datasets;
  groups have variables nested under them.
- 404 for an unknown id.
- 503 when `dictDb` is null.

### E2E (Playwright on the live UI, totoro or local)

- Pick "2021 Census - cultural diversity":
  - Geography dropdown contains "LGA (2021 Boundaries) (UR)".
  - Variable browse modal lists ≥10 groups.
  - Inline autocomplete returns ≥3 results for "ancestry" with group labels
    visible.
- Pick a dataset with no geographies (if any exist after the rebuild) →
  dropdown shows the `(no geography selected)` placeholder only; submit is
  not blocked.
- Submit a 1-variable run end-to-end → assert success in the SSE stream.

### Runner E2E (Playwright against real ABS)

One golden-path run with `geography = "LGA (2021 Boundaries) (UR)"` and
`variables = ["Sex"]`. Acceptance: the resulting CSV's first column header
contains "LGA" or its row labels match LGA-level entities (not "Australia").
This is the only test that proves the new `selectGeography` step works
end-to-end. Skipped in CI; run manually.

---

## Out of scope

- **Backwards compat with `geographies_json`.** The column is dropped, not
  deprecated. Nothing else in the codebase reads it (verified by grep).
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
