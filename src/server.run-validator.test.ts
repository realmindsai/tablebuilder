// src/server.run-validator.test.ts
// TDD tests for Task 5: {id,label} variable/geography refs through validator + runner input

import { vi, describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import os from 'node:os';
import Database from 'better-sqlite3';
import { encryptCreds } from './auth.js';

// ── Fixture DB builder ──────────────────────────────────────────────────────

function buildFixtureDb(dbPath: string): void {
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE datasets (
      id INTEGER PRIMARY KEY,
      name TEXT UNIQUE NOT NULL,
      summary TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE geographies (
      id INTEGER PRIMARY KEY,
      dataset_id INTEGER NOT NULL REFERENCES datasets(id),
      label TEXT NOT NULL
    );
    CREATE TABLE groups (
      id INTEGER PRIMARY KEY,
      dataset_id INTEGER NOT NULL REFERENCES datasets(id),
      label TEXT NOT NULL,
      path TEXT NOT NULL
    );
    CREATE TABLE variables (
      id INTEGER PRIMARY KEY,
      group_id INTEGER NOT NULL REFERENCES groups(id),
      code TEXT NOT NULL DEFAULT '',
      label TEXT NOT NULL,
      category_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE categories (
      id INTEGER PRIMARY KEY,
      variable_id INTEGER NOT NULL REFERENCES variables(id),
      label TEXT NOT NULL
    );
  `);

  db.exec(`
    INSERT INTO datasets (id, name) VALUES (1, 'Test Census Dataset');
    INSERT INTO datasets (id, name) VALUES (2, 'Other Dataset');

    INSERT INTO geographies (id, dataset_id, label) VALUES (10, 1, 'Australia');
    INSERT INTO geographies (id, dataset_id, label) VALUES (11, 1, 'New South Wales');
    INSERT INTO geographies (id, dataset_id, label) VALUES (20, 2, 'Victoria');

    INSERT INTO groups (id, dataset_id, label, path) VALUES (100, 1, 'Sex', 'Sex');
    INSERT INTO groups (id, dataset_id, label, path) VALUES (200, 1, 'Age', 'Age');
    INSERT INTO groups (id, dataset_id, label, path) VALUES (300, 2, 'Other Group', 'Other Group');

    INSERT INTO variables (id, group_id, code, label, category_count)
      VALUES (1001, 100, 'SEXP', 'Sex', 0);
    INSERT INTO variables (id, group_id, code, label, category_count)
      VALUES (1002, 200, 'AGEP', 'Age', 0);
    INSERT INTO variables (id, group_id, code, label, category_count)
      VALUES (2001, 300, 'OTHER', 'Other Var', 0);
  `);

  db.close();
}

// ── Auth helper ─────────────────────────────────────────────────────────────

// Dev key: 32 bytes of 0xaa
const TEST_SECRET = 'a'.repeat(64);

function makeAuthCookie(): string {
  const token = encryptCreds({ userId: 'testuser', password: 'testpass' }, TEST_SECRET);
  return `abs_creds=${token}`;
}

// ── Shared server setup ──────────────────────────────────────────────────────

let server: http.Server;
let baseUrl: string;
let tmpDir: string;

beforeAll(async () => {
  tmpDir = mkdtempSync(join(os.tmpdir(), 'tablebuilder-runval-'));
  const dbPath = join(tmpDir, 'fixture.db');
  buildFixtureDb(dbPath);

  process.env.TABLEBUILDER_TEST_DB_PATH = dbPath;
  vi.resetModules();
  const { createServer } = await import('./server.js');
  const app = await createServer();
  server = http.createServer(app as Parameters<typeof http.createServer>[1]);
  await new Promise<void>(resolve => server.listen(0, resolve));
  baseUrl = `http://localhost:${(server.address() as AddressInfo).port}`;
});

afterAll(() => {
  server.close();
  delete process.env.TABLEBUILDER_TEST_DB_PATH;
  rmSync(tmpDir, { recursive: true, force: true });
});

// ── Helper for POST /api/run ─────────────────────────────────────────────────

async function postRun(body: unknown): Promise<Response> {
  return fetch(`${baseUrl}/api/run`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Cookie: makeAuthCookie(),
    },
    body: JSON.stringify(body),
  });
}

// For "positive path" tests: post and immediately abort once we have response headers.
// This avoids hanging on the SSE stream while still letting us read the status code.
// If validation rejects, the server returns 400 before streaming — we catch that too.
async function postRunCheckStatus(body: unknown): Promise<{ status: number; json: unknown }> {
  const ac = new AbortController();
  // Abort after 500ms — enough time for validation to return but before Playwright hangs
  const timer = setTimeout(() => ac.abort(), 500);
  try {
    const res = await fetch(`${baseUrl}/api/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: makeAuthCookie(),
      },
      body: JSON.stringify(body),
      signal: ac.signal,
    });
    clearTimeout(timer);
    // For 400 responses, read the body; for 200 SSE, abort cleanly
    if (res.status === 400) {
      const json = await res.json();
      return { status: res.status, json };
    }
    // 200 SSE — drain minimally
    res.body?.cancel().catch(() => null);
    return { status: res.status, json: {} };
  } catch (e: unknown) {
    clearTimeout(timer);
    // AbortError means we got a 200 SSE stream (validation passed, Playwright started)
    if (e instanceof Error && (e.name === 'AbortError' || e.message.includes('aborted'))) {
      return { status: 200, json: {} };
    }
    throw e;
  }
}

// ── Validator unit-level tests (400 before DB validation) ────────────────────

describe('POST /api/run — input shape validation', () => {
  it('rejects rows that are plain strings (not {id,label} objects)', async () => {
    const res = await postRun({
      dataset: 'Test Census Dataset',
      rows: ['Sex'],
      cols: [],
      wafer: [],
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toMatch(/rows/i);
  });

  it('rejects rows with missing label', async () => {
    const res = await postRun({
      dataset: 'Test Census Dataset',
      rows: [{ id: 1001 }],
      cols: [],
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toMatch(/rows/i);
  });

  it('rejects rows with non-number id', async () => {
    const res = await postRun({
      dataset: 'Test Census Dataset',
      rows: [{ id: 'not-a-number', label: 'Sex' }],
      cols: [],
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toMatch(/rows/i);
  });

  it('rejects rows with empty label', async () => {
    const res = await postRun({
      dataset: 'Test Census Dataset',
      rows: [{ id: 1001, label: '  ' }],
      cols: [],
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toMatch(/rows/i);
  });

  it('accepts valid {id,label} objects in rows', async () => {
    // Valid shape — DB validation passes too; run is enqueued (SSE starts, Playwright runs)
    // We abort early after headers to avoid hanging on the SSE stream
    const r = await postRunCheckStatus({
      dataset: 'Test Census Dataset',
      rows: [{ id: 1001, label: 'Sex' }],
      cols: [],
      wafer: [],
    });
    // Should NOT be 400 — shape is valid, DB validation passes
    expect(r.status).not.toBe(400);
  });

  it('accepts valid {id,label} objects in cols and wafer', async () => {
    const r = await postRunCheckStatus({
      dataset: 'Test Census Dataset',
      rows: [{ id: 1001, label: 'Sex' }],
      cols: [{ id: 1002, label: 'Age' }],
      wafer: [],
    });
    // Shape is valid — no 400 for shape or DB validation
    expect(r.status).not.toBe(400);
  });

  it('accepts null geography', async () => {
    const r = await postRunCheckStatus({
      dataset: 'Test Census Dataset',
      rows: [{ id: 1001, label: 'Sex' }],
      cols: [],
      geography: null,
    });
    // null geography is valid shape and DB validation passes (no geo check for null)
    expect(r.status).not.toBe(400);
  });

  it('treats missing geography and geography:null identically (no shape error)', async () => {
    const withNull = await postRunCheckStatus({
      dataset: 'Test Census Dataset',
      rows: [{ id: 1001, label: 'Sex' }],
      cols: [],
      geography: null,
    });
    const withMissing = await postRunCheckStatus({
      dataset: 'Test Census Dataset',
      rows: [{ id: 1001, label: 'Sex' }],
      cols: [],
      // geography field absent
    });

    // Both should be non-400 (validation passes for both)
    expect(withNull.status).not.toBe(400);
    expect(withMissing.status).not.toBe(400);
    // They should produce the same status code
    expect(withNull.status).toBe(withMissing.status);
  });

  it('rejects geography with invalid shape (missing label)', async () => {
    const res = await postRun({
      dataset: 'Test Census Dataset',
      rows: [{ id: 1001, label: 'Sex' }],
      cols: [],
      geography: { id: 10 }, // missing label
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string; field?: string };
    expect(body.field).toBe('geography');
  });

  it('rejects geography with non-number id', async () => {
    const res = await postRun({
      dataset: 'Test Census Dataset',
      rows: [{ id: 1001, label: 'Sex' }],
      cols: [],
      geography: { id: 'not-a-number', label: 'Australia' },
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string; field?: string };
    expect(body.field).toBe('geography');
  });
});

// ── DB-backed validation tests ───────────────────────────────────────────────

describe('POST /api/run — DB-backed validation', () => {
  it('returns 400 with field="dataset" when dataset name does not exist in DB', async () => {
    const res = await postRun({
      dataset: 'Completely Unknown Dataset Name',
      rows: [{ id: 1001, label: 'Sex' }],
      cols: [],
      wafer: [],
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string; field: string };
    expect(body.field).toBe('dataset');
    expect(body.error).toMatch(/unknown dataset/i);
  });

  it('returns 400 with field="variables" when a variable id does not belong to the dataset', async () => {
    const res = await postRun({
      dataset: 'Test Census Dataset', // dataset_id=1
      rows: [{ id: 2001, label: 'Other Var' }], // id 2001 belongs to dataset_id=2
      cols: [],
      wafer: [],
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string; field: string };
    expect(body.field).toBe('variables');
    expect(body.error).toMatch(/unknown variable/i);
  });

  it('returns 400 with field="geography" when geography id does not belong to the dataset', async () => {
    const res = await postRun({
      dataset: 'Test Census Dataset', // dataset_id=1
      rows: [{ id: 1001, label: 'Sex' }], // valid variable for dataset 1
      cols: [],
      wafer: [],
      geography: { id: 20, label: 'Victoria' }, // geo id=20 belongs to dataset_id=2
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string; field: string };
    expect(body.field).toBe('geography');
    expect(body.error).toMatch(/unknown geography/i);
  });

  it('accepts valid variable ids and geography id for the dataset', async () => {
    const r = await postRunCheckStatus({
      dataset: 'Test Census Dataset', // dataset_id=1
      rows: [{ id: 1001, label: 'Sex' }], // valid
      cols: [],
      wafer: [],
      geography: { id: 10, label: 'Australia' }, // valid for dataset_id=1
    });
    // Should pass all DB validation — not a 400
    expect(r.status).not.toBe(400);
  });

  it('accepts valid variable ids with no geography', async () => {
    const r = await postRunCheckStatus({
      dataset: 'Test Census Dataset',
      rows: [{ id: 1001, label: 'Sex' }],
      cols: [{ id: 1002, label: 'Age' }],
      wafer: [],
    });
    // Should pass all DB validation — not a 400
    expect(r.status).not.toBe(400);
  });
});
