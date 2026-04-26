// src/server.datasets.integration.test.ts
// Uses the real dictionary.db — no mocks. Run with: npm test
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { createServer } from './server.js';

describe('GET /api/datasets — real dictionary.db', () => {
  let server: http.Server;
  let baseUrl: string;

  beforeAll(async () => {
    const app = await createServer();
    server = http.createServer(app as any);
    await new Promise<void>(resolve => server.listen(0, resolve));
    baseUrl = `http://localhost:${(server.address() as AddressInfo).port}`;
  });

  afterAll(() => server.close());

  it('returns at least 100 dataset names', async () => {
    const res = await fetch(`${baseUrl}/api/datasets`);
    if (res.status === 503) {
      console.warn('dictionary.db not found — skipping integration test');
      return;
    }
    expect(res.status).toBe(200);
    const body = await res.json() as unknown[];
    expect(body.length).toBeGreaterThanOrEqual(100);
  });

  it('includes the canonical 2021 persons usual residence dataset', async () => {
    const res = await fetch(`${baseUrl}/api/datasets`);
    if (res.status === 503) return;
    const body = await res.json() as Array<{ name: string }>;
    expect(body.map(d => d.name)).toContain(
      '2021 Census - counting persons, place of usual residence'
    );
  });
});
