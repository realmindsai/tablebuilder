// src/server.test.ts
import { vi, describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { existsSync } from 'fs'; // gets the mocked version (vi.mock is hoisted)

// Mock better-sqlite3 so no real DB is opened.
// vi.mock is hoisted — runs before any imports below.
vi.mock('better-sqlite3', () => {
  const MOCK_ROWS = [
    { id: 1, name: 'Alpha Dataset' },
    { id: 2, name: 'Beta Dataset' },
  ];
  const MockDb = vi.fn().mockImplementation(function () {
    return {
      prepare: vi.fn().mockReturnValue({ all: vi.fn().mockReturnValue(MOCK_ROWS) }),
    };
  });
  return { default: MockDb };
});

// Mock existsSync to return true so DICT_DB and UI_DIR both resolve.
vi.mock('fs', async (importOriginal) => {
  const mod = await importOriginal<typeof import('fs')>();
  return {
    ...mod,
    existsSync: vi.fn().mockReturnValue(true),
    realpathSync: vi.fn().mockReturnValue('/fake/server/path'),
  };
});

describe('GET /api/datasets — mocked DB', () => {
  let server: http.Server;
  let baseUrl: string;

  beforeAll(async () => {
    const { createServer } = await import('./server.js');
    const app = await createServer();
    server = http.createServer(app as any);
    await new Promise<void>(resolve => server.listen(0, resolve));
    baseUrl = `http://localhost:${(server.address() as AddressInfo).port}`;
  });

  afterAll(() => server.close());

  it('returns 200 with an array', async () => {
    const res = await fetch(`${baseUrl}/api/datasets`);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBe(true);
  });

  it('each entry has id, name, code:null, tag:null, year:null', async () => {
    const res = await fetch(`${baseUrl}/api/datasets`);
    const body = await res.json() as Record<string, unknown>[];
    expect(body.length).toBeGreaterThan(0);
    const first = body[0];
    expect(typeof first.id).toBe('number');
    expect(typeof first.name).toBe('string');
    expect(first.code).toBeNull();
    expect(first.tag).toBeNull();
    expect(first.year).toBeNull();
  });
});

// 503 case: existsSync returns false for dictionary.db path → dictDb is null
describe('GET /api/datasets — DB unavailable', () => {
  let server: http.Server;
  let baseUrl: string;

  beforeAll(async () => {
    // Change mock return value BEFORE resetModules so the fresh server.ts load
    // sees existsSync() → false and sets DICT_DB = null.
    vi.mocked(existsSync).mockReturnValue(false);
    vi.resetModules(); // Force server.ts to re-evaluate module-level DICT_DB
    const { createServer } = await import('./server.js');
    const app = await createServer();
    server = http.createServer(app as any);
    await new Promise<void>(resolve => server.listen(0, resolve));
    baseUrl = `http://localhost:${(server.address() as AddressInfo).port}`;
  });

  afterAll(() => server.close());

  it('returns 503 when dictionary.db is not found', async () => {
    const res = await fetch(`${baseUrl}/api/datasets`);
    expect(res.status).toBe(503);
    const body = await res.json() as { error: string };
    expect(typeof body.error).toBe('string');
  });
});
