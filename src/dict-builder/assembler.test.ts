// src/dict-builder/assembler.test.ts
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { promises as fs } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import Database from 'better-sqlite3';
import { writeSuccess, ensureCacheDir } from './cache.js';
import { build } from './assembler.js';
import type { ExtractedDataset } from './types.js';

let cacheDir: string;
let dbPath: string;

beforeEach(async () => {
  const stamp = Date.now() + '-' + Math.random().toString(36).slice(2);
  cacheDir = join(tmpdir(), `dict-asm-cache-${stamp}`);
  dbPath = join(tmpdir(), `dict-asm-db-${stamp}.db`);
  await ensureCacheDir(cacheDir);
});

afterEach(async () => {
  await fs.rm(cacheDir, { recursive: true, force: true });
  await fs.rm(dbPath, { force: true });
  await fs.rm(`${dbPath}.tmp`, { force: true });
});

const ds = (overrides: Partial<ExtractedDataset> = {}): ExtractedDataset => ({
  dataset_name: 'Test Dataset',
  geographies: ['Australia'],
  groups: [
    { label: 'Demographics', path: 'Demographics', variables: [
      { code: 'SEXP', label: 'Sex', category_count: 2, categories: ['Male', 'Female'] },
    ]},
  ],
  scraped_at: '2026-04-27T08:00:00Z',
  tree_node_count: 5,
  ...overrides,
});

describe('assembler.build', () => {
  it('writes a fresh dictionary.db with all rows from cache files', async () => {
    await writeSuccess(cacheDir, ds({ dataset_name: 'Alpha' }));
    await writeSuccess(cacheDir, ds({ dataset_name: 'Beta' }));
    await build(cacheDir, dbPath);

    const db = new Database(dbPath, { readonly: true });
    expect(db.prepare('SELECT COUNT(*) AS c FROM datasets').get()).toEqual({ c: 2 });
    expect(db.prepare('SELECT COUNT(*) AS c FROM groups').get()).toEqual({ c: 2 });
    expect(db.prepare('SELECT COUNT(*) AS c FROM variables').get()).toEqual({ c: 2 });
    expect(db.prepare('SELECT COUNT(*) AS c FROM categories').get()).toEqual({ c: 4 });
    db.close();
  });

  it('populates category_count column', async () => {
    await writeSuccess(cacheDir, ds({
      dataset_name: 'Big',
      groups: [{ label: 'Geo', path: 'Geo', variables: [
        { code: 'SA1MAIN_2021', label: 'SA1', category_count: 61845, categories: [] },
      ]}],
    }));
    await build(cacheDir, dbPath);
    const db = new Database(dbPath, { readonly: true });
    const row = db.prepare('SELECT category_count FROM variables WHERE code = ?').get('SA1MAIN_2021') as { category_count: number };
    expect(row.category_count).toBe(61845);
    db.close();
  });

  it('writes geographies as rows in geographies table', async () => {
    await writeSuccess(cacheDir, ds({
      dataset_name: 'WithGeos',
      geographies: ['Australia', 'LGA (2021 Boundaries)', 'SA1 by Main ASGS'],
    }));
    await build(cacheDir, dbPath);
    const db = new Database(dbPath, { readonly: true });
    const rows = db.prepare(
      'SELECT label FROM geographies WHERE dataset_id = (SELECT id FROM datasets WHERE name = ?)'
    ).all('WithGeos') as { label: string }[];
    expect(rows.map(r => r.label)).toEqual(['Australia', 'LGA (2021 Boundaries)', 'SA1 by Main ASGS']);
    db.close();
  });

  it('does not have geographies_json column', async () => {
    await writeSuccess(cacheDir, ds({ dataset_name: 'ColCheck' }));
    await build(cacheDir, dbPath);
    const db = new Database(dbPath, { readonly: true });
    const cols = db.prepare('PRAGMA table_info(datasets)').all() as { name: string }[];
    expect(cols.map(c => c.name)).not.toContain('geographies_json');
    db.close();
  });

  it('builds queryable FTS5 indexes', async () => {
    await writeSuccess(cacheDir, ds({ dataset_name: 'Cultural Diversity' }));
    await build(cacheDir, dbPath);
    const db = new Database(dbPath, { readonly: true });
    const hits = db.prepare("SELECT name FROM datasets_fts WHERE datasets_fts MATCH 'cultural'").all();
    expect(hits.length).toBe(1);
    db.close();
  });

  it('atomic-renames .tmp to final path (final file exists, .tmp removed)', async () => {
    await writeSuccess(cacheDir, ds({ dataset_name: 'X' }));
    await build(cacheDir, dbPath);
    expect(await fs.stat(dbPath)).toBeDefined();
    await expect(fs.stat(`${dbPath}.tmp`)).rejects.toThrow();
  });

  it('overwrites an existing target DB', async () => {
    await fs.writeFile(dbPath, 'stale junk');
    await writeSuccess(cacheDir, ds({ dataset_name: 'Fresh' }));
    await build(cacheDir, dbPath);
    const db = new Database(dbPath, { readonly: true });
    const row = db.prepare('SELECT name FROM datasets').get() as { name: string };
    expect(row.name).toBe('Fresh');
    db.close();
  });

  it('produces deterministic byte-identical output for the same cache', async () => {
    await writeSuccess(cacheDir, ds({ dataset_name: 'Beta' }));
    await writeSuccess(cacheDir, ds({ dataset_name: 'Alpha' }));
    await build(cacheDir, dbPath);
    const first = await fs.readFile(dbPath);
    await build(cacheDir, dbPath);
    const second = await fs.readFile(dbPath);
    expect(Buffer.compare(first, second)).toBe(0);
  });
});
