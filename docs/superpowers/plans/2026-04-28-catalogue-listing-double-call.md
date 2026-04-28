# Catalogue-Listing Double-Call Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the build-dict CLI's full-scrape catalogue listing under-counting (~30 missing datasets) by listing the catalogue twice with a re-navigation between, then taking the union.

**Architecture:** Single-file edit in `scripts/build-dict.ts`. Replace the single `listDatasets(page)` call in the full-scrape branch with: list → `navigateToCatalogue` → list-again → union. Second listing is wrapped in try/catch so a network blip after listing-1 doesn't waste the work. No changes to shared `listDatasets` so the live `tablebuilder.service` and `selectDataset` callers are unaffected.

**Tech Stack:** TypeScript ESM, Playwright (already used). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-28-catalogue-listing-double-call-design.md`

---

## File Map

| File | Change |
|------|--------|
| `scripts/build-dict.ts` | Replace lines 177-180 (the `else { queue = await listDatasets(page); … }` block in the queue-building if/else chain) with a two-listing-and-union block |

That's the entire scope. No new files. No tests added (this is operational glue around an already-tested `listDatasets`; verification is the next totoro full-scrape run).

---

## Task 1: Replace single listDatasets call with double-call + union

**Files:**
- Modify: `scripts/build-dict.ts:178-179`

**Context:** `scripts/build-dict.ts` builds a `queue: string[]` of dataset names to scrape. Around line 159 there's an `if (args.only) ... else if (args.retryFailed) ... else { queue = await listDatasets(page); }` chain. The `else` branch is where the bug lives — `listDatasets` on freshly-navigated catalogue tree under-reports by ~30 datasets on first call. Doing a second listing after re-navigation has been observed to consistently return the full set.

`navigateToCatalogue` is already defined in the same file (~line 87) and handles the fresh-page-goto path correctly when called from the catalogue page. `listDatasets` and `Page` are already imported. No new imports needed.

- [ ] **Step 1: Read current state to confirm the line range**

```bash
cd /Users/dewoller/code/rmai/tablebuilder
sed -n '175,182p' scripts/build-dict.ts
```

Expected output (confirms the lines you're about to replace):
```
      queue = namesFromErrors;
      console.log(`[build-dict] --retry-failed: ${queue.length} datasets to retry`);
    } else {
      queue = await listDatasets(page);
      console.log(`[build-dict] catalogue: ${queue.length} datasets`);
    }

    for (let i = 0; i < queue.length; i++) {
```

If the line range is different (someone else edited the file), find the new location of `queue = await listDatasets(page);` inside the `else` branch following `args.retryFailed` and adjust accordingly.

- [ ] **Step 2: Apply the edit**

Use the Edit tool to replace this block exactly:

**Old (the entire `else { ... }` body, lines 177-180):**

```ts
    } else {
      queue = await listDatasets(page);
      console.log(`[build-dict] catalogue: ${queue.length} datasets`);
    }
```

**New:**

```ts
    } else {
      const firstListing = await listDatasets(page);
      console.log(`[build-dict] catalogue listing 1: ${firstListing.length} datasets`);

      // The first listDatasets call after a fresh navigation has been observed
      // to under-report by ~30 datasets (168 vs 200). Subsequent calls return
      // the full set. Re-navigate and list again, then take the union — cheap
      // insurance against either listing missing entries.
      //
      // Fresh page.goto is REQUIRED here, not goBack. The under-counting is
      // specifically a "very first listing on a freshly navigated catalogue"
      // race, and we need a second pass through that same code path. The
      // current navigateToCatalogue uses goBack only when leaving tableView;
      // here URL is already the catalogue so it falls through to a fresh
      // page.goto, which is exactly what we want — don't "optimise" this to
      // skip the re-navigation.
      let secondListing: string[] = [];
      try {
        await navigateToCatalogue(page);
        secondListing = await listDatasets(page);
        console.log(`[build-dict] catalogue listing 2: ${secondListing.length} datasets`);
      } catch (e) {
        // If the second pass fails entirely (network blip, session loss, etc.),
        // don't throw away the work already invested in listing #1 — fall back
        // to it. The user can always re-run with --clear-cache later if they
        // suspect the queue is incomplete.
        console.warn(
          `[build-dict] catalogue listing 2 failed: ${(e as Error).message} — falling back to listing 1`,
        );
      }

      queue = Array.from(new Set([...firstListing, ...secondListing]));
      if (secondListing.length > 0 && firstListing.length !== secondListing.length) {
        console.warn(
          `[build-dict] catalogue counts differed (${firstListing.length} vs ${secondListing.length}); ` +
          `using union of ${queue.length}`,
        );
      }
      console.log(`[build-dict] catalogue: ${queue.length} datasets (queue size)`);
    }
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/dewoller/code/rmai/tablebuilder
npx tsc --noEmit
```

Expected: zero errors. If you get errors:
- "Cannot find name 'firstListing'" or similar → you broke variable scope; verify the new code is inside the `else` block braces
- "Property 'length' does not exist on never[]" → TypeScript inferred `secondListing: never[]` because of an unfortunate split; the explicit `let secondListing: string[] = [];` annotation in the new code prevents this — make sure you copied it verbatim

- [ ] **Step 4: Run all unit tests**

```bash
npm test
```

Expected: 99 passed (no new tests; just confirming no regression).

- [ ] **Step 5: Smoke-test the help banner**

```bash
npx tsx scripts/build-dict.ts --help
```

Expected: prints `scripts/build-dict.ts — see top of file for usage` and exits 0. This confirms the file still parses and runs.

- [ ] **Step 6: Smoke-test `--assemble-only` against an empty cache** (no network, no login)

```bash
TMPCACHE=$(mktemp -d)
TMPDB="${TMPCACHE}/test.db"
npx tsx scripts/build-dict.ts --assemble-only --cache-dir "$TMPCACHE" --db-path "$TMPDB"
sqlite3 "$TMPDB" 'SELECT name FROM sqlite_master WHERE type="table" AND name IN ("datasets","groups","variables","categories","datasets_fts","variables_fts");'
rm -rf "$TMPCACHE"
```

Expected: lists all six table names. Confirms the script's non-listing paths still work end-to-end.

- [ ] **Step 7: Commit**

```bash
cd /Users/dewoller/code/rmai/tablebuilder
git add scripts/build-dict.ts
git commit -m "fix(dict-builder): list catalogue twice and union to fix missing-30 bug

The first listDatasets call after a fresh navigation under-reports by
~30 datasets in the build-dict CLI's full-scrape startup (we observed
168 vs 200 between two back-to-back calls in the same run). Subsequent
calls return the full set.

Fix: list once, navigate-and-list-again, take the union of names. Second
pass is wrapped in try/catch so a network blip mid-startup falls back to
listing-1 instead of aborting the whole scrape.

Scoped to scripts/build-dict.ts only — listDatasets and selectDataset
are unchanged, so the live tablebuilder.service is unaffected.

Acceptance: next full scrape on totoro reports ≥195 in queue.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

- [ ] **Step 8: Push** (so totoro can pull before the next scrape)

```bash
git status -sb            # confirm "## main...origin/main" — no surprise dirty state
git push origin main
```

Expected: clean status (only the build-dict.ts edit just committed; no other modified files). Then a clean push. If main has diverged, `git pull --rebase origin main` first, then push.

---

## Verification (operational, post-implementation)

This isn't a checked task in this plan — it happens on the next full scrape on totoro, which is run separately. The verification:

```bash
ssh totoro_ts
cd /tank/code/tablebuilder
git pull
xvfb-run -a npx tsx scripts/build-dict.ts --clear-cache 2>&1 | tee /tmp/build-dict-full.log

# Within the first ~10 minutes of the run, check the log:
grep '\[build-dict\] catalogue' /tmp/build-dict-full.log
```

Expected output shape:
```
[build-dict] catalogue listing 1: 168 datasets
[build-dict] catalogue listing 2: 200 datasets
[build-dict] catalogue counts differed (168 vs 200); using union of 200
[build-dict] catalogue: 200 datasets (queue size)
```

If the queue size is **≥195**: success. The fix works.

If it's still **<195**: the hypothesis is wrong. Don't iterate blindly — escalate. Likely next steps would involve looking deeper at why `expandAllCollapsed` returns under-counts even on the second pass (maybe stable-zero-poll triggering too early; maybe the catalogue truly has <200 entries on totoro for IP/session reasons).
