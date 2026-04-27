// src/dict-builder/cache.ts
import { promises as fs } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import { slugify } from './walker.js';
import type { ExtractedDataset, ScrapeError, RunSummary } from './types.js';

export const DEFAULT_CACHE_DIR = join(homedir(), '.tablebuilder', 'dict_cache');

export class CacheCollisionError extends Error {
  constructor(slug: string, existingName: string, newName: string) {
    super(
      `Cache slug collision: '${slug}' already exists for dataset '${existingName}', ` +
      `cannot also write '${newName}'. Pick a disambiguation strategy or rename one of the datasets.`,
    );
    this.name = 'CacheCollisionError';
  }
}

const successPath = (dir: string, slug: string) => join(dir, `${slug}.json`);
const errorPath   = (dir: string, slug: string) => join(dir, `${slug}.error.json`);
const summaryPath = (dir: string)               => join(dir, '_summary.json');

export async function ensureCacheDir(dir = DEFAULT_CACHE_DIR): Promise<void> {
  await fs.mkdir(dir, { recursive: true });
}

export async function readSuccess(dir: string, slug: string): Promise<ExtractedDataset | null> {
  try {
    const text = await fs.readFile(successPath(dir, slug), 'utf8');
    return JSON.parse(text) as ExtractedDataset;
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw e;
  }
}

export async function hasError(dir: string, slug: string): Promise<boolean> {
  try {
    await fs.access(errorPath(dir, slug));
    return true;
  } catch {
    return false;
  }
}

export async function writeSuccess(dir: string, data: ExtractedDataset): Promise<void> {
  const slug = slugify(data.dataset_name);
  const existing = await readSuccess(dir, slug);
  if (existing && existing.dataset_name !== data.dataset_name) {
    throw new CacheCollisionError(slug, existing.dataset_name, data.dataset_name);
  }
  await fs.writeFile(successPath(dir, slug), JSON.stringify(data, null, 2));
  // Successful scrape clears any prior error record for the same slug
  try { await fs.unlink(errorPath(dir, slug)); } catch { /* none */ }
}

export async function writeError(dir: string, err: ScrapeError): Promise<void> {
  const slug = slugify(err.dataset_name);
  await fs.writeFile(errorPath(dir, slug), JSON.stringify(err, null, 2));
}

export async function listSuccessCaches(dir: string): Promise<string[]> {
  try {
    const files = await fs.readdir(dir);
    return files
      .filter(f => f.endsWith('.json') && !f.endsWith('.error.json') && f !== '_summary.json')
      .map(f => join(dir, f));
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw e;
  }
}

export async function readAllSuccessCaches(dir: string): Promise<ExtractedDataset[]> {
  const paths = await listSuccessCaches(dir);
  const datasets: ExtractedDataset[] = [];
  for (const p of paths) {
    const text = await fs.readFile(p, 'utf8');
    datasets.push(JSON.parse(text) as ExtractedDataset);
  }
  return datasets;
}

export async function listErrorSlugs(dir: string): Promise<string[]> {
  try {
    const files = await fs.readdir(dir);
    return files.filter(f => f.endsWith('.error.json')).map(f => f.replace(/\.error\.json$/, ''));
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw e;
  }
}

export async function clearCache(dir: string): Promise<void> {
  try { await fs.rm(dir, { recursive: true, force: true }); } catch { /* ok */ }
  await ensureCacheDir(dir);
}

export async function writeSummary(dir: string, summary: RunSummary): Promise<void> {
  await fs.writeFile(summaryPath(dir), JSON.stringify(summary, null, 2));
}
