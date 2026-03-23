# Session Recovery for Dictionary Extraction

## Problem

During batch dictionary extraction (`extract_all_datasets`), the ABS TableBuilder
session expires after ~40 minutes. When this happens, `list_datasets()` returns 0
datasets and every remaining dataset fails with "No dataset matching". In the
2026-03-04 run, 24 of 25 failures were caused by a single session timeout at 00:02,
not by actual missing datasets. One failure (Net Overseas Migration) was a genuine
dataset issue.

## Approach: Relogin Callback (Approach A)

Pass an optional `relogin` callback to `extract_all_datasets()`. When a session
expiration is detected, call it to re-authenticate, then retry the current dataset.

## Changes

### 1. `browser.py` -- Add `relogin()` public method

One-line method on `TableBuilderSession` that calls the existing `_login()`.

### 2. `navigator.py` -- Add `SessionExpiredError`

New exception subclass of `NavigationError`. Raised from `open_dataset()` when
`list_datasets()` returns an empty list. An empty catalogue is unambiguous evidence
that the session has expired -- the catalogue always has datasets when logged in.

### 3. `tree_extractor.py` -- Catch `SessionExpiredError`, relogin, retry

- New parameter: `relogin: Callable[[], None] | None = None`
- Catch `SessionExpiredError` in the extraction loop
- Call `relogin()` and retry the current dataset
- Cap at 2 relogin attempts per run (constant `MAX_RELOGINS = 2`)
- If `relogin` is None or max attempts reached, fall through to existing error handling

### 4. `cli.py` -- Wire up the callback

Store the `TableBuilderSession` object before entering the context manager. Pass
`session.relogin` as the callback to `extract_all_datasets()`.

```python
session = TableBuilderSession(config, headless=not headed, knowledge=knowledge)
with session as page:
    trees = extract_all_datasets(page, relogin=session.relogin, ...)
```

## Detection Logic

Session expiration is detected structurally, not by string matching:

1. `open_dataset()` calls `list_datasets()` which returns an empty list
2. `open_dataset()` raises `SessionExpiredError` (not generic `NavigationError`)
3. `extract_all_datasets()` catches `SessionExpiredError` specifically
4. Calls `relogin()` callback, which navigates to login page and re-authenticates
5. Retries the current dataset

## Backward Compatibility

- `relogin` parameter defaults to `None` -- existing callers are unaffected
- `SessionExpiredError` is a subclass of `NavigationError` -- existing `except NavigationError` handlers still catch it
- No signature changes to `list_datasets()`, `extract_dataset_tree()`, or other public functions
