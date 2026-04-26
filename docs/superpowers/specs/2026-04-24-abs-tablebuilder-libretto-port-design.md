# ABS TableBuilder → Libretto Port: Design Spec

**Date:** 2026-04-24
**Status:** Draft

## Context

TableBuilder (`/Users/dewoller/code/rmai/tablebuilder/`) is a Python CLI that drives the Australian Bureau of Statistics (ABS) TableBuilder website to fetch census data and download it as CSV. It has ~5,000 lines across 10+ modules including a FastAPI service layer, a self-healing selector system with a knowledge base, and a Click CLI.

This spec covers porting only the **back-end browser automation** to Libretto — the parameterized flow that logs in, selects a dataset, configures row/column/wafer variables, and downloads a CSV. The CLI, service layer, self-healing machinery, and raw HTTP mode are explicitly out of scope.

## Goals

- Express the ABS fetch flow as a typed Libretto workflow taking dataset + variable parameters
- Port known JSF (JavaServer Faces) workarounds explicitly rather than discovering them at runtime
- Drop the fallback selector system — use primary selectors only, fix manually if ABS updates their UI
- Read credentials from the existing `~/.tablebuilder/.env` file (zero migration friction)

## Architecture

```
src/
  workflows/
    abs-tablebuilder.ts        ← thin orchestrator, ~50 lines
  shared/
    abs/
      types.ts                 ← Input/Output types, shared interfaces
      auth.ts                  ← dotenv credential load + login + terms acceptance
      navigator.ts             ← dataset fuzzy match + variable tree navigation
      jsf.ts                   ← JSF hidden form submission helpers + table retrieval
      downloader.ts            ← CSV format selection + download + ZIP extraction
    utils.ts                   ← existing shared utilities (unchanged)
```

Note: `src/shared/abs/` is a new subdirectory alongside the existing flat `src/shared/utils.ts`. No changes to `utils.ts`.

## Dependencies to Add

- `dotenv` — for reading `~/.tablebuilder/.env`
- `vitest` — test framework for unit and integration tests

Add to `package.json` before starting implementation:
```bash
npm install dotenv
npm install --save-dev vitest
```

## Types

```typescript
// src/shared/abs/types.ts

interface Input {
  dataset: string;        // fuzzy-matched against ABS dataset list
  rows: string[];         // variable names for row axis
  columns: string[];      // variable names for column axis
  wafers?: string[];      // optional layer variables
  outputPath?: string;    // defaults to timestamped path in output/
}

interface Output {
  csvPath: string;
  dataset: string;        // resolved dataset name (post fuzzy-match)
  rowCount: number;
}

interface Credentials {
  userId: string;
  password: string;
}
```

## Data Flow

The orchestrator calls each helper in sequence, passing the Playwright `page` object through. No intermediate state objects — `page` carries the session state.

```
abs-tablebuilder.ts
  │
  ├─ auth.loadCredentials()
  ├─ auth.login(page, creds)
  ├─ auth.acceptTerms(page)                           ← conditional, ABS shows intermittently
  ├─ navigator.selectDataset(page, input.dataset)
  ├─ navigator.selectVariables(page, { rows, columns, wafers })
  ├─ jsf.retrieveTable(page)                          ← triggers table population via JSF
  └─ downloader.downloadCsv(page, outputPath)
```

## File Breakdown

### `auth.ts`
- `loadCredentials(): Credentials` — reads `~/.tablebuilder/.env` via dotenv; env var names are `TABLEBUILDER_USER_ID` and `TABLEBUILDER_PASSWORD`; throws descriptive error if either is missing
- `login(page, creds)` — navigates to ABS login URL, fills credentials, submits, waits for redirect
- `acceptTerms(page)` — clicks accept button if terms dialog is present (conditional)

### `navigator.ts`
- `selectDataset(page, dataset): string` — loads dataset list, fuzzy-matches input string against names, clicks match, returns resolved name
- `selectVariables(page, { rows, columns, wafers })` — for each variable name, searches the tree UI, expands nodes, assigns to correct axis via axis selector dropdown

### `jsf.ts`
- `submitJsfForm(page, actionId)` — fires hidden JSF form submission using `page.evaluate()` to dispatch in-browser (sets `javax.faces.source`, `javax.faces.partial.execute`, triggers form POST from within the browser context — not raw HTTP)
- `waitForJsfResponse(page)` — waits for `partial-response` XHR to complete before proceeding
- `retrieveTable(page)` — clicks "Retrieve Data" button via JSF submission, waits for numeric values to appear in the table cells

### `downloader.ts`
- `downloadCsv(page, outputPath): string` — selects CSV from format dropdown, intercepts Playwright download event, extracts CSV from ZIP if needed, writes to `outputPath`, returns resolved path

## Large-Table Downloads (v1 Limitation)

The Python source has a queue-and-poll fallback for large tables (polls `SAVED_TABLES_URL`, waits up to 1200s). This is **not ported in v1**. If a table is too large for direct download, `downloadCsv` will throw a clear error: `"Table too large for direct download — queue-based download not supported in this version"`. Address in v2 if encountered.

## Error Handling

No custom retry decorators. Each helper throws a descriptive `Error` on failure; the workflow lets it bubble — Libretto captures and reports it. If a phase fails repeatedly in practice, a targeted `try/catch` with one retry is added to that helper only.

## Testing

**Framework:** vitest

### Unit (`src/shared/abs/*.test.ts`)
- `auth.test.ts` — mock dotenv, assert `loadCredentials` throws clearly on missing `TABLEBUILDER_USER_ID` or `TABLEBUILDER_PASSWORD`
- `navigator.test.ts` — test fuzzy-match logic in isolation (pure function, no browser)
- `jsf.test.ts` — assert `submitJsfForm` calls `page.evaluate()` with correct JSF params (mock `page.evaluate`)

### Integration (`src/workflows/abs-tablebuilder.test.ts`)
- Spin up a mock HTML page mimicking ABS JSF form structure
- Run full workflow against mock, assert it reaches download phase
- No real ABS credentials needed

### E2E (`tests/e2e/abs-tablebuilder.e2e.ts`)
- Runs against live ABS site with real credentials from `~/.tablebuilder/.env`
- Skipped unless `ABS_RUN_E2E` env var is set
- One known-good dataset/variable combo, asserts CSV exists and has rows

## Out of Scope

- Click CLI / FastAPI service layer
- Self-healing selector system and knowledge base
- Credential encryption
- Job queue / database / queue-based large-table download (v2)
- Raw HTTP mode (`requests`-based JSF submission)
