# Design: Catalogue-Listing Double-Call for build-dict CLI

**Date:** 2026-04-28
**Status:** Approved (awaiting user spec review)

---

## Problem

The full ABS dictionary scrape on totoro on 2026-04-27 attempted only 168 datasets even though the catalogue genuinely contains 200. About 30 datasets — primarily 2011 Census variants and a few 2021 datasets — never made it into the work queue and so are absent from `dictionary.db`.

The root cause is visible in the run log:

```
[build-dict] catalogue: 168 datasets        ← listDatasets in build-dict.ts
…
selectDataset: 200 available: […]            ← listDatasets called by selectDataset, immediately after
```

The same `listDatasets` function, called twice in quick succession with the same page state pattern (fresh `page.goto` + `networkidle`), returns 168 the first time and 200 the second. We never observed the second-call result disagree with later ones — it's specifically *the very first listing on a freshly-navigated catalogue page* that under-reports.

Hypothesised mechanism: ABS's JSF catalogue page resolves its tree via post-`networkidle` AJAX racing with our `expandAllCollapsed` polling. On the very first navigation in a session, server-side state is cold; on subsequent navigations, the catalogue page's tree comes back complete and our expansion sees the whole set on the first poll.

---

## Architecture

A single change, contained in `scripts/build-dict.ts`. No changes to `src/shared/abs/navigator.ts`, so the live `tablebuilder.service` and the existing `selectDataset` callers keep their current single-listing behaviour. The +3 minute cost is paid only by the CLI scrape — never by user-facing runs.

---

## Logic

In the full-scrape branch (`!args.only && !args.retryFailed`), replace:

```ts
queue = await listDatasets(page);
console.log(`[build-dict] catalogue: ${queue.length} datasets`);
```

with:

```ts
const firstListing = await listDatasets(page);
console.log(`[build-dict] catalogue listing 1: ${firstListing.length} datasets`);

// The first listDatasets call after a fresh navigation has been observed to
// under-report by ~30 datasets (168 vs 200). Subsequent calls return the full
// set. Re-navigate and list again, then take the union — cheap insurance against
// either listing missing entries.
await navigateToCatalogue(page);
const secondListing = await listDatasets(page);
console.log(`[build-dict] catalogue listing 2: ${secondListing.length} datasets`);

queue = Array.from(new Set([...firstListing, ...secondListing]));
if (firstListing.length !== secondListing.length) {
  console.warn(
    `[build-dict] catalogue counts differed (${firstListing.length} vs ${secondListing.length}); ` +
    `using union of ${queue.length}`,
  );
}
console.log(`[build-dict] catalogue: ${queue.length} datasets (queue size)`);
```

**Union, not just second-trust.** If some run-to-run flakiness happens the other direction (second listing drops a dataset the first had), we don't lose it. The set deduplicates exact-name matches.

---

## Scope

Applies **only** to the full-scrape code path. The `--only <name>` and `--retry-failed` branches each populate `queue` from a different source (single fuzzy-matched name; `<slug>.error.json` files) and are unchanged.

---

## Testing

No unit test. This is operational glue around an already-tested `listDatasets`. The acceptance criterion is the next full-scrape run on totoro: `[build-dict] catalogue: N datasets (queue size)` should report **≥ 195**, allowing some headroom for ABS-side flakiness.

If the next full run again reports < 195, the hypothesis is wrong and the fix needs rework — likely a deeper investigation of why `expandAllCollapsed` returns under-counts on the first pass.

---

## Out of scope

- **Changing `listDatasets` itself.** That function is shared with `selectDataset` and the live service's `runner.ts`; making it slower (or making it re-navigate internally) penalises every user-facing run for a CLI-only failure mode.
- **A general "list-N-times until stable" loop.** We have no evidence that a third listing ever disagrees with the second. Single retry covers the observed problem; more is YAGNI until evidence shows otherwise.
- **Investigating the JSF / catalogue-side cause.** Could be session warm-up, server-side caching, race between AJAX tree-build and our `networkidle` signal, etc. Worth diagnosing eventually, but a 3-minute fix beats a multi-hour spelunking session.
- **`selectDataset`'s internal `listDatasets` call.** It already returns 200 in our observations; second-listings inside `selectDataset` happen after a fresh `navigateToCatalogue` and have consistently been complete. No change needed.
