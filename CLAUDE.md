# TableBuilder — Claude Code Notes

## Running scripts that use Playwright (browser automation)

All `scripts/build-dict.ts` runs **require a display**. On the headless server, always prefix with `xvfb-run -a`:

```bash
xvfb-run -a npx tsx scripts/build-dict.ts --only "Crime Victimisation, 2010-11" --skip-assemble
```

Without `xvfb-run`, Playwright launches headless but the JSF tree never renders (blank page screenshot, 68-byte HTML body).

## Dictionary builder (`scripts/build-dict.ts`)

Scrapes ABS TableBuilder catalogue → cache dir (`~/.tablebuilder/dict_cache/`) → SQLite DB.

```bash
xvfb-run -a npx tsx scripts/build-dict.ts --only "<fuzzy name>"   # one dataset
xvfb-run -a npx tsx scripts/build-dict.ts --skip-assemble          # scrape only
xvfb-run -a npx tsx scripts/build-dict.ts --assemble-only          # build DB from existing cache
xvfb-run -a npx tsx scripts/build-dict.ts --retry-failed           # re-run .error.json entries
```

Credentials: `~/.tablebuilder/.env` → `TABLEBUILDER_USER_ID` / `TABLEBUILDER_PASSWORD`.

## Key ABS TableBuilder gotchas

### URLs
- Login: `https://tablebuilder.abs.gov.au/webapi/jsf/login.xhtml`
- Catalogue: `https://tablebuilder.abs.gov.au/webapi/jsf/dataCatalogueExplorer.xhtml`  
  (**not** the bare `/dataCatalogueExplorer.xhtml` — that returns a 68-byte empty shell)
- TableView: `https://tablebuilder.abs.gov.au/webapi/jsf/tableView/tableView.xhtml`

### JSF tree expansion is slow and multi-pass
The catalogue tree requires **3+ rounds** of expansion to reveal all datasets (e.g. 31 → 18 → 10 nodes across rounds). Each JSF tree click blocks Playwright's actionability check for ~4 s because of CSS transitions. Key mitigations in `src/shared/abs/navigator.ts`:

- CSS transitions are disabled via `page.addStyleTag` before clicking, bringing click time from ~4 s to ~300 ms.
- `expandAllCollapsed` deadline is 600 s (not 30 s) — the catalogue tree needs ~20 min end-to-end with login.
- `.collapsed` class is added by JSF **asynchronously** after node count stabilises; polling uses `page.evaluate(() => document.querySelectorAll(...).length)` rather than `page.locator().count()` because Playwright locators can return stale results during active AJAX processing.

### `page.evaluate` with function strings must be IIFEs
`page.evaluate("() => { ... }")` evaluates the string as an expression, returning the function object (non-serialisable → `undefined`). Use `"(() => { ... })()"` to self-invoke.

### Cache slug format
Cache files use `slugify(datasetName)` from `src/dict-builder/walker.ts`. Example:  
`"2021 Census - cultural diversity"` → `2021_census_-_cultural_diversity` (underscores, lowercase, commas stripped).

## Project structure (dict-builder pipeline)

```
scripts/build-dict.ts          CLI entry — login, queue, scrape loop, summary
src/dict-builder/
  cache.ts                     read/write .json and .error.json cache files
  scraper.ts                   extract() — expands tableView tree, returns ExtractedDataset
  assembler.ts                 build SQLite DB from cache dir
  walker.ts                    parseVariableLabel, slugify, shouldExpandVariable
  types.ts                     ExtractedDataset, ExtractedGroup, ExtractedVariable, …
src/shared/abs/
  auth.ts                      login(), acceptTerms(), loadCredentials()
  navigator.ts                 listDatasets(), selectDataset(), expandAllCollapsed()
  reporter.ts                  PhaseReporter, CancelledError, NEVER_ABORT
```
