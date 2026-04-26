# Tablebuilder UI + Express SSE Server — Design Spec

**Date:** 2026-04-25  
**Status:** Approved (v2 — reviewer fixes applied)

---

## Goal

Add a polished React web UI to the existing ABS TableBuilder automation. The UI (already designed as a static HTML prototype) connects to a new Express server that runs the real `abs-tablebuilder.ts` workflow and streams phase-by-phase progress back to the browser via Server-Sent Events over a POST response body.

---

## 1. Architecture

### Directory layout (additions and modifications)

```
ui/                          ← static files, served by Express at /
  index.html                 ← renamed from Tablebuilder.html
  app.jsx                    ← modified: adds useApiRunner alongside useRunner
  form.jsx                   ← unchanged
  run.jsx                    ← unchanged
  tweaks-panel.jsx           ← unchanged
  data.js                    ← unchanged (mock data + helpers)
  styles.css                 ← unchanged
  assets/
    rmai.css
    purple_circles_motif.svg

src/
  server.ts                  ← NEW: Express static + SSE endpoint
  shared/abs/
    reporter.ts              ← NEW: PhaseReporter type + PhaseEvent union
    auth.ts                  ← modified: accepts reporter + signal, emits login events
    navigator.ts             ← modified: emits dataset / tree / check events
    jsf.ts                   ← modified: emits submit / retrieve events
    downloader.ts            ← modified: emits download event
  workflows/
    abs-tablebuilder.ts      ← modified: accepts reporter + signal, passes through
```

### New dependencies

| Package | Purpose |
|---------|---------|
| `express` | HTTP server — static files + SSE endpoint |
| `@types/express` | TypeScript types for Express (dev) |
| `tsx` | Run TypeScript ESM directly without a build step (dev) |

---

## 2. PhaseReporter (`src/shared/abs/reporter.ts`)

A single callback type threaded through the entire workflow. No classes, no EventEmitter — just a function.

```typescript
export type PhaseEvent =
  | { type: 'phase_start';    phaseId: string; phaseLabel: string; phaseSub: string }
  | { type: 'phase_complete'; phaseId: string; elapsed: number }
  | { type: 'phase_error';    phaseId: string; message: string }
  | { type: 'log';            level: 'info' | 'ok' | 'warn' | 'err' | 'phase'; message: string }
  | { type: 'complete';       result: { csvPath: string; dataset: string; rowCount: number } }
  | { type: 'error';          message: string };

export type PhaseReporter = (event: PhaseEvent) => void;

export const noopReporter: PhaseReporter = () => {};

// A signal that never aborts — safe default for callers that don't need cancellation.
// Module-level singleton so there is exactly one instance, avoiding GC-triggered abort.
const _neverAbortAC = new AbortController();
export const NEVER_ABORT: AbortSignal = _neverAbortAC.signal;

export class CancelledError extends Error {
  constructor() { super('Run cancelled by user'); }
}
```

`noopReporter` keeps all existing call sites working — callers that don't care about progress pass `noopReporter`. Each helper uses `NEVER_ABORT` as the default `signal` (not `new AbortController().signal`, which would create a fresh instance eligible for GC).

---

## 3. The seven phases

The UI and the workflow share exactly this ordered list:

| # | Phase ID   | Label                     | Sub-label                            | Emitted by      |
|---|------------|---------------------------|--------------------------------------|-----------------|
| 1 | `login`    | Logging in                | auth · tablebuilder.abs.gov.au       | `auth.ts`       |
| 2 | `dataset`  | Selecting dataset         | resolving dataset from catalog       | `navigator.ts`  |
| 3 | `tree`     | Expanding variable tree   | walking classification nodes         | `navigator.ts`  |
| 4 | `check`    | Checking categories       | selecting leaf categories            | `navigator.ts`  |
| 5 | `submit`   | Submitting table dimensions | POST /table/layout                 | `navigator.ts`  |
| 6 | `retrieve` | Retrieving table data     | ABS is computing the table           | `jsf.ts`        |
| 7 | `download` | Downloading result        | streaming CSV                        | `downloader.ts` |

`acceptTerms` (in `auth.ts`) is folded into the `login` phase — it fires after the login redirect and before phase_complete. If the terms page is not present, the login phase simply completes faster.

`submit` is emitted from inside `selectVariables` in `navigator.ts` (not from `jsf.ts` directly), because `submitJsfForm` is called once per variable inside the `selectVariables` loop. The `tree`, `check`, and `submit` phases are emitted once for the first variable; subsequent variables emit only `log` events so the phase stepper doesn't flicker.

---

## 4. Workflow instrumentation

Each helper gains two optional trailing parameters:

```typescript
reporter: PhaseReporter = noopReporter,
signal: AbortSignal = new AbortController().signal,
```

The `signal` is an `AbortSignal` — the same one created by the server when `req.on('close')` fires. Inner loops check `signal.aborted` at each iteration and throw `CancelledError` immediately.

### Instrumentation per helper

**`auth.ts` — login phase**

```
phase_start login
log: "  connecting to tablebuilder.abs.gov.au..."
[await page.goto + fill + click]
log: "  ✓ session cookie set · user=analyst"
[acceptTerms if needed — no additional phase, just a log]
phase_complete login (elapsed)
```

**`navigator.ts` — dataset, tree, check, submit phases**

`selectDataset`:
```
phase_start dataset
log: "  resolved dataset: <name>"
phase_complete dataset (elapsed)
```

`selectVariables` (called once with all vars):

The actual code structure in `navigator.ts` is:
1. `expandAllCollapsed` runs once as a pre-loop step (not inside the variable loop)
2. A per-variable loop then runs `checkVariableCategories` + `submitJsfForm` for each variable

The phase instrumentation follows this structure:

```
phase_start tree
[expandAllCollapsed — checks signal.aborted at each expansion round]
log: "  expanded N classification branches"
phase_complete tree (elapsed)

phase_start check
for each variable:
  [checkVariableCategories — checks signal.aborted]
  log: "  selected M categories for <varName>"
phase_complete check (elapsed)

phase_start submit
for each variable:
  [submitJsfForm — checks signal.aborted before call]
  log: "  POST /TableBuilder/view/layout → 202 accepted for <varName>"
phase_complete submit (elapsed)
```

All three phases fire once (not once per variable). Per-variable progress is conveyed via `log` events inside each phase.

**`jsf.ts` — retrieve phase**

```
phase_start retrieve
log: "  waiting on ABS compute engine… this may take a moment"
[poll loop — checks signal.aborted each iteration]
phase_complete retrieve (elapsed)
```

**`downloader.ts` — download phase**

```
phase_start download
log: "  streaming bytes → <outputPath>"
[download + optional ZIP extraction]
phase_complete download (elapsed)
```

### Error handling

On any thrown error that is not `CancelledError`:
1. Helper catches, emits `{ type: 'phase_error', phaseId, message }`
2. Helper re-throws
3. Workflow's top-level catch emits `{ type: 'error', message }` and closes the SSE response

On `CancelledError`: workflow propagates it up, server catches it, closes the response **without** emitting `error`. UI receives only a stream close (reader returns `done: true`) and sets `status = 'cancelled'`.

The client receives at most one `phase_error` and one `error` per failed run. Because React 18's concurrent rendering means rendered state may not have committed by the time the `error` event arrives, the guard **must not rely on the rendered `status` value**. Instead, the state object carries an `errorSeen: boolean` flag. `applyEvent` for `phase_error` sets `errorSeen: true`. `applyEvent` for `error` checks `state.errorSeen` before overwriting — if already true, it only updates `result.errorMsg` and leaves `status` unchanged.

---

## 5. Express server (`src/server.ts`)

### Routes

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/*` | Serve `ui/` as static files |
| `POST` | `/api/run` | SSE stream — runs the workflow |
| `GET`  | `/api/health` | Returns `{ ok: true }` |

### SSE endpoint

```
POST /api/run
Content-Type: application/json
Body: { dataset, rows, cols, wafer, output }

Response headers:
  Content-Type: text/event-stream
  Cache-Control: no-cache
  Connection: keep-alive
  X-Accel-Buffering: no

Event stream (newline-delimited JSON, SSE format):
  data: {"type":"phase_start","phaseId":"login",...}\n\n
  data: {"type":"log","level":"info","message":"  connecting..."}\n\n
  data: {"type":"phase_complete","phaseId":"login","elapsed":2.3}\n\n
  ...
  data: {"type":"complete","result":{"csvPath":"...","dataset":"...","rowCount":189}}\n\n
```

### Cancel / connection close

```typescript
const ac = new AbortController();
req.on('close', () => ac.abort());
// Pass ac.signal into the workflow
```

### Input validation

The server validates JSON before starting the workflow:
- `dataset`: non-empty string
- `rows`: non-empty array of non-empty strings (table requires at least one row variable)
- `cols`, `wafer`: arrays (may be empty — empty cols produces a table with only row variables, which is valid; ABS will return a single-column result)
- `output`: string (may be empty — workflow applies default timestamped path)

Returns `400 { error: "..." }` if invalid.

### Concurrency: run lock

A module-level boolean `let runActive = false` guards the endpoint. A second `POST /api/run` while one is in flight receives `409 { error: "A run is already in progress" }`. One Playwright browser instance is launched per request and closed on run completion, error, or cancel.

`runActive` is reset in a `finally` block that wraps the entire workflow invocation — including browser open/close — so any unhandled Playwright crash or unhandled rejection cannot permanently lock the server:

```typescript
runActive = true;
try {
  await runWorkflow(body, reporter, ac.signal);
} finally {
  runActive = false;
  res.end();
}
```

### Port

Defaults to `3000`, overridable via `PORT` env var.

### CORS

The UI is served from the same Express origin, so no CORS headers are needed. No `cors()` middleware.

---

## 6. UI changes (`ui/app.jsx`)

### New hook: `useApiRunner`

Replaces `useRunner`'s `setInterval` simulation when running on localhost. Produces the same `runState` shape so `RunPanel` is untouched.

```javascript
function useApiRunner(onComplete) {
  const [runState, setRunState] = useState({ status: 'idle', phaseIndex: -1,
    phaseElapsed: {}, totalElapsed: 0, request: null, result: null, log: [],
    errorSeen: false });
  const abortRef = useRef(null);
  const tickRef = useRef(null);  // elapsed ticker (updates every 100ms)

  async function start(request) {
    abortRef.current = new AbortController();
    // start elapsed ticker
    const startMs = Date.now();
    tickRef.current = setInterval(() => {
      setRunState(s => ({ ...s, totalElapsed: (Date.now() - startMs) / 1000 }));
    }, 100);

    let state = { status: 'running', phaseIndex: -1, phaseElapsed: {},
      totalElapsed: 0, request, result: null, log: [] };
    setRunState({ ...state });

    try {
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        signal: abortRef.current.signal,
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop();
        for (const chunk of chunks) {
          const raw = chunk.replace(/^data: /, '').trim();
          if (!raw) continue;
          const event = JSON.parse(raw);
          state = applyEvent(state, event);
          setRunState({ ...state });
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        state = { ...state, status: 'cancelled' };
        setRunState({ ...state });
      }
    } finally {
      clearInterval(tickRef.current);
    }
    onComplete?.(state);
  }

  function cancel() { abortRef.current?.abort(); }
  function reset() { clearInterval(tickRef.current);
    setRunState({ status: 'idle', phaseIndex: -1, phaseElapsed: {},
      totalElapsed: 0, request: null, result: null, log: [] }); }

  return { runState, start, cancel, reset };
}
```

### `applyEvent` (pure function)

```javascript
function applyEvent(state, event) {
  const t = fmtTimestamp(state.totalElapsed);
  switch (event.type) {
    case 'phase_start':
      return { ...state,
        phaseIndex: PHASES.findIndex(p => p.id === event.phaseId),
        log: [...state.log, { t, lv: 'phase', msg: `» ${event.phaseLabel}` }] };
    case 'phase_complete':
      return { ...state,
        phaseElapsed: { ...state.phaseElapsed, [event.phaseId]: event.elapsed } };
    case 'log':
      return { ...state, log: [...state.log, { t, lv: event.level, msg: event.message }] };
    case 'complete':
      return { ...state, status: 'success', result: event.result };
    case 'phase_error':
      return { ...state, status: 'error', errorSeen: true,
        phaseIndex: PHASES.findIndex(p => p.id === event.phaseId),
        log: [...state.log, { t, lv: 'err', msg: `  ✗ ${event.message}` }] };
    case 'error':
      // Guard on errorSeen flag (not rendered status) to survive React 18 concurrent rendering
      if (state.errorSeen) return { ...state, result: { ...state.result, errorMsg: event.message } };
      return { ...state, status: 'error', result: { errorMsg: event.message } };
    default: return state;
  }
}
```

### Mode selection

`App` checks `window.location.hostname`. If `localhost` or `127.0.0.1`, `useApiRunner` is used; otherwise `useRunner` (simulation). The tweaks panel demo/failure buttons always call `useRunner.start()` directly regardless of mode.

---

## 7. package.json additions

```json
"serve": "tsx src/server.ts",
"serve:prod": "node dist/server.js"
```

---

## 8. Testing

### `reporter.ts` — no unit tests (pure type exports)

### Server smoke tests (`src/server.test.ts`)

Mock the workflow import so no browser launches:
- `GET /api/health` → `{ ok: true }`, status 200
- `POST /api/run` with missing `dataset` → 400
- `POST /api/run` with empty `rows` → 400
- `POST /api/run` while `runActive = true` → 409

### `applyEvent` unit tests

`applyEvent` is a pure function — test all event types in isolation, including the double-error guard.

### Existing tests

All existing unit + integration tests pass unchanged. Each modified helper's optional `reporter` and `signal` parameters default to `noopReporter` and a non-aborting signal.

### E2E test extension

The existing `ABS_RUN_E2E=1` test passes a collector reporter and asserts:
1. All 7 phase IDs fire `phase_start` events in the correct order
2. All 7 phase IDs fire `phase_complete` events
3. Final `complete` event has `rowCount > 0`

---

## 9. Out of scope

- Authentication/authorisation on the HTTP server (localhost only, no auth needed)
- Queue-based large-table download (existing `downloader.ts` limitation, tracked separately)
- HTTPS
- Multiple concurrent users
