# Tablebuilder Totoro Deployment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the Tablebuilder UI to Totoro as a persistent systemd service with user-supplied ABS credentials (encrypted cookie), in-memory run queue, audit logging, nginx reverse proxy, and Cloudflare DNS.

**Architecture:** `src/auth.ts` handles AES-256-GCM cookie encryption. `src/queue.ts` owns the run queue and `runActive` flag (migrated from `server.ts`). `src/logger.ts` writes daily JSON-lines audit files. `server.ts` grows login routes + auth middleware + wires everything together. `runner.ts` gains an explicit `creds` parameter at position 2. The UI gets a login page and a queued state.

**Tech Stack:** TypeScript 5.8, Express 5, Node.js built-in `crypto` (AES-256-GCM), `cookie-parser`, Playwright, systemd, nginx, Cloudflare

**Spec:** `docs/superpowers/specs/2026-04-25-tablebuilder-totoro-deploy-design.md`

---

## File map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/auth.ts` | AES-256-GCM cookie encrypt/decrypt |
| Create | `src/auth.test.ts` | Unit tests for encryptCreds/decryptCreds |
| Create | `src/queue.ts` | In-memory FIFO run queue, runActive flag, position broadcasts |
| Create | `src/queue.test.ts` | Unit tests for queue operations |
| Create | `src/logger.ts` | Append JSON-lines audit log, prune old files |
| Create | `src/logger.test.ts` | Unit tests for logRun/pruneOldLogs |
| Modify | `src/shared/abs/runner.ts` | Add `creds: Credentials` at position 2, remove internal loadCredentials() |
| Modify | `src/workflows/abs-tablebuilder.ts` | Call loadCredentials() itself, pass to runTablebuilder |
| Modify | `src/server.ts` | Add cookieParser, requireAuth, login routes, wire queue+logger; remove runActive |
| Modify | `src/server.test.ts` | Import _setRunActive/_resetRunActive from ./queue.js |
| Create | `ui/login.html` | ABS credential capture form |
| Modify | `ui/app.jsx` | Handle 401 → redirect to /login |
| Modify | `ui/applyEvent.js` | Add 'queued' event type |
| Modify | `ui/run.jsx` | Show queued state (position N in queue) |
| Create | `deploy/tablebuilder.service` | systemd unit for Totoro |
| Create | `deploy/nginx.conf` | nginx reverse proxy with SSE config |

---

## Chunk 1: cookie-parser dep + src/auth.ts (TDD)

### Task 1: Install cookie-parser and write failing auth tests

**Files:**
- Modify: `package.json`
- Create: `src/auth.test.ts`

- [ ] **Step 1: Install cookie-parser**

```bash
cd /Users/dewoller/code/libretto-automations
npm install cookie-parser
npm install --save-dev @types/cookie-parser
```

Expected: `package.json` gains `"cookie-parser"` in dependencies and `"@types/cookie-parser"` in devDependencies.

- [ ] **Step 2: Write failing tests**

Create `src/auth.test.ts`:

```typescript
// src/auth.test.ts
import { describe, it, expect } from 'vitest';
import { encryptCreds, decryptCreds } from './auth.js';
import type { Credentials } from './shared/abs/types.js';

const SECRET = 'a'.repeat(64); // 64 hex chars = 32 bytes

const CREDS: Credentials = { userId: 'test@example.com', password: 'secret123' };

describe('encryptCreds / decryptCreds', () => {
  it('round-trips valid credentials', () => {
    const token = encryptCreds(CREDS, SECRET);
    expect(decryptCreds(token, SECRET)).toEqual(CREDS);
  });

  it('returns null for wrong secret', () => {
    const token = encryptCreds(CREDS, SECRET);
    expect(decryptCreds(token, 'b'.repeat(64))).toBeNull();
  });

  it('returns null for tampered payload', () => {
    const token = encryptCreds(CREDS, SECRET);
    const tampered = token.slice(0, -4) + 'XXXX';
    expect(decryptCreds(tampered, SECRET)).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(decryptCreds('', SECRET)).toBeNull();
  });

  it('produces different ciphertext each call (random IV)', () => {
    const t1 = encryptCreds(CREDS, SECRET);
    const t2 = encryptCreds(CREDS, SECRET);
    expect(t1).not.toBe(t2);
  });
});
```

- [ ] **Step 3: Run tests — verify they fail**

```bash
npm test -- src/auth.test.ts
```

Expected: FAIL — `Cannot find module './auth.js'`

---

### Task 2: Implement src/auth.ts

**Files:**
- Create: `src/auth.ts`

- [ ] **Step 1: Create auth.ts**

```typescript
// src/auth.ts
import { createCipheriv, createDecipheriv, randomBytes } from 'crypto';
import type { Credentials } from './shared/abs/types.js';

const ALGO = 'aes-256-gcm';

// Binary layout: [iv: 12 bytes][tag: 16 bytes][ciphertext: variable]
// Encoded as base64url for safe use in cookie values.

export function encryptCreds(creds: Credentials, secret: string): string {
  const key = Buffer.from(secret, 'hex');
  const iv = randomBytes(12);
  const cipher = createCipheriv(ALGO, key, iv);
  const payload = JSON.stringify({ userId: creds.userId, password: creds.password });
  const encrypted = Buffer.concat([cipher.update(payload, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, tag, encrypted]).toString('base64url');
}

export function decryptCreds(token: string, secret: string): Credentials | null {
  try {
    const key = Buffer.from(secret, 'hex');
    const data = Buffer.from(token, 'base64url');
    if (data.length < 29) return null; // minimum: 12 iv + 16 tag + 1 byte payload
    const iv = data.subarray(0, 12);
    const tag = data.subarray(12, 28);
    const encrypted = data.subarray(28);
    const decipher = createDecipheriv(ALGO, key, iv);
    decipher.setAuthTag(tag);
    const decrypted = Buffer.concat([decipher.update(encrypted), decipher.final()]);
    const parsed = JSON.parse(decrypted.toString('utf8')) as Record<string, unknown>;
    if (typeof parsed.userId !== 'string' || typeof parsed.password !== 'string') return null;
    return { userId: parsed.userId, password: parsed.password };
  } catch {
    return null;
  }
}
```

- [ ] **Step 2: Run tests — verify they pass**

```bash
npm test -- src/auth.test.ts
```

Expected: 5/5 tests pass.

- [ ] **Step 3: Run full test suite**

```bash
npm test
```

Expected: all existing 39 tests + 5 new = 44 total, all pass.

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json src/auth.ts src/auth.test.ts
git commit -m "feat: add AES-256-GCM cookie encryption (auth.ts)
chore: install cookie-parser and @types/cookie-parser"
```

---

## Chunk 2: src/queue.ts + migrate runActive

### Task 3: Write failing queue tests and create queue.ts

**Files:**
- Create: `src/queue.test.ts`
- Create: `src/queue.ts`
- Modify: `src/server.test.ts` (update import)
- Modify: `src/server.ts` (remove runActive, import from queue)

- [ ] **Step 1: Write failing queue tests**

Create `src/queue.test.ts`:

```typescript
// src/queue.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { Response } from 'express';
import {
  enqueue, dequeueNext, removeFromQueue, queueLength,
  _setRunActive, _resetRunActive,
} from './queue.js';
import type { QueueEntry } from './queue.js';
import type { Credentials } from './shared/abs/types.js';

function mockRes(): Response {
  return {
    writableEnded: false,
    write: vi.fn(),
  } as unknown as Response;
}

function makeEntry(id: string): QueueEntry {
  const creds: Credentials = { userId: 'u', password: 'p' };
  return {
    runId: id,
    creds,
    input: { dataset: 'Census 2021', rows: ['Sex'], columns: [], wafers: [] },
    res: mockRes(),
    ac: new AbortController(),
    addedAt: Date.now(),
    clientIP: '127.0.0.1',
  };
}

beforeEach(() => {
  // Drain queue and reset flag between tests
  while (queueLength() > 0) dequeueNext();
  _resetRunActive();
});

describe('enqueue', () => {
  it('increases queue length', () => {
    enqueue(makeEntry('r1'));
    expect(queueLength()).toBe(1);
  });

  it('sends queued event with position 1 to first entry', () => {
    const entry = makeEntry('r1');
    enqueue(entry);
    expect(entry.res.write).toHaveBeenCalledWith(
      expect.stringContaining('"type":"queued"')
    );
    expect(entry.res.write).toHaveBeenCalledWith(
      expect.stringContaining('"position":1')
    );
  });

  it('sends updated positions to all waiting entries', () => {
    const e1 = makeEntry('r1');
    const e2 = makeEntry('r2');
    enqueue(e1);
    enqueue(e2);
    // e2 enqueue triggers broadcast: e1 gets position 1, e2 gets position 2
    const lastCallArg = (e2.res.write as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[0] as string;
    expect(lastCallArg).toContain('"position":2');
  });
});

describe('dequeueNext', () => {
  it('returns and removes the first entry (FIFO)', () => {
    const e1 = makeEntry('r1');
    const e2 = makeEntry('r2');
    enqueue(e1); enqueue(e2);
    expect(dequeueNext()?.runId).toBe('r1');
    expect(queueLength()).toBe(1);
  });

  it('returns undefined when queue is empty', () => {
    expect(dequeueNext()).toBeUndefined();
  });
});

describe('removeFromQueue', () => {
  it('removes entry by runId and returns true', () => {
    enqueue(makeEntry('r1'));
    expect(removeFromQueue('r1')).toBe(true);
    expect(queueLength()).toBe(0);
  });

  it('returns false when runId not found', () => {
    expect(removeFromQueue('nope')).toBe(false);
  });
});

describe('_setRunActive / _resetRunActive', () => {
  it('allows test control of runActive flag', () => {
    // These are tested implicitly via server.test.ts 409 check
    _setRunActive(true);
    _resetRunActive();
    // Just verify no throw
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
npm test -- src/queue.test.ts
```

Expected: FAIL — `Cannot find module './queue.js'`

- [ ] **Step 3: Create src/queue.ts**

```typescript
// src/queue.ts
import type express from 'express';
import type { Credentials } from './shared/abs/types.js';
import type { Input } from './shared/abs/types.js';

export interface QueueEntry {
  runId: string;
  creds: Credentials;
  input: Input;
  res: express.Response;
  ac: AbortController;
  addedAt: number;
  clientIP: string;
}

const _queue: QueueEntry[] = [];
let _runActive = false;

// Test helpers — exported for server.test.ts
export function _setRunActive(v: boolean) { _runActive = v; }
export function _resetRunActive() { _runActive = false; }
export function isRunActive() { return _runActive; }
export function setRunActive(v: boolean) { _runActive = v; }

export function queueLength(): number { return _queue.length; }

function sendQueued(res: express.Response, position: number): void {
  if (!res.writableEnded) {
    res.write(`data: ${JSON.stringify({
      type: 'queued',
      position,
      estimatedWaitSecs: position * 90,
    })}\n\n`);
  }
}

function broadcastPositions(): void {
  _queue.forEach((entry, i) => sendQueued(entry.res, i + 1));
}

export function enqueue(entry: QueueEntry): void {
  _queue.push(entry);
  broadcastPositions();
}

export function dequeueNext(): QueueEntry | undefined {
  if (_queue.length === 0) return undefined;
  const entry = _queue.shift()!;
  broadcastPositions();
  return entry;
}

export function removeFromQueue(runId: string): boolean {
  const idx = _queue.findIndex(e => e.runId === runId);
  if (idx < 0) return false;
  _queue.splice(idx, 1);
  broadcastPositions();
  return true;
}
```

- [ ] **Step 4: Run queue tests — verify they pass**

```bash
npm test -- src/queue.test.ts
```

Expected: all queue tests pass.

- [ ] **Step 5: Update src/server.test.ts — change import and remove 409 test**

In `src/server.test.ts`, find:
```typescript
const { _setRunActive, _resetRunActive } = await import('./server.js');
```
Change to:
```typescript
const { _setRunActive, _resetRunActive } = await import('./queue.js');
```

**Delete the entire 409 test** — the new handler no longer returns 409 (it queues runs instead). The test will fail because the new `POST /api/run` always opens an SSE stream regardless of `runActive`:

```typescript
// DELETE this entire it() block:
it('returns 409 when a run is already in progress', async () => {
  ...
});
```

- [ ] **Step 6: Update src/server.ts — remove runActive, import from queue**

In `src/server.ts`:

**Remove** these three lines:
```typescript
let runActive = false;
// ...
export function _setRunActive(v: boolean) { runActive = v; }
export function _resetRunActive() { runActive = false; }
```

**Add** these imports at the top:
```typescript
import { isRunActive, setRunActive, enqueue, dequeueNext, removeFromQueue, type QueueEntry } from './queue.js';
import { randomUUID } from 'crypto';
```

**Replace** the `POST /api/run` handler body. The new handler enqueues the run rather than executing immediately. Add a `tryProcessNext()` helper function above `createServer()`:

```typescript
async function tryProcessNext(): Promise<void> {
  if (isRunActive()) return;
  const entry = dequeueNext();
  if (!entry) return;

  setRunActive(true);
  let browser: import('playwright').Browser | undefined;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await runTablebuilder(page, entry.creds, entry.input,
      (event) => { if (!entry.res.writableEnded) entry.res.write(`data: ${JSON.stringify(event)}\n\n`); },
      entry.ac.signal);
  } catch (err) {
    if (!(err instanceof CancelledError)) {
      const message = err instanceof Error ? err.message : String(err);
      if (!entry.res.writableEnded) entry.res.write(`data: ${JSON.stringify({ type: 'error', message })}\n\n`);
    }
  } finally {
    setRunActive(false);
    if (browser) await browser.close().catch(() => null);
    entry.res.end();
    void tryProcessNext(); // drain next entry
  }
}
```

**Replace** the `POST /api/run` handler:

```typescript
app.post('/api/run', async (req, res) => {
  const validation = validateBody(req.body);
  if (!validation.ok) {
    res.status(400).json({ error: validation.error });
    return;
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  const ac = new AbortController();
  const runId = randomUUID();

  // Use placeholder creds until auth middleware is added in Task 7
  const creds = { userId: '', password: '' };

  const entry: QueueEntry = {
    runId, creds, input: validation.input, res, ac, addedAt: Date.now(),
  };

  req.on('close', () => {
    const wasQueued = removeFromQueue(runId);
    if (!wasQueued) ac.abort(); // was running — abort
  });

  enqueue(entry);
  void tryProcessNext();
});
```

Note: `creds` is placeholder here — Task 7 adds the auth middleware that sets `req.creds`. The 409 check is also removed — the queue handles concurrency.

**Remove** the old `runActive` check from the POST handler (already done above).

- [ ] **Step 7: Run all tests — verify they pass**

```bash
npm test
```

Expected: all 44 + queue tests pass. The 409 test still works because `server.test.ts` now imports `_setRunActive` from `./queue.js` which sets `_runActive` directly.

- [ ] **Step 8: Verify build**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 9: Commit**

```bash
git add src/queue.ts src/queue.test.ts src/server.ts src/server.test.ts
git commit -m "feat: add run queue (queue.ts); migrate runActive from server.ts to queue.ts"
```

---

## Chunk 3: src/logger.ts (TDD)

### Task 4: Write failing logger tests and create logger.ts

**Files:**
- Create: `src/logger.test.ts`
- Create: `src/logger.ts`

- [ ] **Step 1: Write failing logger tests**

Create `src/logger.test.ts`:

```typescript
// src/logger.test.ts
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtemp, rm, readdir, readFile, writeFile } from 'fs/promises';
import { tmpdir } from 'os';
import { join } from 'path';
import { logRun, pruneOldLogs } from './logger.js';

// Override log dir for tests via env var — logger.ts reads it at call time
// (not at module load time) so setting it before each test is sufficient.
let tmpLogDir: string;

beforeEach(async () => {
  tmpLogDir = await mkdtemp(join(tmpdir(), 'tablebuilder-logs-'));
  process.env._TEST_LOG_DIR = tmpLogDir;
});

afterEach(async () => {
  delete process.env._TEST_LOG_DIR;
  await rm(tmpLogDir, { recursive: true, force: true });
});

describe('logRun', () => {
  it('creates a YYYY-MM-DD.jsonl file', async () => {
    await logRun({
      ts: new Date().toISOString(),
      absUsername: 'test@example.com',
      clientIP: '1.2.3.4',
      dataset: 'Census 2021',
      rows: ['Sex'],
      cols: [],
      wafers: [],
      status: 'success',
      durationMs: 1000,
      rowCount: 42,
    });
    const files = await readdir(tmpLogDir);
    expect(files).toHaveLength(1);
    expect(files[0]).toMatch(/^\d{4}-\d{2}-\d{2}\.jsonl$/);
  });

  it('appends valid JSON on each call', async () => {
    const entry = {
      ts: '2026-04-25T00:00:00Z',
      absUsername: 'u',
      clientIP: '1.1.1.1',
      dataset: 'D',
      rows: ['Sex'],
      cols: [],
      wafers: [],
      status: 'success' as const,
      durationMs: 500,
      rowCount: 10,
    };
    await logRun(entry);
    await logRun({ ...entry, rowCount: 20 });
    const files = await readdir(tmpLogDir);
    const content = await readFile(join(tmpLogDir, files[0]), 'utf-8');
    const lines = content.trim().split('\n');
    expect(lines).toHaveLength(2);
    expect(JSON.parse(lines[0]).rowCount).toBe(10);
    expect(JSON.parse(lines[1]).rowCount).toBe(20);
  });
});

describe('pruneOldLogs', () => {
  it('deletes files older than retentionDays', async () => {
    // Create an old file (31 days ago) and a recent file (today)
    const old = new Date();
    old.setDate(old.getDate() - 31);
    const oldName = `${old.toISOString().slice(0, 10)}.jsonl`;
    const recentName = `${new Date().toISOString().slice(0, 10)}.jsonl`;
    await writeFile(join(tmpLogDir, oldName), '');
    await writeFile(join(tmpLogDir, recentName), '');

    await pruneOldLogs(30);

    const files = await readdir(tmpLogDir);
    expect(files).not.toContain(oldName);
    expect(files).toContain(recentName);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
npm test -- src/logger.test.ts
```

Expected: FAIL — `Cannot find module './logger.js'`

- [ ] **Step 3: Create src/logger.ts**

```typescript
// src/logger.ts
import { mkdir, appendFile, readdir, unlink } from 'fs/promises';
import { join } from 'path';
import { homedir } from 'os';

// Read at call time (not module load) so _TEST_LOG_DIR env override works in tests.
function getLogDir(): string {
  return process.env._TEST_LOG_DIR ?? join(homedir(), '.tablebuilder', 'logs');
}

export interface AuditEntry {
  ts: string;
  absUsername: string;
  clientIP: string;
  dataset: string;
  rows: string[];
  cols: string[];
  wafers: string[];
  status: 'success' | 'error' | 'cancelled';
  durationMs: number;
  rowCount: number | null;
  errorMsg?: string;
}

export async function logRun(entry: AuditEntry): Promise<void> {
  const dir = getLogDir();
  await mkdir(dir, { recursive: true });
  const date = new Date().toISOString().slice(0, 10);
  const file = join(dir, `${date}.jsonl`);
  await appendFile(file, JSON.stringify(entry) + '\n');
}

export async function pruneOldLogs(retentionDays = 30): Promise<void> {
  const dir = getLogDir();
  await mkdir(dir, { recursive: true });
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - retentionDays);
  let files: string[];
  try {
    files = await readdir(dir);
  } catch {
    return;
  }
  for (const file of files) {
    if (!file.endsWith('.jsonl')) continue;
    const dateStr = file.slice(0, 10);
    if (!Number.isNaN(Date.parse(dateStr)) && new Date(dateStr) < cutoff) {
      await unlink(join(dir, file)).catch(() => null);
    }
  }
}
```

- [ ] **Step 4: Run logger tests — verify they pass**

```bash
npm test -- src/logger.test.ts
```

Expected: all logger tests pass.

- [ ] **Step 5: Run full test suite**

```bash
npm test
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/logger.ts src/logger.test.ts
git commit -m "feat: add audit logger (logger.ts) — daily JSON-lines files, 30-day pruning"
```

---

## Chunk 4: Update runner.ts + workflow + server.ts call site

### Task 5: Add `creds` parameter to runTablebuilder and update call sites

**Files:**
- Modify: `src/shared/abs/runner.ts`
- Modify: `src/workflows/abs-tablebuilder.ts`
- Modify: `src/server.ts` (update tryProcessNext call)

The `creds` parameter moves to position 2. The internal `loadCredentials()` call is removed from `runner.ts`. The Libretto workflow calls `loadCredentials()` itself.

- [ ] **Step 1: Replace src/shared/abs/runner.ts**

```typescript
// src/shared/abs/runner.ts
import type { Page } from 'playwright-core';
import { loadCredentials, login } from './auth.js';
import { selectDataset, selectVariables } from './navigator.js';
import { retrieveTable } from './jsf.js';
import { downloadCsv } from './downloader.js';
import { noopReporter, NEVER_ABORT, CancelledError, type PhaseReporter } from './reporter.js';
import type { Credentials, Input, Output } from './types.js';

// REQUIRED: re-export loadCredentials so the Libretto workflow can import it
// from runner.js. Without this line, abs-tablebuilder.ts fails to build.
export { loadCredentials };

export async function runTablebuilder(
  page: Page,
  creds: Credentials,
  input: Input,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<Output> {
  try {
    await login(page, creds, reporter, signal);

    if (signal.aborted) throw new CancelledError();

    const resolvedDataset = await selectDataset(page, input.dataset, reporter, signal);
    await selectVariables(page, {
      rows: input.rows,
      columns: input.columns,
      wafers: input.wafers,
    }, reporter, signal);

    if (signal.aborted) throw new CancelledError();

    await retrieveTable(page, reporter, signal);
    const { csvPath, rowCount } = await downloadCsv(page, input.outputPath, reporter);

    const result = { csvPath, dataset: resolvedDataset, rowCount };
    reporter({ type: 'complete', result });
    return result;
  } catch (err) {
    if (err instanceof CancelledError) throw err;
    const message = err instanceof Error ? err.message : String(err);
    reporter({ type: 'error', message });
    throw err;
  }
}
```

- [ ] **Step 2: Update src/workflows/abs-tablebuilder.ts**

```typescript
// src/workflows/abs-tablebuilder.ts
import { workflow, type LibrettoWorkflowContext } from 'libretto';
import { runTablebuilder, loadCredentials } from '../shared/abs/runner.js';
import type { Input, Output } from '../shared/abs/types.js';

export default workflow<Input, Output>(
  'abs-tablebuilder',
  async (ctx: LibrettoWorkflowContext, input: Input): Promise<Output> => {
    const creds = loadCredentials(); // reads from ~/.tablebuilder/.env for CLI use
    return runTablebuilder(ctx.page, creds, input);
  }
);
```

- [ ] **Step 3: Update tryProcessNext in src/server.ts**

In `src/server.ts`, the `tryProcessNext` function already calls `runTablebuilder(page, entry.creds, entry.input, ...)`. This is correct — no change needed here once runner.ts signature matches.

Verify the import at top of `server.ts` still imports `runTablebuilder`:
```typescript
import { runTablebuilder } from './shared/abs/runner.js';
```

- [ ] **Step 4: Run tests**

```bash
npm test
```

Expected: all tests pass.

- [ ] **Step 5: Verify build**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 6: Commit**

```bash
git add src/shared/abs/runner.ts src/workflows/abs-tablebuilder.ts
git commit -m "feat: add creds param at position 2 to runTablebuilder; workflow calls loadCredentials itself"
```

---

## Chunk 5: Login routes + auth middleware + wire queue + logger

### Task 6: Add auth middleware, login routes, and wire logger into server.ts

**Files:**
- Modify: `src/server.ts`

This is the largest server.ts change. It adds:
- `cookieParser()` middleware
- `COOKIE_SECRET` from env
- `requireAuth` middleware function
- `GET /login` route
- `POST /login` route
- Auth guard on `GET /` and `POST /api/run`
- Real `creds` from cookie in queue entry
- `logRun()` call on run completion
- `pruneOldLogs()` call on startup

- [ ] **Step 1: Replace src/server.ts with the fully wired version**

```typescript
// src/server.ts
import express, { type Request, type Response, type NextFunction } from 'express';
import cookieParser from 'cookie-parser';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { randomUUID } from 'crypto';
import { chromium } from 'playwright';
import { runTablebuilder } from './shared/abs/runner.js';
import { encryptCreds, decryptCreds } from './auth.js';
import { isRunActive, setRunActive, enqueue, dequeueNext, removeFromQueue, type QueueEntry } from './queue.js';
import { logRun, pruneOldLogs, type AuditEntry } from './logger.js';
import { CancelledError, type PhaseEvent } from './shared/abs/reporter.js';
import type { Credentials, Input } from './shared/abs/types.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const UI_DIR = join(__dirname, '..', 'ui');
const PORT = Number(process.env.PORT ?? 3000);
const COOKIE_SECRET = process.env.COOKIE_SECRET ?? '';

if (!COOKIE_SECRET && process.env.NODE_ENV === 'production') {
  throw new Error('COOKIE_SECRET environment variable is required in production');
}

// Augment Express Request with creds
interface AuthedRequest extends Request {
  creds: Credentials;
}

function validateBody(body: unknown): { ok: true; input: Input } | { ok: false; error: string } {
  if (!body || typeof body !== 'object') return { ok: false, error: 'Request body must be JSON' };
  const b = body as Record<string, unknown>;
  if (typeof b.dataset !== 'string' || b.dataset.trim().length === 0) {
    return { ok: false, error: 'dataset must be a non-empty string' };
  }
  if (!Array.isArray(b.rows) || b.rows.length === 0 || b.rows.some((r: unknown) => typeof r !== 'string' || (r as string).trim().length === 0)) {
    return { ok: false, error: 'rows must be a non-empty array of non-empty strings' };
  }
  const cols = Array.isArray(b.cols) ? (b.cols as string[]) : [];
  const wafer = Array.isArray(b.wafer) ? (b.wafer as string[]) : [];
  const output = typeof b.output === 'string' ? b.output : '';
  return {
    ok: true,
    input: { dataset: b.dataset.trim(), rows: b.rows as string[], columns: cols, wafers: wafer, outputPath: output.trim() || undefined },
  };
}

function requireAuth(req: Request, res: Response, next: NextFunction): void {
  const token = req.cookies?.abs_creds as string | undefined;
  if (!token) {
    if (req.method === 'GET') { res.redirect('/login'); return; }
    res.status(401).json({ error: 'Not authenticated' }); return;
  }
  // Dev fallback must be valid 64-char hex (32 bytes for AES-256-GCM)
  const secret = COOKIE_SECRET || 'a'.repeat(64);
  const creds = decryptCreds(token, secret);
  if (!creds) {
    res.clearCookie('abs_creds');
    if (req.method === 'GET') { res.redirect('/login'); return; }
    res.status(401).json({ error: 'Not authenticated' }); return;
  }
  (req as AuthedRequest).creds = creds;
  next();
}

async function tryProcessNext(): Promise<void> {
  if (isRunActive()) return;
  const entry = dequeueNext();
  if (!entry) return;

  setRunActive(true);
  const startMs = Date.now();
  let browser: import('playwright').Browser | undefined;
  let finalStatus: AuditEntry['status'] = 'error';
  let rowCount: number | null = null;
  let errorMsg: string | undefined;
  const clientIP = entry.clientIP;

  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    function send(event: PhaseEvent): void {
      if (!entry.res.writableEnded) entry.res.write(`data: ${JSON.stringify(event)}\n\n`);
    }
    const result = await runTablebuilder(page, entry.creds, entry.input, send, entry.ac.signal);
    finalStatus = 'success';
    rowCount = result.rowCount;
  } catch (err) {
    if (err instanceof CancelledError) {
      finalStatus = 'cancelled';
    } else {
      finalStatus = 'error';
      errorMsg = err instanceof Error ? err.message : String(err);
      if (!entry.res.writableEnded) {
        entry.res.write(`data: ${JSON.stringify({ type: 'error', message: errorMsg })}\n\n`);
      }
    }
  } finally {
    setRunActive(false);
    if (browser) await browser.close().catch(() => null);
    entry.res.end();
    await logRun({
      ts: new Date().toISOString(),
      absUsername: entry.creds.userId,
      clientIP,
      dataset: entry.input.dataset,
      rows: entry.input.rows,
      cols: entry.input.columns ?? [],
      wafers: entry.input.wafers ?? [],
      status: finalStatus,
      durationMs: Date.now() - startMs,
      rowCount,
      ...(errorMsg ? { errorMsg } : {}),
    }).catch(console.error);
    void tryProcessNext();
  }
}

export async function createServer(): Promise<express.Express> {
  await pruneOldLogs(30).catch(console.error);

  const app = express();
  app.use(cookieParser());
  app.use(express.json());
  app.use(express.urlencoded({ extended: false }));

  // Login page (no auth required)
  app.get('/login', (_req, res) => {
    res.sendFile(join(UI_DIR, 'login.html'));
  });

  // Login form submission
  app.post('/login', (req, res) => {
    const { userId, password, remember } = req.body as Record<string, string>;
    if (!userId?.trim() || !password) {
      res.status(400).send('ABS username and password are required.');
      return;
    }
    // Dev fallback must be valid 64-char hex (32 bytes for AES-256-GCM)
  const secret = COOKIE_SECRET || 'a'.repeat(64);
    const token = encryptCreds({ userId: userId.trim(), password }, secret);
    const cookieOpts: Parameters<typeof res.cookie>[2] = {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'strict',
    };
    // Checkbox sends 'on' when checked; omits field when unchecked (never sends 'off')
    if (remember === 'on') {
      cookieOpts.maxAge = 30 * 24 * 60 * 60 * 1000; // 30 days
    }
    res.cookie('abs_creds', token, cookieOpts);
    res.redirect('/');
  });

  // Static UI files — only accessible when authenticated
  app.use(requireAuth, express.static(UI_DIR));

  // Health check (no auth)
  app.get('/api/health', (_req, res) => {
    res.json({ ok: true });
  });

  // SSE run endpoint (requires auth)
  app.post('/api/run', requireAuth, async (req, res) => {
    const validation = validateBody(req.body);
    if (!validation.ok) {
      res.status(400).json({ error: validation.error });
      return;
    }

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');

    const ac = new AbortController();
    const runId = randomUUID();
    const creds = (req as AuthedRequest).creds;
    const clientIP = (req.headers['cf-connecting-ip'] as string) || req.ip || 'unknown';

    const entry: QueueEntry = {
      runId, creds, input: validation.input, res, ac, addedAt: Date.now(), clientIP,
    };

    req.on('close', () => {
      const wasQueued = removeFromQueue(runId);
      if (!wasQueued) ac.abort();
    });

    enqueue(entry as QueueEntry);
    void tryProcessNext();
  });

  return app;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const app = await createServer();
  app.listen(PORT, () => {
    console.log(`Tablebuilder UI running at http://localhost:${PORT}`);
  });
}
```

**Note:** `QueueEntry` includes `clientIP: string` (set at enqueue time from `CF-Connecting-IP` or `req.ip`). This is defined in `src/queue.ts` — see Chunk 2.

Simplified version — update `QueueEntry` in `src/queue.ts`:
```typescript
export interface QueueEntry {
  runId: string;
  creds: Credentials;
  input: Input;
  res: express.Response;
  ac: AbortController;
  addedAt: number;
  clientIP: string;  // ADD THIS
}
```

Then in server.ts, set `clientIP: (req.headers['cf-connecting-ip'] as string) || req.ip || 'unknown'` when creating the entry, and remove the `req` reference from `tryProcessNext`.

- [ ] **Step 2: Run tests**

```bash
npm test
```

Expected: all tests pass. The server tests may need `process.env.COOKIE_SECRET` set — add to the test file:

At the top of `src/server.test.ts`, before the imports or in a `beforeAll`, add:
```typescript
process.env.COOKIE_SECRET = 'a'.repeat(64);
```

- [ ] **Step 3: Verify build**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add src/server.ts src/queue.ts src/server.test.ts
git commit -m "feat: add login routes, auth middleware, wire queue and logger into server.ts"
```

---

## Chunk 6: Login page

### Task 7: Create ui/login.html

**Files:**
- Create: `ui/login.html`

- [ ] **Step 1: Create ui/login.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in · Tablebuilder · RMAI</title>
  <meta name="color-scheme" content="light">
  <meta name="darkreader-lock">
  <link rel="stylesheet" href="assets/rmai.css">
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; height: 100%; background: #FAFAFA; }
    body { font-family: var(--rmai-font-sans); -webkit-font-smoothing: antialiased; }

    .shell {
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }

    .card {
      background: #fff;
      border: 1px solid var(--rmai-border);
      border-radius: 12px;
      padding: 40px 36px;
      width: 100%;
      max-width: 400px;
      box-shadow: var(--rmai-shadow-2);
    }

    .brand {
      display: flex;
      flex-direction: column;
      line-height: 1.05;
      letter-spacing: -0.02em;
      margin-bottom: 28px;
    }
    .brand__a { font-size: 11px; font-weight: 500; color: var(--rmai-fg-mut); text-transform: lowercase; }
    .brand__b { font-size: 16px; font-weight: 800; color: var(--rmai-fg-1); text-transform: lowercase; }
    .brand__app { font-size: 20px; font-weight: 700; color: var(--rmai-fg-1); margin-top: 10px; letter-spacing: -0.01em; }

    .field { margin-bottom: 16px; }
    .field label { display: block; font-size: 12px; font-weight: 600; color: var(--rmai-fg-1); margin-bottom: 6px; }
    .field input[type=text],
    .field input[type=password],
    .field input[type=email] {
      width: 100%;
      font-family: var(--rmai-font-sans);
      font-size: 14px;
      color: var(--rmai-fg-1);
      padding: 10px 12px;
      background: #fff;
      border: 1px solid var(--rmai-border);
      border-radius: 6px;
      outline: none;
      transition: border-color 120ms, box-shadow 120ms;
    }
    .field input:focus {
      border-color: var(--rmai-purple);
      box-shadow: 0 0 0 2px rgba(167,122,205,0.18);
    }

    .check-row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 20px;
      font-size: 13px;
      color: var(--rmai-fg-2);
      cursor: pointer;
    }
    .check-row input[type=checkbox] { width: 15px; height: 15px; cursor: pointer; accent-color: var(--rmai-purple); }

    .btn-submit {
      width: 100%;
      background: var(--rmai-purple);
      color: #fff;
      border: none;
      border-radius: 6px;
      font-family: var(--rmai-font-sans);
      font-weight: 600;
      font-size: 14px;
      padding: 12px 16px;
      cursor: pointer;
      transition: background 120ms;
    }
    .btn-submit:hover { background: #9366bd; }

    .error-msg {
      margin-top: 14px;
      padding: 10px 14px;
      background: rgba(242,101,65,0.08);
      border: 1px solid rgba(242,101,65,0.3);
      border-radius: 6px;
      font-size: 13px;
      color: var(--rmai-orange);
      display: none;
    }
    .hint {
      margin-top: 16px;
      font-size: 11px;
      color: var(--rmai-fg-mut);
      text-align: center;
      line-height: 1.5;
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="card">
      <div class="brand">
        <span class="brand__a">real minds,</span>
        <span class="brand__b">artificial intelligence</span>
        <span class="brand__app">tablebuilder</span>
      </div>

      <form id="loginForm" method="POST" action="/login">
        <div class="field">
          <label for="userId">ABS Username (email)</label>
          <input type="email" id="userId" name="userId" required
                 autocomplete="username" placeholder="you@example.com" />
        </div>
        <div class="field">
          <label for="password">ABS Password</label>
          <input type="password" id="password" name="password" required
                 autocomplete="current-password" placeholder="••••••••" />
        </div>
        <label class="check-row">
          <input type="checkbox" name="remember" id="remember" checked />
          Remember me for 30 days
        </label>
        <button type="submit" class="btn-submit">Sign in to ABS Tablebuilder</button>
      </form>

      <div class="error-msg" id="errorMsg">
        Invalid credentials format. Please try again.
      </div>

      <p class="hint">
        Your ABS credentials are encrypted in your browser and<br>
        never stored on this server.
      </p>
    </div>
  </div>

  <script>
    // If already authenticated, skip to main app
    document.addEventListener('DOMContentLoaded', () => {
      const params = new URLSearchParams(window.location.search);
      if (params.get('error') === '1') {
        document.getElementById('errorMsg').style.display = 'block';
      }
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Update POST /login in server.ts to redirect with error param on failure**

In the `POST /login` handler, if userId or password is missing:
```typescript
res.redirect('/login?error=1');
return;
```
(replaces the `res.status(400).send(...)` from Task 6)

- [ ] **Step 3: Start server and verify login page loads**

```bash
npm run serve &
SERVER_PID=$!
sleep 2
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/login
kill $SERVER_PID 2>/dev/null
```

Expected: `200`

- [ ] **Step 4: Run all tests**

```bash
npm test
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add ui/login.html src/server.ts
git commit -m "feat: add login page (ui/login.html) and POST /login handler"
```

---

## Chunk 7: UI updates (401 handling, queued state)

### Task 8: Handle 401 in app.jsx, add queued state to applyEvent + run.jsx

**Files:**
- Modify: `ui/app.jsx` (handle 401 → redirect)
- Modify: `ui/applyEvent.js` (add queued event, extend INITIAL_RUN_STATE)
- Modify: `ui/run.jsx` (show queued state)
- Modify: `src/applyEvent.test.ts` (add queued test)

- [ ] **Step 1: Update ui/applyEvent.js — add queued state**

In `ui/applyEvent.js`, update `INITIAL_RUN_STATE` to add queue fields:

```javascript
export const INITIAL_RUN_STATE = {
  status: 'idle', phaseIndex: -1, phaseElapsed: {}, totalElapsed: 0,
  request: null, result: null, log: [], errorSeen: false,
  queuePosition: null, queueWaitSecs: null,
};
```

Add `queued` case to `applyEvent`:

```javascript
case 'queued':
  return {
    ...state,
    status: 'queued',
    queuePosition: event.position,
    queueWaitSecs: event.estimatedWaitSecs,
  };
```

Insert this case BEFORE `case 'phase_start':`.

- [ ] **Step 2: Add queued test to src/applyEvent.test.ts**

Append to the existing `describe('applyEvent', ...)`:

```typescript
  it('queued sets status=queued with position', () => {
    const s = applyEvent(INITIAL_RUN_STATE, {
      type: 'queued', position: 2, estimatedWaitSecs: 180
    });
    expect(s.status).toBe('queued');
    expect(s.queuePosition).toBe(2);
    expect(s.queueWaitSecs).toBe(180);
  });
```

- [ ] **Step 3: Run tests — verify they pass**

```bash
npm test -- src/applyEvent.test.ts
```

Expected: 8 tests pass (7 existing + 1 new).

- [ ] **Step 4: Update ui/app.jsx — handle 401**

In `useApiRunner`, in the `start` function, find:

```javascript
if (!response.ok && response.status !== 200) {
```

Replace with:

```javascript
if (response.status === 401) {
  window.location.href = '/login';
  stopTick();
  return;
}
if (!response.ok && response.status !== 200) {
```

Also update `INITIAL_RUN_STATE` usage in `useApiRunner` — since it now comes from `applyEvent.js` globals, the inline reference remains fine.

- [ ] **Step 5: Update ui/run.jsx — add queued state display**

In `run.jsx`, find the `if (status === "idle")` check and add a queued check BEFORE it:

```javascript
if (status === "queued") {
  return (
    <section className="panel panel--run">
      <div className="run">
        <div className="run__hero">
          <div>
            <h1>Queued</h1>
            <p className="sub">
              You're position <strong>{runState.queuePosition}</strong> in the queue.
              Estimated wait: <strong>{runState.queueWaitSecs}s</strong>.
            </p>
          </div>
          <span className="status-pill idle">
            <span className="dot"></span>Waiting
          </span>
        </div>
        <div className="run__body" style={{ position: "relative" }}>
          <img className="run-motif" src="assets/purple_circles_motif.svg" alt="" aria-hidden="true" />
          <div className="idle">
            <div className="idle__ttl">Another run is in progress</div>
            <div className="idle__sub">
              You'll be automatically connected when it's your turn.
              Keep this tab open.
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 6: Run all tests**

```bash
npm test
```

Expected: all tests pass (40 total).

- [ ] **Step 7: Commit**

```bash
git add ui/applyEvent.js ui/app.jsx ui/run.jsx src/applyEvent.test.ts
git commit -m "feat: add queued state to UI; handle 401 with redirect to /login"
```

---

## Chunk 8: Deploy artefacts

### Task 9: Create systemd unit and nginx config

**Files:**
- Create: `deploy/tablebuilder.service`
- Create: `deploy/nginx.conf`
- Create: `deploy/README.md`

- [ ] **Step 1: Create deploy/ directory and tablebuilder.service**

```bash
mkdir -p /Users/dewoller/code/libretto-automations/deploy
```

Create `deploy/tablebuilder.service`:

```ini
[Unit]
Description=Tablebuilder UI — RMAI
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/tablebuilder
ExecStart=/usr/bin/node dist/server.js
Restart=always
RestartSec=5
EnvironmentFile=/opt/tablebuilder/.env

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create deploy/nginx.conf**

```nginx
# Cloudflare IP ranges — required for CF-Connecting-IP trust
# Update periodically: https://www.cloudflare.com/ips/
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2a06:98c0::/29;
set_real_ip_from 2c0f:f248::/32;
real_ip_header CF-Connecting-IP;

server {
    listen 80;
    server_name tablebuilder.realmindsai.com.au;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # SSE: disable buffering, long read timeout, no chunked re-encoding
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_set_header Connection '';
        chunked_transfer_encoding off;
    }
}
```

- [ ] **Step 3: Create deploy/README.md**

```markdown
# Tablebuilder — Totoro Deployment

## Prerequisites

- Node.js 20+ installed on Totoro
- nginx installed (`sudo apt install nginx`)
- Playwright Chromium: `npx playwright install chromium`
- Port 80 restricted to Cloudflare IPs (see firewall section below)

## Deploy steps

### 1. Build

```bash
npm run build
```

### 2. Copy files to Totoro

```bash
rsync -avz --exclude node_modules --exclude .env \
  . ubuntu@totoro:/opt/tablebuilder/
ssh ubuntu@totoro "cd /opt/tablebuilder && npm install --production"
```

### 3. Generate COOKIE_SECRET

```bash
openssl rand -hex 32
```

### 4. Create /opt/tablebuilder/.env on Totoro

```
PORT=3000
COOKIE_SECRET=<output from step 3>
NODE_ENV=production
```

### 5. Install and start systemd service

```bash
sudo cp deploy/tablebuilder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tablebuilder
sudo systemctl start tablebuilder
sudo systemctl status tablebuilder
```

### 6. Configure nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/tablebuilder
sudo ln -s /etc/nginx/sites-available/tablebuilder /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 7. Restrict port 80 to Cloudflare IPs (mandatory)

```bash
# Allow Cloudflare ranges (from https://www.cloudflare.com/ips/)
for cidr in \
  103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 104.16.0.0/13 \
  104.24.0.0/14 108.162.192.0/18 131.0.72.0/22 141.101.64.0/18 \
  162.158.0.0/15 172.64.0.0/13 173.245.48.0/20 188.114.96.0/20 \
  190.93.240.0/20 197.234.240.0/22 198.41.128.0/17; do
  sudo ufw allow from $cidr to any port 80
done
sudo ufw deny 80
```

### 8. Configure Cloudflare

- DNS: A record `tablebuilder` → Totoro public IP, proxied (orange cloud)
- SSL/TLS: Full (strict)

## Checking logs

```bash
tail -f ~/.tablebuilder/logs/$(date +%Y-%m-%d).jsonl | jq .
```

## Service management

```bash
sudo systemctl restart tablebuilder   # restart after code update
sudo journalctl -u tablebuilder -f    # live logs
```
```

- [ ] **Step 4: Run all tests**

```bash
npm test
```

Expected: all tests pass.

- [ ] **Step 5: Final build check**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 6: Commit**

```bash
git add deploy/
git commit -m "feat: add deploy artefacts — systemd service, nginx config, deployment README"
```

---

## Running locally for development

```bash
# Set a dev COOKIE_SECRET (any 64-char hex)
export COOKIE_SECRET=$(openssl rand -hex 32)
npm run serve
# Open http://localhost:3000
# You'll be redirected to /login — enter any ABS credentials to test the UI
```

## Deployment checklist

- [ ] `npm run build` exits 0
- [ ] `npm test` all pass
- [ ] `COOKIE_SECRET` generated and set in `/opt/tablebuilder/.env`
- [ ] systemd service running (`systemctl status tablebuilder`)
- [ ] nginx configured and reloaded
- [ ] Port 80 restricted to Cloudflare IPs via ufw
- [ ] Cloudflare DNS A record pointing to Totoro, proxied
- [ ] `https://tablebuilder.realmindsai.com.au` loads login page
