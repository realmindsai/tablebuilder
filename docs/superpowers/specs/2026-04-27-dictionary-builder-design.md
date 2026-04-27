# Design: ABS Dictionary Builder

**Date:** 2026-04-27
**Status:** Approved (awaiting user spec review)

---

## Problem

The current `docs/explorer/data/dictionary.db` is structurally incomplete:

1. **No geographic variable rows.** Variables like `STRD State/Territory`, `SA2`, `SA4`, `LGA Local Government Area 2021`, `POAS Postal Area`, `SA1MAIN_2021` are missing from the `variables` table for every census dataset, even though they're real cross-tab dimensions in the ABS TableBuilder. This is why a row like "Sex × Age × State" works at runtime (live tree has them) but the DB-driven picker, fuzzy matcher, or any pre-flight validator can't tell the user that State exists.

2. **Empty `categories` table.** Every variable's category list (Sex → Male/Female; State → NSW/VIC/…) is missing for every dataset.

3. **`geographies_json` is a flat list of classification-release names** (`"LGA (2021 Boundaries)"`, `"SA1 by Main ASGS"`) rather than the geographic *variable* rows you can put on rows/cols. That column is still useful — those are real classification-release options the dataset is published against — but it's *not* the same thing as the geographic variable rows that should be in `variables`.

The legacy Python `tree_extractor.py` had two structural issues that produced this state:
- `--exclude-census` defaulted to `True`, so census datasets weren't scraped on the original run.
- `_split_geography_and_variables` treated geographic entries as *the prefix of no-checkbox leaves*, which captured the classification-release list but never recursed into those classifications to capture the variable rows inside them.

The Python implementation was archived in `legacy/python-tablebuilder-20260426.zip` two days ago as part of the Node.js migration. Reviving it would re-introduce a parallel codebase. A TypeScript rewrite using existing `auth.ts` and `navigator.ts` is the natural path.

---

## Architecture

```
src/dict-builder/
  scraper.ts        — extract one dataset's tree from a logged-in Playwright page
  walker.ts         — tree-walking primitives (depth-aware expand, classify nodes)
  cache.ts          — read/write per-dataset JSON cache files
  assembler.ts      — cache files → fresh dictionary.db (transactional)
  types.ts          — ExtractedDataset / ExtractedGroup / ExtractedVariable / ExtractedCategory
  scraper.test.ts
  walker.test.ts
  assembler.test.ts
  cache.test.ts

scripts/
  build-dict.ts     — CLI entry point: login → loop datasets → assemble
```

**Reused without changes:**
- `src/shared/abs/auth.ts` — JSF login
- `src/shared/abs/navigator.ts` — `selectDataset`, `listDatasets`, `expandVariableGroups`, `tryExpandGeographic`

**Files written:**
- `~/.tablebuilder/dict_cache/<slug>.json` — per-dataset extraction (success)
- `~/.tablebuilder/dict_cache/<slug>.error.json` — per-dataset failure record
- `~/.tablebuilder/dict_cache/_summary.json` — end-of-run summary
- `~/.tablebuilder/build-dict.log` — full stdout/stderr (via tee)
- `docs/explorer/data/dictionary.db` — final atomic-renamed output

**Data flow:**

1. CLI logs in once via `auth.ts`. Session cookie persists for the whole run.
2. `listDatasets()` scrapes the live ABS catalogue → list of dataset names.
3. For each dataset:
   - If `<slug>.json` exists: skip (resume).
   - If `<slug>.error.json` exists: skip unless `--retry-failed`.
   - Otherwise: `selectDataset(name)` → `scraper.extract(page)` → `cache.write(<slug>, result)` → `navigateBackToCatalogue(page)`.
4. After every dataset is processed: `assembler.build(cacheDir, dbPath + '.tmp')` reads every JSON, applies the schema (with the new `category_count` column), inserts datasets/groups/variables/categories under per-dataset transactions, builds FTS5 indexes, then `fs.rename(tmp, target)` for an atomic swap.

Per-dataset isolation means one bad dataset never costs the rest of the run. Atomic rename means the running service keeps serving the old DB throughout — zero-downtime.

---

## Tree walking + geographic recursion

The walker walks every dataset's full schema tree depth-first, classifying each non-leaf node as **group** or **variable** based on its label, not its position in the tree:

| Classification | Detection | Action |
|---|---|---|
| **Variable** | label matches `^[A-Z][A-Z0-9_]{2,}\s.+\(\d+\)\s*$` — `CODE Label (N)` like `STRD State/Territory (9)` or `SA1MAIN_2021 SA1 by Main ASGS (61845)`. The character class includes `_` because real ABS codes use it (`SA1MAIN_2021`, `LGA_2021`, `IFAGEP`). | Capture as a variable row (see code/label extraction below). Use `(N)` as `category_count`. Decide whether to expand based on the threshold (next section). |
| **Group** | non-leaf, doesn't match the variable pattern (`Geographical Areas (Usual Residence)`, `LGA (2021 Boundaries)`, `Selected Person Characteristics`) | Expand and recurse. |
| **Category** | leaf node with a checkbox, inside a variable | Capture as a category row, attached to the surrounding variable. |
| **Geography classification** | leaf node *without* a checkbox, inside the geographic top-level group | Capture into `geographies_json`. |

**Critical change vs legacy:** no `'geographical' in SKIP_GROUPS` exclusion. The walker recurses into `Geographical Areas (Usual Residence)` and into each classification-release sub-group (`LGA (2021 Boundaries)`, `Suburbs and Localities`, `SA1 by Main ASGS`, `Postal Areas`, …). Inside those sub-groups it captures the variable rows — `LGA Local Government Area 2021`, `POAS Postal Area`, `SA1MAIN_2021 SA1`, etc. — that the legacy never reached.

A single tree walk produces both the variable rows AND the `geographies_json` classification list, since the geography-classification leaves and the geographic variables are at different depths and have different node types (no-checkbox vs checkbox).

**Code/label extraction from a matched variable node.**

The raw label is `<CODE> <REST> (<N>)` — e.g. `SA1MAIN_2021 SA1 by Main Statistical Area Structure (61845)`. Canonical extraction:

- `code` = the substring before the first whitespace (`SA1MAIN_2021`)
- `category_count` = the integer inside the trailing `(N)` (`61845`)
- `label` = the substring between the first whitespace and the trailing `(N)`, trimmed (`SA1 by Main Statistical Area Structure`)

This rule is applied uniformly. If the label doesn't match the variable regex (no `(N)`, missing code, etc.), the node is treated as a **group** — log a warning with the raw label and recurse normally. Don't drop nodes silently.

**Slug for cache filenames** — derived from the dataset name with this algorithm:

1. Lowercase
2. Replace any sequence of non-alphanumeric characters (Unicode-aware) with a single `_`
3. Trim leading/trailing `_`
4. Cap at 80 chars (preserve uniqueness of typical ABS names; truncation collisions are a hard error, see below)

`"2021 Census - counting persons, place of usual residence"` → `2021_census_counting_persons_place_of_usual_residence`. The collision check runs on every `cache.write()` call (not only on resume): if a `<slug>.json` already exists, read its `dataset_name` field — match → allow overwrite (this is just resume retry); mismatch → abort the run with an explicit error so a human can pick a disambiguation strategy.

---

## Categories — the threshold

For each variable found in the walk:

| Category count `N` | Action |
|---|---|
| `N ≤ 100` | Expand the variable, capture every leaf into the `categories` JSON field |
| `N > 100` | Don't expand. Just record `category_count = N` on the variable; `categories` stays empty |

`N` is parsed from the trailing `(N)` in the variable label — no expansion needed to count. Never click an expander for `SA1` (60k), `POAS` (3k), `SA2` (2.4k), `LGA` (550). Expansion only happens for things like `SEXP Sex (2)`, `AGEP Age (21)`, `MSTP Marital Status (5)`, `STRD State/Territory (9)`. Big wins: scrape time stays manageable, DB stays small, picker/explorer can still show counts ("STRD State/Territory · 9 categories") without storing 60,000 SA1 codes.

**Schema change required:** add `category_count INTEGER NOT NULL DEFAULT 0` to the `variables` table. Single column, additive — `/api/datasets` doesn't touch it, so existing readers are unaffected.

---

## Cache → DB assembly

Each `~/.tablebuilder/dict_cache/<slug>.json`:

```json
{
  "dataset_name": "2021 Census - cultural diversity",
  "geographies": ["Australia", "Main Statistical Area Structure", "LGA (2021 Boundaries)", "..."],
  "groups": [
    {
      "label": "Cultural Diversity",
      "path": "Cultural Diversity",
      "variables": [
        { "code": "ANCP", "label": "Ancestry Multi Response", "category_count": 11, "categories": ["English","Australian","..."] },
        { "code": "BPLP", "label": "Country of Birth of Person", "category_count": 8, "categories": ["..."] }
      ]
    },
    {
      "label": "LGA (2021 Boundaries)",
      "path": "Geographical Areas (Usual Residence) > LGA (2021 Boundaries)",
      "variables": [
        { "code": "LGA_2021", "label": "Local Government Area 2021", "category_count": 565, "categories": [] }
      ]
    },
    {
      "label": "SA1 by Main ASGS",
      "path": "Geographical Areas (Usual Residence) > SA1 by Main ASGS",
      "variables": [
        { "code": "SA1MAIN_2021", "label": "SA1 by Main Statistical Area Structure", "category_count": 61845, "categories": [] }
      ]
    }
  ],
  "scraped_at": "2026-04-27T08:14:32Z",
  "tree_node_count": 412
}
```

`assembler.build(cacheDir, dbPath)`:

1. Open `${dbPath}.tmp` (delete if present so we always start fresh — never partially populated). Apply schema: the CREATE TABLE statements for `datasets`, `groups`, `variables`, `categories` are inlined in `assembler.ts` as string constants (single source of truth, no dependency on reading the old DB). The `variables` table includes the new `category_count INTEGER NOT NULL DEFAULT 0` column.
2. Sort cache files by `dataset_name` ascending. Within each cache, sort `groups` by `path` ascending; within each group, sort `variables` by `code` ascending; within each variable, **preserve** the `categories` array order from the cache (it reflects ABS site display order, which is what the user expects to see). These three sorts make `assembler.build` deterministic given a fixed cache: running it twice on the same cache directory produces a byte-identical SQLite file. End-to-end determinism (same scrape inputs → same DB output) additionally requires `scraper.ts` to capture categories in Playwright DOM order (stable across runs against the same ABS catalogue snapshot) — `scraper.ts` does this implicitly by iterating `page.locator('.treeNodeElement').all()` in document order.
3. Each cache → one transaction: insert dataset (with `geographies_json` as JSON-stringified array), then groups, then variables (with `category_count`), then categories.
4. After all inserts, build FTS5 indexes by `CREATE VIRTUAL TABLE datasets_fts USING fts5(name, summary)` and `CREATE VIRTUAL TABLE variables_fts USING fts5(dataset_name, group_path, code, label, categories_text, summary)`, then `INSERT INTO <fts> SELECT … FROM <base tables>`. No triggers — the DB is rebuilt from scratch each run, so we don't need incremental sync. The legacy schema's `_data`/`_idx`/`_content`/`_docsize`/`_config` shadow tables are auto-created by SQLite when the virtual table is created.
5. `fs.rename('${dbPath}.tmp', dbPath)`.

Pure function (input: cache dir + DB target → output: file). Easy to unit-test against a fixture cache directory.

---

## CLI + operational flow

`scripts/build-dict.ts`:

| Flag | Behaviour |
|---|---|
| (none) | Full run with resume — skip datasets that already have `<slug>.json` |
| `--clear-cache` | Delete `~/.tablebuilder/dict_cache/` first, then full run |
| `--only <name>` | Scrape exactly one dataset. The argument is matched against the live catalogue using the existing `fuzzyMatchDataset` from `navigator.ts` (same logic as a normal run). Exactly one match → use it. Zero matches → exit with the standard "No dataset matching" error and the available list. Multiple matches → exit with an error listing the candidates and instruct the user to be more specific. |
| `--retry-failed` | Re-scrape only datasets with `<slug>.error.json`; delete the error file on success |
| `--headed` | Show the browser window (debug) |
| `--skip-assemble` | Scrape only; skip the final DB build. Cache files are produced but `dictionary.db` is left untouched, so the running service keeps serving the old DB until a later `--assemble-only` run. Useful for "scrape now, review caches manually, assemble later" flows. |
| `--assemble-only` | Skip scraping; rebuild DB from existing caches |

Loads `~/.tablebuilder/.env` for credentials (project convention). Default DB target: `docs/explorer/data/dictionary.db`.

**On totoro:**

```bash
ssh totoro_ts
cd /tank/code/tablebuilder
git pull
tsx scripts/build-dict.ts | tee ~/.tablebuilder/build-dict.log
# go away for ~90 min
git add docs/explorer/data/dictionary.db
git commit -m "chore: rebuild dictionary.db from full ABS scrape"
git push
sudo systemctl restart tablebuilder   # serves the new DB
```

The current systemd service keeps running on the old DB throughout. Atomic rename = zero-downtime.

---

## Failure handling & resume

**Per-dataset isolation.** Each dataset is scraped in its own try/catch. On failure: write `<slug>.error.json`:

```json
{
  "dataset_name": "...",
  "error": "navigation timeout: catalogue page took >30s to load",
  "stack": "...",
  "failed_at": "2026-04-27T08:42:11Z",
  "attempt": 1
}
```

Continue to the next dataset. Top-level catastrophic failure (login dies, browser crashes, ssh disconnects) leaves caches intact — re-run from the same point, no work lost.

**End-of-run summary** logged + written to `_summary.json`:

```
✓ 127 datasets scraped
✗ 4 datasets failed (see <slug>.error.json files):
  - Australian Census Longitudinal Dataset, 2006-2011-2016-2021
  - Businesses in Australia (BLADE), 2001-02 to 2023-24
  - …
Cache files: ~/.tablebuilder/dict_cache/  (127 ok + 4 errors)
Run again with --retry-failed to retry just the errors.
```

**Resume rules** (idempotent re-run):

- `<slug>.json` exists → skip (already scraped).
- `<slug>.error.json` exists → skip on a normal run; re-scrape only when `--retry-failed`. Delete the `.error.json` on success.
- Neither exists → scrape now.

**Browser hygiene.** Between datasets, the page navigates back to the catalogue via the existing helper. If navigation back fails, the loop closes the page and opens a fresh one. If the new page lands on the login screen (session cookie expired or invalidated by the server), re-run `auth.login()` once before continuing. If re-login also fails, abort the run with a clear error — the cache files written so far are preserved, so the user can resume after fixing credentials/connectivity.

---

## Testing

**Unit tests (vitest, no real browser):**

| Test file | What it covers |
|---|---|
| `walker.test.ts` | Mock Playwright page with a synthetic `treeNodeElement` tree at various depths. Assert variable-pattern regex matches `STRD State/Territory (9)`, `SA1MAIN_2021 SA1 (61845)`, `AGEP Age (21)`. Assert geographic recursion captures `STRD` as a variable row inside `Geographical Areas (Usual Residence)`. Assert ≤100 threshold drives the expand/skip decision (mock variables of size 5 vs size 500 → only the size-5 one gets expanded). |
| `scraper.test.ts` | Feed a recorded synthetic tree fixture for one small dataset and one census dataset. Assert resulting `ExtractedDataset` has correct geography count, group count, variable count, and that variable-level category arrays match expected sizes (capped at threshold). |
| `assembler.test.ts` | Fixture cache directory of 3–4 JSON files → `build()` against a temp SQLite path. Assert datasets/groups/variables/categories row counts, FTS index queryable, `category_count` populated correctly. Re-run `build()` against the same cache → DB byte-identical (deterministic insert order). |
| `cache.test.ts` | Round-trip an `ExtractedDataset` through write → read → assert deep-equal. Slug generation handles ABS dataset names with commas, parens, dashes, "(MB)" suffixes, and UTF-8 (so cache filenames don't collide). |

**Integration test (opt-in, not in CI):**

`tsx scripts/build-dict.ts --only "Crime Victimisation, 2010-11"` against the real ABS site. Small historical dataset, fast, stable. Run manually before declaring the scraper working. **Run on totoro** (see Dev workflow below).

**Acceptance test** after a full rebuild:

```sql
-- Geographic variables now exist for census datasets
SELECT COUNT(*) FROM variables WHERE code IN ('STRD','SA1MAIN_2021','SA2','SA4','LGA_2021','POAS');
-- expected: ≥ 5 distinct codes × 5 census datasets = 25+

-- Categories present for low-cardinality variables
SELECT v.label, COUNT(c.id) AS cat_count
FROM variables v JOIN categories c ON c.variable_id = v.id
WHERE v.code = 'SEXP' GROUP BY v.id;
-- expected: 2 (Male, Female) for every dataset that has SEXP

-- High-cardinality variables have category_count but no category rows
SELECT label, category_count FROM variables WHERE code = 'SA1MAIN_2021' LIMIT 1;
-- expected: count > 50000, but 0 rows in categories for that variable_id
```

If the first query returns < 25, geographic recursion regressed for some datasets.

---

## Dev workflow

Develop and unit-test locally on the Mac. Run integration tests and the full scrape on totoro.

| Stage | Where | Why |
|---|---|---|
| Write `scraper.ts`, `walker.ts`, `assembler.ts`, etc. | Mac | Fast edit-save-test loop, no SSH lag |
| Unit tests (mock Playwright pages) | Mac | Zero internet needed |
| First integration smoketest (`--only "Crime Victimisation, 2010-11"`) | totoro | Live ABS site needed; user has bad internet locally; totoro already has Chromium + auth |
| Full ~90-minute rebuild | totoro | Stable connection, runtime location |

Same git-based deploy flow as the rest of the project: build → push → `ssh totoro_ts` → `git pull` → `tsx scripts/build-dict.ts ...`. No separate "spin up" needed; `tsx` runs straight from source. The new `scripts/` directory is gitignored only for build artifacts; source files there are committed.

---

## Out of scope

- **Scheduled rebuilds.** Manual CLI only. A systemd timer can be added later if the monthly cadence proves useful (probably not — ABS publishes a few datasets per year).
- **Capturing > 100 categories per variable.** The literal list of every postcode/SA1/SA2 code is always re-fetchable from the ABS site; storing them bloats the DB without a clear consumer use case.
- **Schema versioning.** The single additive column (`category_count`) is the only schema change in this design. If future iterations need bigger changes, that's a separate spec.
- **Public-facing API for categories.** The `/api/datasets` route doesn't change shape (still returns `{id, name, code:null, tag:null, year:null}`). Exposing categories through HTTP can be added when there's a UI consumer.
- **Concurrency.** Sequential dataset scraping. ABS will likely throttle parallel sessions on a single account, and serial is plenty fast at ~90 min total.
