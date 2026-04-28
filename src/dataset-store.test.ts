// src/dataset-store.test.ts
// @vitest-environment jsdom
//
// Tests for ui/dataset-store.js — window.DatasetStore.loadMetadata(id)
// The module sets window.DatasetStore directly (no ESM exports), so we
// evaluate the file into the jsdom window each test run.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const storeSource = readFileSync(
  join(__dirname, '..', 'ui', 'dataset-store.js'),
  'utf8',
);

// Re-evaluate the module source before each test so the cache is fresh.
// Each call to loadDatasetStoreModule() installs a new window.DatasetStore.
function loadDatasetStoreModule() {
  // eslint-disable-next-line no-eval
  eval(storeSource);
}

declare global {
  interface Window {
    DatasetStore: { loadMetadata: (id: number | string) => Promise<unknown> };
  }
}

beforeEach(() => {
  vi.resetAllMocks();
  loadDatasetStoreModule();
});

describe('DatasetStore.loadMetadata', () => {
  it('fetches once per id and caches the promise', async () => {
    const data = { id: 1, variables: [] };
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => data,
    });
    vi.stubGlobal('fetch', mockFetch);

    const p1 = window.DatasetStore.loadMetadata(1);
    const p2 = window.DatasetStore.loadMetadata(1);

    expect(p1).toBe(p2); // same promise reference — cached

    const [r1, r2] = await Promise.all([p1, p2]);
    expect(r1).toEqual(data);
    expect(r2).toEqual(data);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('rejects on non-OK response and clears cache so retry re-fetches', async () => {
    const mockFetch = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 404, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true,  json: async () => ({ id: 2 }) });
    vi.stubGlobal('fetch', mockFetch);

    // First call — should reject
    await expect(window.DatasetStore.loadMetadata(2)).rejects.toThrow(
      'metadata fetch failed: 404',
    );

    // Second call — cache was cleared, should fetch again and succeed
    const result = await window.DatasetStore.loadMetadata(2);
    expect(result).toEqual({ id: 2 });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('rejects on network error and clears cache so retry re-fetches', async () => {
    const networkError = new TypeError('Failed to fetch');
    const mockFetch = vi.fn()
      .mockRejectedValueOnce(networkError)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 3 }) });
    vi.stubGlobal('fetch', mockFetch);

    // First call — network error
    await expect(window.DatasetStore.loadMetadata(3)).rejects.toThrow(
      'Failed to fetch',
    );

    // Second call — cache was cleared, fetch fires again and succeeds
    const result = await window.DatasetStore.loadMetadata(3);
    expect(result).toEqual({ id: 3 });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });
});
