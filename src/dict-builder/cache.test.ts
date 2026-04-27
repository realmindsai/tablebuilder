// src/dict-builder/cache.test.ts
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { promises as fs } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import {
  ensureCacheDir,
  readSuccess,
  writeSuccess,
  writeError,
  hasError,
  listSuccessCaches,
  readAllSuccessCaches,
  listErrorSlugs,
  clearCache,
  writeSummary,
  CacheCollisionError,
} from './cache.js';
import type { ExtractedDataset, ScrapeError, RunSummary } from './types.js';

let dir: string;

beforeEach(async () => {
  dir = join(tmpdir(), `dict-cache-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  await ensureCacheDir(dir);
});

afterEach(async () => {
  await fs.rm(dir, { recursive: true, force: true });
});

const sampleDataset = (name: string): ExtractedDataset => ({
  dataset_name: name,
  geographies: ['Australia', 'LGA'],
  groups: [
    { label: 'Demographics', path: 'Demographics', variables: [
      { code: 'SEXP', label: 'Sex', category_count: 2, categories: ['Male', 'Female'] },
    ]},
  ],
  scraped_at: '2026-04-27T08:00:00Z',
  tree_node_count: 42,
});

describe('writeSuccess + readSuccess', () => {
  it('round-trips an ExtractedDataset', async () => {
    const ds = sampleDataset('2021 Census - cultural diversity');
    await writeSuccess(dir, ds);
    const read = await readSuccess(dir, '2021_census_cultural_diversity');
    expect(read).toEqual(ds);
  });

  it('returns null when cache file does not exist', async () => {
    expect(await readSuccess(dir, 'nonexistent_slug')).toBeNull();
  });

  it('allows overwrite when same dataset_name (resume retry)', async () => {
    const ds1 = sampleDataset('2021 Census - cultural diversity');
    const ds2 = { ...ds1, tree_node_count: 99 };
    await writeSuccess(dir, ds1);
    await writeSuccess(dir, ds2);
    const read = await readSuccess(dir, '2021_census_cultural_diversity');
    expect(read?.tree_node_count).toBe(99);
  });

  it('throws CacheCollisionError when slug collides with different dataset_name', async () => {
    // Two pretend-different ABS dataset names that both slugify to the same string
    const ds1 = sampleDataset('Foo Bar');
    const ds2 = sampleDataset('FOO!!! BAR');
    await writeSuccess(dir, ds1);
    await expect(writeSuccess(dir, ds2)).rejects.toThrow(CacheCollisionError);
  });

  it('clears stale .error.json on successful write', async () => {
    const errSlug = '2021_census_cultural_diversity';
    await writeError(dir, {
      dataset_name: '2021 Census - cultural diversity',
      error: 'timeout',
      failed_at: '2026-04-27T08:00:00Z',
      attempt: 1,
    });
    expect(await hasError(dir, errSlug)).toBe(true);
    await writeSuccess(dir, sampleDataset('2021 Census - cultural diversity'));
    expect(await hasError(dir, errSlug)).toBe(false);
  });
});

describe('writeError + hasError + listErrorSlugs', () => {
  it('writes, detects, and lists error files', async () => {
    const err: ScrapeError = {
      dataset_name: 'Foo Dataset',
      error: 'navigation timeout',
      failed_at: '2026-04-27T08:00:00Z',
      attempt: 1,
    };
    await writeError(dir, err);
    expect(await hasError(dir, 'foo_dataset')).toBe(true);
    expect(await listErrorSlugs(dir)).toEqual(['foo_dataset']);
  });
});

describe('listSuccessCaches + readAllSuccessCaches', () => {
  it('lists only success caches (excludes .error.json and _summary.json)', async () => {
    await writeSuccess(dir, sampleDataset('Foo'));
    await writeSuccess(dir, sampleDataset('Bar'));
    await writeError(dir, { dataset_name: 'Baz', error: 'x', failed_at: 'y', attempt: 1 });
    await writeSummary(dir, {
      total: 3, succeeded: 2, failed: 1, failed_datasets: ['Baz'],
      started_at: 'a', finished_at: 'b',
    });
    const paths = await listSuccessCaches(dir);
    expect(paths).toHaveLength(2);
    const datasets = await readAllSuccessCaches(dir);
    const names = datasets.map(d => d.dataset_name).sort();
    expect(names).toEqual(['Bar', 'Foo']);
  });

  it('returns empty array when cache dir does not exist', async () => {
    const fresh = join(tmpdir(), `not-here-${Date.now()}`);
    expect(await listSuccessCaches(fresh)).toEqual([]);
  });
});

describe('clearCache', () => {
  it('deletes all cache files and recreates the directory', async () => {
    await writeSuccess(dir, sampleDataset('Foo'));
    await clearCache(dir);
    expect(await listSuccessCaches(dir)).toEqual([]);
  });
});
