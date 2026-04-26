# ABS TableBuilder Queue-Based Download: Design Spec

**Date:** 2026-04-24
**Status:** Draft

## Context

The existing `downloadCsv` function in `src/shared/abs/downloader.ts` uses a two-step fallback chain:

1. **Direct download** — waits 15s for a Playwright download event or HTTP response with `Content-Disposition: attachment`
2. **DOM extraction** — reads the visible table cells from `pageForm:dataTable` and writes them as CSV

During E2E testing against the live ABS site, the direct download was found to trigger JSF AJAX rather than a browser file download. DOM extraction works as a last resort but produces whatever is currently rendered on the page (which may be confidentialised `-` values or incomplete data).

The ABS provides a queue-based download mechanism: submit a table to a server-side queue, poll the saved tables page (`openTable.xhtml`) until the file is ready, then download the completed file. This produces the actual full CSV that the ABS server generated — more reliable than DOM scraping.

## Goal

Add a queue-based download step between direct download and DOM extraction. The chain becomes:

```
direct download (15s) → queue-based download → DOM extraction (last resort)
```

## Architecture

```
src/shared/abs/
  downloader.ts           ← MODIFY: call queueDownload between saveDownload and readTableFromDom
  queue-downloader.ts     ← NEW: queue dialog + poll logic (single export)
```

`queue-downloader.ts` exports exactly one function:

```typescript
export async function queueDownload(page: Page, tmpPath: string): Promise<void>
```

All queue-specific selectors, URLs, and timing constants live in `queue-downloader.ts`. `downloader.ts` imports and calls it; it does not know the internals.

## Queue Flow

```
queueDownload(page, tmpPath)
  │
  ├─ openQueueDialog(page)
  │    → click #pageForm\:retB (second click, after data retrieval)
  │    → wait 5s for #downloadTableModeForm\:downloadTableNameTxt
  │    → if not found: retry once (same click + 5s wait)
  │    → if still not found: throw 'Queue dialog did not open — cannot submit table to queue'
  │
  ├─ fillAndSubmit(page, tableName)
  │    → fill #downloadTableModeForm\:downloadTableNameTxt with tableName
  │    → click #downloadTableModeForm\:queueTableButton (Playwright click)
  │    → wait 3s for submission AJAX to settle
  │
  ├─ navigate to SAVED_TABLES_URL
  │    https://tablebuilder.abs.gov.au/webapi/jsf/tableView/openTable.xhtml
  │
  └─ pollForDownload(page, tableName, tmpPath, deadline = 10 min)
       → every 5s: reload page + scan <tr> rows
       → match row where text contains tableName AND 'click here to download'
       → when found: Playwright-click the <a> element in that row
       → capture file via trySaveViaResponse() (imported from downloader.ts)
       → if deadline exceeded: throw 'Queue table did not complete within 10 minutes'
```

**Table name format:** `abs_q_<Date.now()>` — unique per run, identifiable in saved tables list.

**Download link:** `openTable.xhtml` rows use JSF onclick with `href="#"`. The `<a>` element must be clicked via Playwright (not navigated by URL) to trigger the JSF action.

**File capture:** reuses `trySaveViaResponse(page, clickFn, tmpPath, 60000)` from `downloader.ts`. This function must be changed from `async function` to `export async function` to make it importable. It intercepts the HTTP response (Content-Disposition or CSV MIME type) and also listens for Playwright download events simultaneously.

## Error Handling

All errors throw and propagate through `downloadCsv`. There is no silent fallback from queue to DOM within `queueDownload` itself — DOM extraction only runs because `queueDownload` threw.

| Failure point | Error thrown |
|---|---|
| Dialog didn't open after 2 attempts | `'Queue dialog did not open — cannot submit table to queue'` |
| Name input not found in open dialog | `'Queue dialog name input (#downloadTableModeForm:downloadTableNameTxt) not found'` |
| Submit button not found | `'Queue dialog submit button (#downloadTableModeForm:queueTableButton) not found'` |
| Poll exceeded 10 minutes | `'Queue table did not complete within 10 minutes'` |
| File capture failed after link click | propagates from `trySaveViaResponse` |

## Updated `downloadCsv` Chain

```typescript
// 1. Direct download (15s)
const directSuccess = await saveDownload(page, downloadBtn, tmpPath);
if (directSuccess) { /* save and return */ }

// 2. Queue-based download
try {
  await queueDownload(page, tmpPath);
  // save from tmpPath and return
} catch (err) {
  // queue failed — fall through to DOM extraction
  console.log('downloadCsv: queue download failed, trying DOM extraction:', err.message);
}

// 3. DOM extraction (last resort)
const domSuccess = await readTableFromDom(page, resolvedPath);
if (!domSuccess) throw new Error('Could not download table: all methods failed.');
```

## Testing

### Unit tests (`src/shared/abs/queue-downloader.test.ts`)

Mock the `page` object to verify:
- `openQueueDialog` retries exactly once on first failure, throws on second failure
- `fillAndSubmit` calls `page.fill` and `page.click` with the correct selectors
- `pollForDownload` exits immediately when matching row text is found
- `pollForDownload` throws after deadline with correct message

### Integration test (extend `src/workflows/abs-tablebuilder.test.ts`)

Use real Playwright + `page.setContent()` with a mock `openTable.xhtml` page that has a matching "click here to download" row. Verify:
- `pollForDownload` finds the row and clicks the link element
- `trySaveViaResponse` captures the response

### E2E

The existing `ABS_RUN_E2E=1` test covers the full path — if the ABS site's direct download fails (as it does currently), the queue flow will be exercised automatically.

## Constants (all in `queue-downloader.ts`)

`SAVED_TABLES_URL` is currently also declared in `downloader.ts` (line 9). Remove it from `downloader.ts` and keep the single definition here.

```typescript
const SAVED_TABLES_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/tableView/openTable.xhtml';
const QUEUE_DIALOG_SELECTOR = '#downloadTableModeForm\\:downloadTableNameTxt';
const QUEUE_SUBMIT_SELECTOR = '#downloadTableModeForm\\:queueTableButton';
const RETRIEVE_BTN_SELECTOR = '#pageForm\\:retB';
const DIALOG_WAIT_MS = 5000;
const SUBMIT_SETTLE_MS = 3000;
const POLL_INTERVAL_MS = 5000;
const POLL_TIMEOUT_MS = 600_000; // 10 minutes
```

## Out of Scope

- Cleanup of queued tables after download (left for a future pass)
- Configurable poll timeout (hardcoded at 10 minutes)
- Support for non-CSV queue formats (ABS also queues Excel; ignored here)
