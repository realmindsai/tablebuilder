// src/logger.test.ts
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtemp, rm, readdir, readFile, writeFile } from 'fs/promises';
import { tmpdir } from 'os';
import { join } from 'path';
import { logRun, pruneOldLogs } from './logger.js';

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
