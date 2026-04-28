// src/server.ts
import express, { type Request, type Response, type NextFunction, type CookieOptions } from 'express';
import cookieParser from 'cookie-parser';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { realpathSync, existsSync } from 'fs';
import { randomUUID } from 'crypto';
import { chromium } from 'playwright';
import { runTablebuilder } from './shared/abs/runner.js';
import { encryptCreds, decryptCreds } from './auth.js';
import { isRunActive, setRunActive, enqueue, dequeueNext, removeFromQueue, type QueueEntry } from './queue.js';
import { logRun, pruneOldLogs, type AuditEntry } from './logger.js';
import { CancelledError } from './shared/abs/reporter.js';
import type { Credentials, Input } from './shared/abs/types.js';
import Database from 'better-sqlite3';

const __dirname = dirname(fileURLToPath(import.meta.url));
// Find the project root by looking for ui/ directory.
// In dev (tsx), __dirname is src/, so ../ui works.
// In prod (dist), __dirname is dist/src, so ../../ui is needed.
const ui1 = join(__dirname, '..', 'ui');
const UI_DIR = existsSync(ui1) ? ui1 : join(__dirname, '..', '..', 'ui');
const PORT = Number(process.env.PORT ?? 3000);
const TEST_DB_OVERRIDE = process.env.TABLEBUILDER_TEST_DB_PATH;
const dictDb1 = join(__dirname, '..', 'docs', 'explorer', 'data', 'dictionary.db');
const dictDb2 = join(__dirname, '..', '..', 'docs', 'explorer', 'data', 'dictionary.db');
const DICT_DB = TEST_DB_OVERRIDE
  ? (existsSync(TEST_DB_OVERRIDE) ? TEST_DB_OVERRIDE : null)
  : (existsSync(dictDb1) ? dictDb1 : existsSync(dictDb2) ? dictDb2 : null);
const dictDb = DICT_DB ? new Database(DICT_DB, { readonly: true }) : null;

function hasGeographiesTable(db: Database.Database | null): boolean {
  if (!db) return false;
  const row = db.prepare(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='geographies'"
  ).get();
  return row != null;
}
const dictReady = hasGeographiesTable(dictDb);
if (dictDb && !dictReady) {
  console.warn('[server] dictionary.db is missing the geographies table — needs reassembly');
}
const COOKIE_SECRET = process.env.COOKIE_SECRET ?? '';

if (!COOKIE_SECRET && process.env.NODE_ENV === 'production') {
  throw new Error('COOKIE_SECRET environment variable is required in production');
}

// Dev fallback must be valid 64-char hex (32 bytes for AES-256-GCM)
const _secret = COOKIE_SECRET || 'a'.repeat(64);

// Fail fast if the key is the wrong length — better than crashing on first login
const _keyBytes = Buffer.from(_secret, 'hex');
if (_keyBytes.length !== 32) {
  throw new Error(`COOKIE_SECRET must be exactly 64 hex characters (got ${_secret.length})`);
}

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
  const creds = decryptCreds(token, _secret);
  if (!creds) {
    res.clearCookie('abs_creds');
    if (req.method === 'GET') { res.redirect('/login'); return; }
    res.status(401).json({ error: 'Not authenticated' }); return;
  }
  (req as AuthedRequest).creds = creds;
  next();
}

const RUN_TIMEOUT_MS = 5 * 60 * 1000; // 5-minute hard deadline per run

async function tryProcessNext(): Promise<void> {
  console.log(`[queue] tryProcessNext — runActive=${isRunActive()} queueLen=${isRunActive() ? '?' : 'checking'}`);
  if (isRunActive()) { console.log('[queue] skipping — run already active'); return; }
  const entry = dequeueNext();
  if (!entry) { console.log('[queue] queue empty'); return; }

  console.log(`[run:${entry.runId}] starting — dataset="${entry.input.dataset}" user="${entry.creds.userId}"`);
  setRunActive(true);
  const startMs = Date.now();
  let browser: import('playwright').Browser | undefined;
  let finalStatus: AuditEntry['status'] = 'error';
  let rowCount: number | null = null;
  let errorMsg: string | undefined;

  // Hard deadline: abort the run if it hasn't finished in 5 minutes
  const timeoutId = setTimeout(() => {
    console.log(`[run:${entry.runId}] TIMEOUT — aborting after ${RUN_TIMEOUT_MS / 1000}s`);
    entry.ac.abort();
  }, RUN_TIMEOUT_MS);

  try {
    console.log(`[run:${entry.runId}] launching Chromium…`);
    browser = await chromium.launch({ headless: true });
    console.log(`[run:${entry.runId}] Chromium launched — opening page`);
    const page = await browser.newPage();
    console.log(`[run:${entry.runId}] page opened — calling runTablebuilder`);
    const result = await runTablebuilder(page, entry.creds, entry.input,
      (event) => { if (!entry.res.writableEnded) entry.res.write(`data: ${JSON.stringify(event)}\n\n`); },
      entry.ac.signal);
    finalStatus = 'success';
    rowCount = result.rowCount;
    console.log(`[run:${entry.runId}] SUCCESS — ${rowCount} rows`);
  } catch (err) {
    if (err instanceof CancelledError) {
      finalStatus = 'cancelled';
      console.log(`[run:${entry.runId}] CANCELLED`);
    } else {
      finalStatus = 'error';
      errorMsg = err instanceof Error ? err.message : String(err);
      console.error(`[run:${entry.runId}] ERROR — ${errorMsg}`);
      if (!entry.res.writableEnded) {
        entry.res.write(`data: ${JSON.stringify({ type: 'error', message: errorMsg })}\n\n`);
      }
    }
  } finally {
    clearTimeout(timeoutId);
    console.log(`[run:${entry.runId}] finally — resetting runActive, closing browser`);
    setRunActive(false);
    if (browser) await browser.close().catch(() => null);
    entry.res.end();
    await logRun({
      ts: new Date().toISOString(),
      absUsername: entry.creds.userId,
      clientIP: entry.clientIP,
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
      res.redirect('/login?error=1');
      return;
    }
    const token = encryptCreds({ userId: userId.trim(), password }, _secret);
    const cookieOpts: CookieOptions = {
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

  // Health check (no auth) — must be registered before protected static middleware
  app.get('/api/health', (_req, res) => {
    res.json({ ok: true });
  });

  // Dataset list (no auth) — serves real ABS names from dictionary.db for the UI picker
  app.get('/api/datasets', (_req, res) => {
    if (!dictDb) { res.status(503).json({ error: 'Dataset dictionary unavailable' }); return; }
    const rows = dictDb.prepare('SELECT id, name FROM datasets ORDER BY name').all() as Array<{ id: number; name: string }>;
    res.json(rows.map(r => ({ id: r.id, name: r.name, code: null, tag: null, year: null })));
  });

  // Dataset metadata (no auth) — returns geographies, groups, and variables for a given dataset id
  app.get('/api/datasets/:id/metadata', (req, res) => {
    if (!dictDb) { res.status(503).json({ error: 'Dataset dictionary unavailable' }); return; }
    if (!dictReady) { res.status(503).json({ error: 'Dictionary out of date — needs reassembly' }); return; }
    const id = Number(req.params.id);
    if (!Number.isFinite(id)) { res.status(400).json({ error: 'id must be a number' }); return; }
    const dataset = dictDb.prepare('SELECT id, name FROM datasets WHERE id = ?').get(id) as { id: number; name: string } | undefined;
    if (!dataset) { res.status(404).json({ error: 'Unknown dataset' }); return; }
    const geographies = dictDb.prepare('SELECT id, label FROM geographies WHERE dataset_id = ? ORDER BY id').all(id) as Array<{ id: number; label: string }>;
    const groupRows = dictDb.prepare('SELECT id, label FROM groups WHERE dataset_id = ? ORDER BY id').all(id) as Array<{ id: number; label: string }>;
    const variablesByGroup = dictDb.prepare(
      'SELECT id, group_id, code, label FROM variables WHERE group_id IN (SELECT id FROM groups WHERE dataset_id = ?) ORDER BY label'
    ).all(id) as Array<{ id: number; group_id: number; code: string; label: string }>;
    const groups = groupRows.map(g => ({
      id: g.id,
      label: g.label,
      variables: variablesByGroup.filter(v => v.group_id === g.id).map(v => ({ id: v.id, code: v.code, label: v.label })),
    }));
    res.json({ id: dataset.id, name: dataset.name, geographies, groups });
  });

  // SSE run endpoint
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
    console.log(`[api/run] new request — runId=${runId} user=${creds.userId} dataset="${validation.input.dataset}" runActive=${isRunActive()}`);

    const entry: QueueEntry = {
      runId, creds, input: validation.input, res, ac, addedAt: Date.now(), clientIP,
    };

    // Use res.on('close') not req.on('close') — in Express 5, the request body
    // being fully parsed triggers req 'close' immediately for POST requests.
    // res 'close' fires when the SSE client actually disconnects.
    res.on('close', () => {
      console.log(`[run:${runId}] res closed by client`);
      const wasQueued = removeFromQueue(runId);
      if (!wasQueued) ac.abort();
    });

    enqueue(entry);
    void tryProcessNext();
  });

  // Static UI files — protected by auth (registered after API routes so /api/health stays open)
  app.use(requireAuth, express.static(UI_DIR));

  return app;
}

// Only start listening when this file is run directly (not when imported by tests)
// Resolve symlinks on macOS where /tmp → /private/tmp
if (realpathSync(process.argv[1] ?? '.') === realpathSync(fileURLToPath(import.meta.url))) {
  const app = await createServer();
  app.listen(PORT, () => {
    console.log(`Tablebuilder UI running at http://localhost:${PORT}`);
  });
}
