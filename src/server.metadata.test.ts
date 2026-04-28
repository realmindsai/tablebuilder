// src/server.metadata.test.ts
import { vi, describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import os from 'node:os';
import Database from 'better-sqlite3';

// ── Fixture helpers ─────────────────────────────────────────────────────────

function buildOldSchemaDb(dbPath: string): void {
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE datasets (
      id INTEGER PRIMARY KEY,
      name TEXT UNIQUE NOT NULL
    );
    INSERT INTO datasets (name) VALUES ('Old Dataset');
  `);
  db.close();
}

function buildNewSchemaDb(dbPath: string): void {
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
    INSERT INTO datasets (id, name) VALUES (1, 'Test Dataset Alpha');

    INSERT INTO geographies (dataset_id, label) VALUES (1, 'Australia');
    INSERT INTO geographies (dataset_id, label) VALUES (1, 'New South Wales');

    INSERT INTO groups (id, dataset_id, label, path) VALUES (1, 1, 'Age Group', 'Age/Age Group');
    INSERT INTO groups (id, dataset_id, label, path) VALUES (2, 1, 'Sex', 'Sex');

    INSERT INTO variables (id, group_id, code, label, category_count) VALUES (1, 1, 'AGE5P', 'Age in 5 year groups', 0);
    INSERT INTO variables (id, group_id, code, label, category_count) VALUES (2, 1, 'AGEP', 'Age single year', 0);
    INSERT INTO variables (id, group_id, code, label, category_count) VALUES (3, 2, 'SEXP', 'Sex', 0);
    INSERT INTO variables (id, group_id, code, label, category_count) VALUES (4, 2, 'SEXR', 'Sex (ratio)', 0);
  `);

  db.close();
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('GET /api/datasets/:id/metadata — 503 when geographies table missing (boot guard)', () => {
  let server: http.Server;
  let baseUrl: string;
  let tmpDir: string;

  beforeAll(async () => {
    tmpDir = mkdtempSync(join(os.tmpdir(), 'tablebuilder-test-'));
    const dbPath = join(tmpDir, 'old-schema.db');
    buildOldSchemaDb(dbPath);

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

  it('returns 503 with out-of-date error message', async () => {
    const res = await fetch(`${baseUrl}/api/datasets/1/metadata`);
    expect(res.status).toBe(503);
    const body = await res.json() as { error: string };
    expect(body.error).toMatch(/out of date|reassembly/i);
  });
});

describe('GET /api/datasets/:id/metadata — 503 when dictDb is null', () => {
  let server: http.Server;
  let baseUrl: string;

  beforeAll(async () => {
    // Point to a non-existent path so DICT_DB resolves to null
    process.env.TABLEBUILDER_TEST_DB_PATH = '/tmp/tablebuilder-test-nonexistent-path/no.db';
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
  });

  it('returns 503 with unavailable error message', async () => {
    const res = await fetch(`${baseUrl}/api/datasets/1/metadata`);
    expect(res.status).toBe(503);
    const body = await res.json() as { error: string };
    expect(body.error).toMatch(/unavailable/i);
  });
});

describe('GET /api/datasets/:id/metadata — 200 with full shape for known dataset', () => {
  let server: http.Server;
  let baseUrl: string;
  let tmpDir: string;

  beforeAll(async () => {
    tmpDir = mkdtempSync(join(os.tmpdir(), 'tablebuilder-test-'));
    const dbPath = join(tmpDir, 'new-schema.db');
    buildNewSchemaDb(dbPath);

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

  it('returns 200 with correct shape', async () => {
    const res = await fetch(`${baseUrl}/api/datasets/1/metadata`);
    expect(res.status).toBe(200);
    const body = await res.json() as {
      id: number;
      name: string;
      geographies: Array<{ id: number; label: string }>;
      groups: Array<{ id: number; label: string; variables: Array<{ id: number; code: string; label: string }> }>;
    };
    expect(typeof body.id).toBe('number');
    expect(body.id).toBe(1);
    expect(typeof body.name).toBe('string');
    expect(body.name).toBe('Test Dataset Alpha');

    expect(Array.isArray(body.geographies)).toBe(true);
    expect(body.geographies).toHaveLength(2);
    expect(body.geographies[0]).toMatchObject({ id: expect.any(Number), label: expect.any(String) });

    expect(Array.isArray(body.groups)).toBe(true);
    expect(body.groups).toHaveLength(2);
    const firstGroup = body.groups[0];
    expect(typeof firstGroup.id).toBe('number');
    expect(typeof firstGroup.label).toBe('string');
    expect(Array.isArray(firstGroup.variables)).toBe(true);
    expect(firstGroup.variables).toHaveLength(2);
    const firstVar = firstGroup.variables[0];
    expect(typeof firstVar.id).toBe('number');
    expect(typeof firstVar.code).toBe('string');
    expect(typeof firstVar.label).toBe('string');
  });
});

describe('GET /api/datasets/:id/metadata — 404 for unknown dataset id', () => {
  let server: http.Server;
  let baseUrl: string;
  let tmpDir: string;

  beforeAll(async () => {
    tmpDir = mkdtempSync(join(os.tmpdir(), 'tablebuilder-test-'));
    const dbPath = join(tmpDir, 'new-schema-404.db');
    buildNewSchemaDb(dbPath);

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

  it('returns 404 with "Unknown dataset"', async () => {
    const res = await fetch(`${baseUrl}/api/datasets/999999/metadata`);
    expect(res.status).toBe(404);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Unknown dataset');
  });
});

describe('GET /api/datasets/:id/metadata — 400 for non-numeric id', () => {
  let server: http.Server;
  let baseUrl: string;
  let tmpDir: string;

  beforeAll(async () => {
    tmpDir = mkdtempSync(join(os.tmpdir(), 'tablebuilder-test-'));
    const dbPath = join(tmpDir, 'new-schema-400.db');
    buildNewSchemaDb(dbPath);

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

  it('returns 400 for non-numeric id', async () => {
    const res = await fetch(`${baseUrl}/api/datasets/abc/metadata`);
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(typeof body.error).toBe('string');
  });
});
