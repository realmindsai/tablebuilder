process.env.COOKIE_SECRET = 'a'.repeat(64);

// src/server.test.ts
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { createServer } from './server.js';
import { encryptCreds } from './auth.js';
import type { Server } from 'http';

let server: Server;
let baseUrl: string;
let validCookie: string;

beforeAll(async () => {
  validCookie = encryptCreds({ userId: 'test@example.com', password: 'test' }, 'a'.repeat(64));
  const app = await createServer();
  await new Promise<void>(resolve => {
    server = app.listen(0, () => resolve());
  });
  const addr = server.address() as { port: number };
  baseUrl = `http://localhost:${addr.port}`;
});

afterAll(async () => {
  await new Promise<void>(resolve => server.close(() => resolve()));
});

describe('GET /api/health', () => {
  it('returns 200 with ok: true', async () => {
    const res = await fetch(`${baseUrl}/api/health`);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ ok: true });
  });
});

describe('POST /api/run validation', () => {
  it('returns 400 when dataset is missing', async () => {
    const res = await fetch(`${baseUrl}/api/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Cookie': `abs_creds=${validCookie}` },
      body: JSON.stringify({ rows: ['Sex'], cols: [], wafer: [], output: '' }),
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toMatch(/dataset/i);
  });

  it('returns 400 when rows is empty', async () => {
    const res = await fetch(`${baseUrl}/api/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Cookie': `abs_creds=${validCookie}` },
      body: JSON.stringify({ dataset: 'Census 2021', rows: [], cols: [], wafer: [], output: '' }),
    });
    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toMatch(/rows/i);
  });

  it('returns 400 when dataset is empty string', async () => {
    const res = await fetch(`${baseUrl}/api/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Cookie': `abs_creds=${validCookie}` },
      body: JSON.stringify({ dataset: '', rows: ['Sex'], cols: [], wafer: [], output: '' }),
    });
    expect(res.status).toBe(400);
  });

});
