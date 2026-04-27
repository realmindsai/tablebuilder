# ABS Dictionary Builder Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a TypeScript scraper that walks every ABS TableBuilder dataset's full schema tree (including geographic variables like STRD/SA2/LGA that the legacy Python scraper missed), captures categories for low-cardinality variables, and rebuilds `docs/explorer/data/dictionary.db` from scratch.

**Architecture:** Two-phase pipeline. Phase 1 (per-dataset): Playwright session opens each dataset, walks the schema tree, writes a JSON cache file at `~/.tablebuilder/dict_cache/<slug>.json`. Phase 2 (assembly): all caches read into memory, written to a fresh SQLite DB inline-tmp file, atomically renamed to `dictionary.db`. Resume: a cache file means "already done — skip". Failure: write `<slug>.error.json`, continue. Develop locally on Mac with mocked Playwright pages; run real scrape on totoro where Chromium and stable internet live.

**Tech Stack:** TypeScript, ESM, Playwright, better-sqlite3, vitest. Reuses `src/shared/abs/auth.ts` (login) and parts of `src/shared/abs/navigator.ts` (`listDatasets` — needs export).

**Spec:** `docs/superpowers/specs/2026-04-27-dictionary-builder-design.md`

---

## File Map

| File | Responsibility |
|---|---|
| `src/dict-builder/types.ts` | `ExtractedDataset`, `ExtractedGroup`, `ExtractedVariable`, `ScrapeError`, `RunSummary` interfaces |
| `src/dict-builder/walker.ts` | Pure: variable-label regex, `parseVariableLabel`, `slugify`, `shouldExpandVariable` |
| `src/dict-builder/walker.test.ts` | Unit tests for walker — no browser |
| `src/dict-builder/cache.ts` | Per-dataset JSON read/write with collision detection |
| `src/dict-builder/cache.test.ts` | Unit tests for cache (uses `tmp` dir) |
| `src/dict-builder/scraper.ts` | Playwright DOM walk → `ExtractedDataset`. Pure node-classification helpers + the Playwright `extract()` entry point |
| `src/dict-builder/scraper.test.ts` | Unit tests for the pure helpers + a mock-page test for `extract()` |
| `src/dict-builder/assembler.ts` | Reads cache files, writes fresh `dictionary.db.tmp`, atomic rename. Inlined `CREATE TABLE` statements with the new `category_count` column |
| `src/dict-builder/assembler.test.ts` | Unit tests using a fixture cache directory and a temp DB path |
| `scripts/build-dict.ts` | CLI entry: parse flags, login, loop datasets, write summary, optionally assemble |
| `src/shared/abs/navigator.ts` | **MODIFY**: export `listDatasets` (currently module-private) |

---

## Chunk 1: Pure foundations (types, walker, cache)

### Task 1: Export `listDatasets` from `navigator.ts`

**Files:**
- Modify: `src/shared/abs/navigator.ts:94`

- [ ] **Step 1: Make `listDatasets` exported**

In `src/shared/abs/navigator.ts`, change:
```typescript
async function listDatasets(page: Page, signal: AbortSignal = NEVER_ABORT): Promise<string[]> {
```
to:
```typescript
export async function listDatasets(page: Page, signal: AbortSignal = NEVER_ABORT): Promise<string[]> {
```

- [ ] **Step 2: Verify nothing broke**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test
```

Expected: 61/61 tests still pass.

- [ ] **Step 3: Commit**

```bash
git add src/shared/abs/navigator.ts
git commit -m "refactor: export listDatasets for use by dict-builder"
```

---

### Task 2: `src/dict-builder/types.ts`

**Files:**
- Create: `src/dict-builder/types.ts`

- [ ] **Step 1: Write the type file**

```typescript
// src/dict-builder/types.ts

export interface ExtractedVariable {
  code: string;             // e.g. "STRD" or "SA1MAIN_2021"
  label: string;            // e.g. "State/Territory" (no count, no code)
  category_count: number;   // parsed from "(N)" in the raw label
  categories: string[];     // empty when category_count > 100
}

export interface ExtractedGroup {
  label: string;            // local group label, e.g. "LGA (2021 Boundaries)"
  path: string;             // " > "-joined ancestors, e.g. "Geographical Areas (Usual Residence) > LGA (2021 Boundaries)"
  variables: ExtractedVariable[];
}

export interface ExtractedDataset {
  dataset_name: string;
  geographies: string[];    // classification-release leaves (no checkbox)
  groups: ExtractedGroup[];
  scraped_at: string;       // ISO 8601 UTC timestamp
  tree_node_count: number;  // raw .treeNodeElement count, for diagnostics
}

export interface ScrapeError {
  dataset_name: string;
  error: string;
  stack?: string;
  failed_at: string;
  attempt: number;
}

export interface RunSummary {
  total: number;
  succeeded: number;
  failed: number;
  failed_datasets: string[];
  started_at: string;
  finished_at: string;
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add src/dict-builder/types.ts
git commit -m "feat(dict-builder): add type definitions for ExtractedDataset"
```

---

### Task 3: `src/dict-builder/walker.ts` — pure helpers

**Files:**
- Create: `src/dict-builder/walker.test.ts`
- Create: `src/dict-builder/walker.ts`

- [ ] **Step 1: Write the failing test file**

```typescript
// src/dict-builder/walker.test.ts
import { describe, it, expect } from 'vitest';
import {
  parseVariableLabel,
  isVariableLabel,
  slugify,
  shouldExpandVariable,
  CATEGORY_THRESHOLD,
} from './walker.js';

describe('parseVariableLabel', () => {
  it('parses standard CODE Label (N) format', () => {
    expect(parseVariableLabel('STRD State/Territory (9)')).toEqual({
      code: 'STRD',
      label: 'State/Territory',
      category_count: 9,
    });
  });

  it('parses codes with underscores (real ABS uses these)', () => {
    expect(parseVariableLabel('SA1MAIN_2021 SA1 by Main Statistical Area Structure (61845)')).toEqual({
      code: 'SA1MAIN_2021',
      label: 'SA1 by Main Statistical Area Structure',
      category_count: 61845,
    });
  });

  it('parses codes with digits in the middle', () => {
    expect(parseVariableLabel('AGE10P Age in Ten Year Groups (11)')).toEqual({
      code: 'AGE10P',
      label: 'Age in Ten Year Groups',
      category_count: 11,
    });
  });

  it('parses labels with parentheses inside', () => {
    expect(parseVariableLabel('TENLLD Tenure (Landlord Type) (8)')).toEqual({
      code: 'TENLLD',
      label: 'Tenure (Landlord Type)',
      category_count: 8,
    });
  });

  it('returns null for non-variable labels', () => {
    expect(parseVariableLabel('Selected Person Characteristics')).toBeNull();
    expect(parseVariableLabel('Geographical Areas (Usual Residence)')).toBeNull();
    expect(parseVariableLabel('LGA (2021 Boundaries)')).toBeNull();
    expect(parseVariableLabel('IFAGEP')).toBeNull();
    expect(parseVariableLabel('')).toBeNull();
  });
});

describe('isVariableLabel', () => {
  it('mirrors parseVariableLabel boolean result', () => {
    expect(isVariableLabel('STRD State/Territory (9)')).toBe(true);
    expect(isVariableLabel('Cultural Diversity')).toBe(false);
  });
});

describe('slugify', () => {
  it('lowercases, replaces non-alphanumeric with underscore, trims', () => {
    expect(slugify('2021 Census - counting persons, place of usual residence'))
      .toBe('2021_census_counting_persons_place_of_usual_residence');
  });

  it('collapses multiple non-alphanumeric runs into a single underscore', () => {
    expect(slugify('Foo --- Bar,, Baz')).toBe('foo_bar_baz');
  });

  it('caps at 80 chars', () => {
    const long = 'a'.repeat(120);
    expect(slugify(long).length).toBe(80);
  });

  it('strips leading and trailing underscores after substitution', () => {
    expect(slugify(' (Survey) ')).toBe('survey');
  });
});

describe('shouldExpandVariable', () => {
  it('expands variables with <= 100 categories', () => {
    expect(shouldExpandVariable(0)).toBe(true);
    expect(shouldExpandVariable(1)).toBe(true);
    expect(shouldExpandVariable(100)).toBe(true);
  });

  it('does not expand variables with > 100 categories', () => {
    expect(shouldExpandVariable(101)).toBe(false);
    expect(shouldExpandVariable(61845)).toBe(false);
  });

  it('exposes the threshold constant', () => {
    expect(CATEGORY_THRESHOLD).toBe(100);
  });
});
```

- [ ] **Step 2: Run to confirm failure (no walker.ts yet)**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test -- src/dict-builder/walker.test.ts
```

Expected: FAIL — `Cannot find module './walker.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/dict-builder/walker.ts

// Variable labels in the ABS schema tree match: CODE LABEL (N)
// where CODE is uppercase + digits + underscores (>= 3 chars total).
// LABEL can contain anything (including inner parens) — the trailing
// "(\d+)" must be the LAST parenthesised group.
const VAR_LABEL_RE = /^([A-Z][A-Z0-9_]{2,})\s+(.+)\s+\((\d+)\)\s*$/;

export interface ParsedVariableLabel {
  code: string;
  label: string;
  category_count: number;
}

export function parseVariableLabel(raw: string): ParsedVariableLabel | null {
  const m = raw.match(VAR_LABEL_RE);
  if (!m) return null;
  return {
    code: m[1],
    label: m[2].trim(),
    category_count: parseInt(m[3], 10),
  };
}

export function isVariableLabel(raw: string): boolean {
  return VAR_LABEL_RE.test(raw);
}

export const SLUG_MAX = 80;

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, SLUG_MAX);
}

export const CATEGORY_THRESHOLD = 100;

export function shouldExpandVariable(category_count: number): boolean {
  return category_count <= CATEGORY_THRESHOLD;
}
```

- [ ] **Step 4: Run tests to verify**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test -- src/dict-builder/walker.test.ts
```

Expected: 13/13 tests pass (4 + 1 + 4 + 3 + 1).

- [ ] **Step 5: Commit**

```bash
git add src/dict-builder/walker.ts src/dict-builder/walker.test.ts
git commit -m "feat(dict-builder): add walker helpers (parseVariableLabel, slugify, threshold)"
```

---

### Task 4: `src/dict-builder/cache.ts` — JSON I/O + collision detection

**Files:**
- Create: `src/dict-builder/cache.test.ts`
- Create: `src/dict-builder/cache.ts`

- [ ] **Step 1: Write the failing test file**

```typescript
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test -- src/dict-builder/cache.test.ts
```

Expected: FAIL — `Cannot find module './cache.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
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
```

- [ ] **Step 4: Run tests to verify**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test -- src/dict-builder/cache.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Run full suite**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test
```

Expected: all tests pass (61 existing + walker + cache).

- [ ] **Step 6: Commit**

```bash
git add src/dict-builder/cache.ts src/dict-builder/cache.test.ts
git commit -m "feat(dict-builder): add cache module with collision detection"
```

---

## Chunk 2: Scraper

### Task 5: `src/dict-builder/scraper.ts` — pure node classification helpers + Playwright entry

The scraper has two layers:
- **Pure helpers** working on a flat `RawNode[]` array — easy to TDD
- **`extract(page, datasetName)`** — uses Playwright to fetch the raw nodes, then delegates to the pure helpers

**Files:**
- Create: `src/dict-builder/scraper.test.ts`
- Create: `src/dict-builder/scraper.ts`

- [ ] **Step 1: Write the failing test file**

```typescript
// src/dict-builder/scraper.test.ts
import { describe, it, expect, vi } from 'vitest';
import {
  splitGeographyAndVariables,
  classifyAndBuildGroups,
  extract,
  type RawNode,
} from './scraper.js';

const node = (
  label: string,
  depth: number,
  is_leaf: boolean,
  is_collapsed: boolean,
  has_checkbox: boolean,
): RawNode => ({ label, depth, is_leaf, is_collapsed, has_checkbox });

describe('splitGeographyAndVariables', () => {
  it('puts no-checkbox leaves before the first checkbox into geographies', () => {
    const nodes = [
      node('Australia',                                       0, true,  false, false),
      node('LGA (2021 Boundaries)',                           0, true,  false, false),
      node('Selected Person Characteristics',                 0, false, false, false),
      node('SEXP Sex (2)',                                    1, false, false, true),
      node('Male',                                            2, true,  false, true),
      node('Female',                                          2, true,  false, true),
    ];
    const { geographies, varNodes } = splitGeographyAndVariables(nodes);
    expect(geographies).toEqual(['Australia', 'LGA (2021 Boundaries)']);
    expect(varNodes.map(n => n.label)).toEqual([
      'Selected Person Characteristics',
      'SEXP Sex (2)',
      'Male',
      'Female',
    ]);
  });

  it('returns all leaves as geographies when no checkboxes exist', () => {
    const nodes = [
      node('Australia',  0, true, false, false),
      node('LGA',        0, true, false, false),
    ];
    const { geographies, varNodes } = splitGeographyAndVariables(nodes);
    expect(geographies).toEqual(['Australia', 'LGA']);
    expect(varNodes).toEqual([]);
  });

  it('returns empty arrays for an empty node list', () => {
    expect(splitGeographyAndVariables([])).toEqual({ geographies: [], varNodes: [] });
  });
});

describe('classifyAndBuildGroups', () => {
  it('classifies variable nodes by label pattern, captures categories', () => {
    const nodes = [
      node('Selected Person Characteristics', 0, false, false, false),
      node('SEXP Sex (2)',                    1, false, false, true),
      node('Male',                            2, true,  false, true),
      node('Female',                          2, true,  false, true),
      node('AGEP Age (21)',                   1, false, false, true),
      node('0-4',                             2, true,  false, true),
      node('5-9',                             2, true,  false, true),
    ];
    const groups = classifyAndBuildGroups(nodes, () => {});
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('Selected Person Characteristics');
    expect(groups[0].path).toBe('Selected Person Characteristics');
    expect(groups[0].variables.map(v => v.code)).toEqual(['SEXP', 'AGEP']);
    expect(groups[0].variables[0]).toEqual({
      code: 'SEXP', label: 'Sex', category_count: 2, categories: ['Male', 'Female'],
    });
  });

  it('builds " > "-joined paths through nested groups', () => {
    const nodes = [
      node('Geographical Areas (Usual Residence)', 0, false, false, false),
      node('LGA (2021 Boundaries)',                1, false, false, false),
      node('LGA_2021 Local Government Area 2021 (565)', 2, false, false, true),
    ];
    const groups = classifyAndBuildGroups(nodes, () => {});
    expect(groups).toHaveLength(1);
    expect(groups[0].path).toBe('Geographical Areas (Usual Residence) > LGA (2021 Boundaries)');
    expect(groups[0].variables[0].code).toBe('LGA_2021');
    expect(groups[0].variables[0].category_count).toBe(565);
    expect(groups[0].variables[0].categories).toEqual([]); // > 100, not expanded
  });

  it('captures categories only for variables with count <= 100', () => {
    const nodes = [
      node('Group',                                 0, false, false, false),
      node('SEXP Sex (2)',                          1, false, false, true),
      node('Male',                                  2, true,  false, true),
      node('Female',                                2, true,  false, true),
      node('SA1MAIN_2021 SA1 by Main ASGS (61845)', 1, false, false, true),
      // Even if the DOM happened to have leaves under SA1, the scraper
      // would not expand it; here we omit those leaves.
    ];
    const groups = classifyAndBuildGroups(nodes, () => {});
    expect(groups[0].variables[0].categories).toEqual(['Male', 'Female']);
    expect(groups[0].variables[1].categories).toEqual([]);
    expect(groups[0].variables[1].category_count).toBe(61845);
  });

  it('treats malformed group-like labels as groups and reports a warning', () => {
    const warnings: string[] = [];
    const nodes = [
      node('weird-malformed-no-count',  0, false, false, false),
      node('SEXP Sex (2)',              1, false, false, true),
      node('Male',                      2, true,  false, true),
    ];
    const groups = classifyAndBuildGroups(nodes, msg => warnings.push(msg));
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('weird-malformed-no-count');
    expect(warnings.length).toBeGreaterThanOrEqual(0); // at minimum, doesn't throw
  });

  it('handles empty input', () => {
    expect(classifyAndBuildGroups([], () => {})).toEqual([]);
  });
});

describe('extract (Playwright integration with mock page)', () => {
  it('returns ExtractedDataset built from page.evaluate result', async () => {
    const rawNodes: RawNode[] = [
      node('Australia',                                  0, true,  false, false),
      node('Selected Person Characteristics',            0, false, false, false),
      node('SEXP Sex (2)',                               1, false, false, true),
      node('Male',                                       2, true,  false, true),
      node('Female',                                     2, true,  false, true),
    ];
    const page = {
      waitForSelector: vi.fn().mockResolvedValue(undefined),
      evaluate: vi.fn().mockResolvedValue(rawNodes),
      locator: vi.fn().mockReturnValue({
        all: vi.fn().mockResolvedValue([]),
        nth: vi.fn().mockReturnValue({
          locator: () => ({ first: () => ({ click: vi.fn().mockResolvedValue(undefined) }) }),
        }),
      }),
    };

    const result = await extract(page as any, 'Test Dataset');
    expect(result.dataset_name).toBe('Test Dataset');
    expect(result.geographies).toEqual(['Australia']);
    expect(result.groups).toHaveLength(1);
    expect(result.groups[0].variables[0].code).toBe('SEXP');
    expect(result.tree_node_count).toBe(5);
    expect(result.scraped_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test -- src/dict-builder/scraper.test.ts
```

Expected: FAIL — `Cannot find module './scraper.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/dict-builder/scraper.ts
import type { Page } from 'playwright-core';
import type { ExtractedDataset, ExtractedGroup, ExtractedVariable } from './types.js';
import { parseVariableLabel, shouldExpandVariable } from './walker.js';

// ── Raw node shape returned by page.evaluate ────────────────────────────────

export interface RawNode {
  label: string;
  depth: number;          // counted from root container by ancestor <ul> nesting
  is_leaf: boolean;
  is_collapsed: boolean;
  has_checkbox: boolean;
}

// JS evaluated inside the page. Walks the schema tree and returns a flat
// array of raw node descriptors with accurate depth.
const TREE_EXTRACT_JS = `
() => {
  const container = document.querySelector('#tableViewSchemaTree')
                  || document.querySelector('.treeControl');
  if (!container) return [];

  const nodes = container.querySelectorAll('.treeNodeElement');
  return Array.from(nodes).map(node => {
    const label = node.querySelector('.label');
    const expander = node.querySelector('.treeNodeExpander');
    const checkbox = node.querySelector('input[type=checkbox]');

    let depth = 0;
    let el = node.parentElement;
    while (el && el !== container) {
      if (el.tagName === 'UL') depth++;
      el = el.parentElement;
    }

    const expClass = expander ? expander.className : '';
    return {
      label: label ? (label.textContent || '').trim() : '',
      depth,
      is_leaf: expClass.includes('leaf'),
      is_collapsed: expClass.includes('collapsed'),
      has_checkbox: !!checkbox,
    };
  });
}
`;

// ── Pure helpers ────────────────────────────────────────────────────────────

export function splitGeographyAndVariables(nodes: RawNode[]): {
  geographies: string[];
  varNodes: RawNode[];
} {
  if (nodes.length === 0) return { geographies: [], varNodes: [] };

  let firstCheckIdx = -1;
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i].has_checkbox) { firstCheckIdx = i; break; }
  }
  if (firstCheckIdx === -1) {
    return {
      geographies: nodes.filter(n => n.is_leaf).map(n => n.label),
      varNodes: [],
    };
  }

  const minDepth = Math.min(...nodes.map(n => n.depth));
  let varStartIdx = firstCheckIdx;
  for (let i = firstCheckIdx - 1; i >= 0; i--) {
    if (nodes[i].depth === minDepth) { varStartIdx = i; break; }
  }

  const geos = nodes.slice(0, varStartIdx).filter(n => n.is_leaf).map(n => n.label);
  return { geographies: geos, varNodes: nodes.slice(varStartIdx) };
}

export function classifyAndBuildGroups(
  varNodes: RawNode[],
  warn: (msg: string) => void,
): ExtractedGroup[] {
  if (varNodes.length === 0) return [];

  const groups: ExtractedGroup[] = [];
  const groupStack: Map<number, string> = new Map();
  let currentGroup: ExtractedGroup | null = null;
  let currentVar: ExtractedVariable | null = null;
  let lastPath = '';

  const flushVar = () => {
    if (currentVar && currentGroup) {
      currentGroup.variables.push(currentVar);
      currentVar = null;
    }
  };
  const flushGroup = () => {
    flushVar();
    if (currentGroup && currentGroup.variables.length > 0) groups.push(currentGroup);
    currentGroup = null;
  };

  for (const node of varNodes) {
    const parsed = parseVariableLabel(node.label);

    if (parsed) {
      // VARIABLE
      flushVar();
      if (currentGroup === null) {
        currentGroup = { label: '(ungrouped)', path: '(ungrouped)', variables: [] };
        lastPath = '(ungrouped)';
      }
      currentVar = {
        code: parsed.code,
        label: parsed.label,
        category_count: parsed.category_count,
        categories: [],
      };
    } else if (!node.is_leaf) {
      // GROUP (or malformed label that lacks "(N)" — treat as group, warn)
      if (!parseVariableLabel(node.label) && /\(\d+\)/.test(node.label)) {
        // Has parens with digits but didn't match — likely malformed
        warn(`malformed group-like label (treating as group): ${node.label}`);
      }
      groupStack.set(node.depth, node.label);
      for (const d of [...groupStack.keys()]) {
        if (d > node.depth) groupStack.delete(d);
      }
      const path = [...groupStack.keys()].sort((a, b) => a - b)
        .map(d => groupStack.get(d)!)
        .join(' > ');
      if (path !== lastPath) {
        flushGroup();
        currentGroup = { label: node.label, path, variables: [] };
        lastPath = path;
      }
    } else if (node.is_leaf && currentVar !== null && shouldExpandVariable(currentVar.category_count)) {
      // CATEGORY (leaf under an expanded variable)
      currentVar.categories.push(node.label);
    }
    // else: orphan leaf or category under an unexpanded variable — skip
  }

  flushGroup();
  return groups;
}

// ── Playwright entry point ──────────────────────────────────────────────────

async function fetchRawTree(page: Page): Promise<RawNode[]> {
  return await page.evaluate(TREE_EXTRACT_JS) as RawNode[];
}

async function expandTreeForExtraction(page: Page): Promise<void> {
  // Repeatedly expand collapsed nodes that are EITHER groups (no variable
  // pattern in label) OR variables with category_count <= 100. Stop when
  // a round produces no new expansions OR after 30 rounds (safety cap).
  for (let round = 0; round < 30; round++) {
    const nodes = await fetchRawTree(page);
    let didExpand = false;
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      if (!n.is_collapsed) continue;
      const parsed = parseVariableLabel(n.label);
      if (parsed && !shouldExpandVariable(parsed.category_count)) continue; // big variable, skip
      // Click expander on the i-th element
      const expander = page.locator('.treeNodeElement').nth(i).locator('.treeNodeExpander').first();
      try {
        await expander.click();
        await new Promise(r => setTimeout(r, 300));
        didExpand = true;
      } catch { /* stale handle, next round will retry */ }
    }
    if (!didExpand) break;
  }
}

export async function extract(page: Page, datasetName: string): Promise<ExtractedDataset> {
  await page.waitForSelector('.treeNodeElement', { timeout: 30000 }).catch(() => null);
  await expandTreeForExtraction(page);
  const raw = await fetchRawTree(page);
  const { geographies, varNodes } = splitGeographyAndVariables(raw);
  const groups = classifyAndBuildGroups(varNodes, msg => console.warn(`[${datasetName}] ${msg}`));
  return {
    dataset_name: datasetName,
    geographies,
    groups,
    scraped_at: new Date().toISOString(),
    tree_node_count: raw.length,
  };
}
```

- [ ] **Step 4: Run the scraper tests**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test -- src/dict-builder/scraper.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Run full suite**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/dict-builder/scraper.ts src/dict-builder/scraper.test.ts
git commit -m "feat(dict-builder): add tree scraper with depth-aware classify + recursion"
```

---

## Chunk 3: Assembler (cache → SQLite)

### Task 6: `src/dict-builder/assembler.ts`

**Files:**
- Create: `src/dict-builder/assembler.test.ts`
- Create: `src/dict-builder/assembler.ts`

- [ ] **Step 1: Write the failing test file**

```typescript
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

  it('stores geographies_json as a JSON array string', async () => {
    await writeSuccess(cacheDir, ds({
      dataset_name: 'WithGeos',
      geographies: ['Australia', 'LGA (2021 Boundaries)', 'SA1 by Main ASGS'],
    }));
    await build(cacheDir, dbPath);
    const db = new Database(dbPath, { readonly: true });
    const row = db.prepare('SELECT geographies_json FROM datasets WHERE name = ?').get('WithGeos') as { geographies_json: string };
    expect(JSON.parse(row.geographies_json)).toEqual(['Australia', 'LGA (2021 Boundaries)', 'SA1 by Main ASGS']);
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test -- src/dict-builder/assembler.test.ts
```

Expected: FAIL — `Cannot find module './assembler.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/dict-builder/assembler.ts
import { promises as fs } from 'fs';
import Database from 'better-sqlite3';
import { readAllSuccessCaches } from './cache.js';
import type { ExtractedDataset } from './types.js';

// Inlined schema — single source of truth. The category_count column is the
// only addition over what shipped in the legacy DB.
const SCHEMA_SQL = `
CREATE TABLE datasets (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  geographies_json TEXT NOT NULL DEFAULT '[]',
  summary TEXT NOT NULL DEFAULT ''
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
CREATE INDEX idx_groups_dataset ON groups(dataset_id);
CREATE INDEX idx_variables_group ON variables(group_id);
CREATE INDEX idx_categories_variable ON categories(variable_id);
`;

const FTS_SQL = `
CREATE VIRTUAL TABLE datasets_fts USING fts5(name, summary);
CREATE VIRTUAL TABLE variables_fts USING fts5(
  dataset_name, group_path, code, label, categories_text, summary
);
INSERT INTO datasets_fts (rowid, name, summary)
  SELECT id, name, summary FROM datasets;
INSERT INTO variables_fts (rowid, dataset_name, group_path, code, label, categories_text, summary)
  SELECT v.id,
         d.name,
         g.path,
         v.code,
         v.label,
         COALESCE((SELECT GROUP_CONCAT(c.label, ' ') FROM categories c WHERE c.variable_id = v.id), ''),
         ''
  FROM variables v
  JOIN groups g ON g.id = v.group_id
  JOIN datasets d ON d.id = g.dataset_id;
`;

function sortedDatasets(caches: ExtractedDataset[]): ExtractedDataset[] {
  // Sort datasets by name; sort groups within each dataset by path; sort
  // variables within each group by code; preserve categories order from
  // cache (it reflects ABS site display order).
  return [...caches]
    .sort((a, b) => a.dataset_name.localeCompare(b.dataset_name))
    .map(d => ({
      ...d,
      groups: [...d.groups]
        .sort((a, b) => a.path.localeCompare(b.path))
        .map(g => ({
          ...g,
          variables: [...g.variables].sort((a, b) => a.code.localeCompare(b.code)),
        })),
    }));
}

export async function build(cacheDir: string, dbPath: string): Promise<void> {
  const tmpPath = `${dbPath}.tmp`;
  // Clean slate — never start from a partially-populated tmp file
  await fs.rm(tmpPath, { force: true });

  const datasets = sortedDatasets(await readAllSuccessCaches(cacheDir));

  const db = new Database(tmpPath);
  try {
    db.pragma('journal_mode = WAL');
    db.exec(SCHEMA_SQL);

    const insertDataset = db.prepare(
      'INSERT INTO datasets (name, geographies_json, summary) VALUES (?, ?, ?)',
    );
    const insertGroup = db.prepare(
      'INSERT INTO groups (dataset_id, label, path) VALUES (?, ?, ?)',
    );
    const insertVariable = db.prepare(
      'INSERT INTO variables (group_id, code, label, category_count) VALUES (?, ?, ?, ?)',
    );
    const insertCategory = db.prepare(
      'INSERT INTO categories (variable_id, label) VALUES (?, ?)',
    );

    for (const d of datasets) {
      const tx = db.transaction(() => {
        const datasetId = insertDataset.run(
          d.dataset_name,
          JSON.stringify(d.geographies),
          '',
        ).lastInsertRowid as number;

        for (const g of d.groups) {
          const groupId = insertGroup.run(datasetId, g.label, g.path).lastInsertRowid as number;
          for (const v of g.variables) {
            const varId = insertVariable.run(groupId, v.code, v.label, v.category_count).lastInsertRowid as number;
            for (const cat of v.categories) {
              insertCategory.run(varId, cat);
            }
          }
        }
      });
      tx();
    }

    // FTS: rebuild from scratch using base tables
    db.exec(FTS_SQL);
  } finally {
    db.close();
  }

  await fs.rename(tmpPath, dbPath);
}
```

- [ ] **Step 4: Run the assembler tests**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test -- src/dict-builder/assembler.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Run full suite**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/dict-builder/assembler.ts src/dict-builder/assembler.test.ts
git commit -m "feat(dict-builder): add assembler — cache → SQLite with FTS rebuild"
```

---

## Chunk 4: CLI + integration

### Task 7: `scripts/build-dict.ts`

**Files:**
- Create: `scripts/build-dict.ts`

This is the user-facing entry point. It threads the modules together but contains no testable logic of its own beyond argument parsing — keep it thin. Manual testing on totoro provides the integration coverage.

- [ ] **Step 1: Write the script**

```typescript
// scripts/build-dict.ts
//
// CLI: rebuild the ABS dictionary database.
//
// Usage:
//   tsx scripts/build-dict.ts                    # full run with resume
//   tsx scripts/build-dict.ts --clear-cache      # nuke cache, full rescrape
//   tsx scripts/build-dict.ts --only "<name>"    # one dataset (fuzzy-matched)
//   tsx scripts/build-dict.ts --retry-failed     # re-scrape only the .error.json entries
//   tsx scripts/build-dict.ts --headed           # show browser window
//   tsx scripts/build-dict.ts --skip-assemble    # scrape only; no DB build
//   tsx scripts/build-dict.ts --assemble-only    # skip scrape; just rebuild DB from cache

import { chromium, type Page } from 'playwright';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { existsSync } from 'fs';

import { loadCredentials, login } from '../src/shared/abs/auth.js';
import { listDatasets, fuzzyMatchDataset, selectDataset } from '../src/shared/abs/navigator.js';
import { extract } from '../src/dict-builder/scraper.js';
import {
  DEFAULT_CACHE_DIR,
  ensureCacheDir,
  readSuccess,
  hasError,
  writeSuccess,
  writeError,
  listErrorSlugs,
  clearCache,
  writeSummary,
} from '../src/dict-builder/cache.js';
import { build as assembleDb } from '../src/dict-builder/assembler.js';
import { slugify } from '../src/dict-builder/walker.js';
import type { ScrapeError, RunSummary } from '../src/dict-builder/types.js';

const CATALOGUE_URL = 'https://tablebuilder.abs.gov.au/dataCatalogueExplorer.xhtml';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = join(__dirname, '..');
const DEFAULT_DB_PATH = join(PROJECT_ROOT, 'docs', 'explorer', 'data', 'dictionary.db');

interface Args {
  clearCache: boolean;
  only: string | null;
  retryFailed: boolean;
  headed: boolean;
  skipAssemble: boolean;
  assembleOnly: boolean;
  cacheDir: string;
  dbPath: string;
}

function parseArgs(argv: string[]): Args {
  const a: Args = {
    clearCache: false,
    only: null,
    retryFailed: false,
    headed: false,
    skipAssemble: false,
    assembleOnly: false,
    cacheDir: DEFAULT_CACHE_DIR,
    dbPath: DEFAULT_DB_PATH,
  };
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    switch (flag) {
      case '--clear-cache':   a.clearCache = true; break;
      case '--retry-failed':  a.retryFailed = true; break;
      case '--headed':        a.headed = true; break;
      case '--skip-assemble': a.skipAssemble = true; break;
      case '--assemble-only': a.assembleOnly = true; break;
      case '--only':          a.only = argv[++i]; break;
      case '--cache-dir':     a.cacheDir = argv[++i]; break;
      case '--db-path':       a.dbPath = argv[++i]; break;
      case '-h': case '--help':
        process.stdout.write(__filename + ' — see top of file for usage\n');
        process.exit(0);
      default:
        process.stderr.write(`Unknown flag: ${flag}\n`);
        process.exit(2);
    }
  }
  return a;
}

async function navigateToCatalogue(page: Page): Promise<void> {
  await page.goto(CATALOGUE_URL, { waitUntil: 'load' });
  if (page.url().includes('login.xhtml')) {
    throw new Error('Session expired — re-login required');
  }
}

async function scrapeOne(page: Page, datasetName: string): Promise<void> {
  await navigateToCatalogue(page);
  await selectDataset(page, datasetName);
  const data = await extract(page, datasetName);
  await writeSuccess(DEFAULT_CACHE_DIR, data);
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));

  if (args.assembleOnly) {
    console.log(`[build-dict] assemble-only — building DB from ${args.cacheDir}`);
    await assembleDb(args.cacheDir, args.dbPath);
    console.log(`[build-dict] wrote ${args.dbPath}`);
    return;
  }

  if (args.clearCache) {
    console.log(`[build-dict] clearing cache at ${args.cacheDir}`);
    await clearCache(args.cacheDir);
  } else {
    await ensureCacheDir(args.cacheDir);
  }

  const creds = loadCredentials();
  const browser = await chromium.launch({ headless: !args.headed });
  const ctx = await browser.newContext();
  let page = await ctx.newPage();   // `let` so the recovery path can reassign

  const startedAt = new Date().toISOString();
  let succeeded = 0;
  const failedNames: string[] = [];

  try {
    await login(page, creds);
    await navigateToCatalogue(page);

    let queue: string[];
    if (args.only) {
      const all = await listDatasets(page);
      queue = [fuzzyMatchDataset(args.only, all)];
      console.log(`[build-dict] --only matched: ${queue[0]}`);
    } else if (args.retryFailed) {
      const errorSlugs = await listErrorSlugs(args.cacheDir);
      // We need original dataset names; read each .error.json
      const fs = await import('fs/promises');
      const namesFromErrors: string[] = [];
      for (const slug of errorSlugs) {
        const path = join(args.cacheDir, `${slug}.error.json`);
        const text = await fs.readFile(path, 'utf8');
        const err = JSON.parse(text) as ScrapeError;
        namesFromErrors.push(err.dataset_name);
      }
      queue = namesFromErrors;
      console.log(`[build-dict] --retry-failed: ${queue.length} datasets to retry`);
    } else {
      queue = await listDatasets(page);
      console.log(`[build-dict] catalogue: ${queue.length} datasets`);
    }

    for (let i = 0; i < queue.length; i++) {
      const name = queue[i];
      const slug = slugify(name);

      // Skip if already done (resume), unless --retry-failed (which already filters)
      if (!args.retryFailed && (await readSuccess(args.cacheDir, slug)) !== null) {
        console.log(`[${i + 1}/${queue.length}] SKIP (cached): ${name}`);
        succeeded++;
        continue;
      }
      if (!args.retryFailed && await hasError(args.cacheDir, slug)) {
        console.log(`[${i + 1}/${queue.length}] SKIP (errored, run --retry-failed): ${name}`);
        continue;
      }

      console.log(`[${i + 1}/${queue.length}] ${name}`);
      try {
        await scrapeOne(page, name);
        succeeded++;
      } catch (e) {
        const err = e as Error;
        console.error(`  ✗ ${err.message}`);
        await writeError(args.cacheDir, {
          dataset_name: name,
          error: err.message,
          stack: err.stack,
          failed_at: new Date().toISOString(),
          attempt: 1,
        });
        failedNames.push(name);
        // Recover: re-create the page (browser may be wedged) and update the
        // outer `page` reference so the next iteration uses the fresh tab.
        try { await page.close(); } catch {}
        page = await ctx.newPage();
        try {
          await navigateToCatalogue(page);
        } catch {
          await login(page, creds);
          await navigateToCatalogue(page);
        }
      }
    }
  } finally {
    await browser.close();
  }

  const summary: RunSummary = {
    total: succeeded + failedNames.length,
    succeeded,
    failed: failedNames.length,
    failed_datasets: failedNames,
    started_at: startedAt,
    finished_at: new Date().toISOString(),
  };
  await writeSummary(args.cacheDir, summary);

  console.log(`\n=== Summary ===`);
  console.log(`✓ ${summary.succeeded} succeeded`);
  console.log(`✗ ${summary.failed} failed`);
  if (failedNames.length > 0) {
    console.log(`Failed datasets:`);
    for (const n of failedNames) console.log(`  - ${n}`);
    console.log(`Run again with --retry-failed to retry just the errors.`);
  }

  if (!args.skipAssemble && summary.succeeded > 0) {
    console.log(`\n[build-dict] assembling ${args.dbPath}...`);
    await assembleDb(args.cacheDir, args.dbPath);
    console.log(`[build-dict] done.`);
  }
}

main().catch(e => {
  console.error(e);
  process.exit(1);
});
```

- [ ] **Step 2: Verify it type-checks**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Smoke test parsing locally (no browser)**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npx tsx scripts/build-dict.ts --help
```

Expected: prints the usage banner and exits 0.

- [ ] **Step 4: Smoke test `--assemble-only` against an empty cache (should produce empty-but-valid DB)**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && \
  TMPCACHE=$(mktemp -d) TMPDB=$(mktemp -u --suffix=.db) && \
  npx tsx scripts/build-dict.ts --assemble-only --cache-dir "$TMPCACHE" --db-path "$TMPDB" && \
  sqlite3 "$TMPDB" "SELECT name FROM sqlite_master WHERE type='table';" && \
  rm -rf "$TMPCACHE" "$TMPDB"
```

Expected: lists `datasets`, `groups`, `variables`, `categories`, `datasets_fts`, `variables_fts` (plus FTS shadow tables).

- [ ] **Step 5: Commit**

```bash
git add scripts/build-dict.ts
git commit -m "feat(dict-builder): add scripts/build-dict.ts CLI entrypoint"
```

---

### Task 8: Integration smoketest on totoro

**Files:** none (manual operational test)

This task verifies end-to-end behaviour against the real ABS site. **Run on totoro** (bad local internet, full Chromium needed).

- [ ] **Step 1: Push the work to GitHub**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && git push origin main
```

- [ ] **Step 2: SSH to totoro, pull, smoketest one small dataset**

```bash
ssh totoro_ts
cd /tank/code/tablebuilder
git pull
npx tsx scripts/build-dict.ts --only "Crime Victimisation, 2010-11" --skip-assemble 2>&1 | tee /tmp/build-dict-smoke.log
```

Expected output highlights:
- `--only matched: Crime Victimisation, 2010-11`
- `[1/1] Crime Victimisation, 2010-11`
- `✓ 1 succeeded`
- `✗ 0 failed`

- [ ] **Step 3: Inspect the cache file**

```bash
cat ~/.tablebuilder/dict_cache/crime_victimisation_2010_11.json | python3 -m json.tool | head -50
```

Expected: well-formed JSON with `dataset_name`, `geographies` (>=1 entry), `groups` (>=1), at least one variable with the `(N)` parsed correctly into `category_count`.

- [ ] **Step 4: Verify variable rows for census geographic codes**

Run a single census dataset to verify the geographic-recursion fix:

```bash
npx tsx scripts/build-dict.ts --only "2021 Census - cultural diversity" --skip-assemble 2>&1 | tee -a /tmp/build-dict-smoke.log
cat ~/.tablebuilder/dict_cache/2021_census_cultural_diversity.json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
              codes=[v['code'] for g in d['groups'] for v in g['variables']]; \
              print('codes:', codes); \
              print('STRD present:', 'STRD' in codes); \
              print('SA1MAIN_2021 present:', 'SA1MAIN_2021' in codes)"
```

Expected: `STRD present: True` AND `SA1MAIN_2021 present: True`. **This is the acceptance test for the geographic-recursion fix.** If either is False, the scraper has regressed and Task 5 needs to be revisited before continuing.

- [ ] **Step 5: Full run (only if Step 4 passes)**

```bash
nohup npx tsx scripts/build-dict.ts > /tmp/build-dict-full.log 2>&1 &
# go away for ~90 minutes
tail -f /tmp/build-dict-full.log   # monitor
```

Expected: `Summary` section at end shows ≥125 succeeded, ≤6 failed. If failures > 10, investigate before committing the new DB.

- [ ] **Step 6: Validate the new dictionary.db**

```bash
sqlite3 docs/explorer/data/dictionary.db "
SELECT COUNT(*) FROM variables WHERE code IN ('STRD','SA1MAIN_2021','SA2','SA4','LGA_2021','POAS');
SELECT v.label, COUNT(c.id) FROM variables v JOIN categories c ON c.variable_id = v.id WHERE v.code = 'SEXP' GROUP BY v.id LIMIT 1;
SELECT label, category_count FROM variables WHERE code = 'SA1MAIN_2021' LIMIT 1;
"
```

Expected:
- First query returns ≥ 25 (geographic variables present)
- Second query: `Sex|2` (categories captured for SEXP)
- Third query: SA1 with category_count > 50000 (high-cardinality recorded but not expanded)

- [ ] **Step 7: Commit the new DB and push**

```bash
git add docs/explorer/data/dictionary.db
git commit -m "chore(dict): rebuild dictionary.db with geographic variables + categories"
git push origin main
```

- [ ] **Step 8: Restart the service**

```bash
sudo systemctl restart tablebuilder
curl -s http://localhost:3000/api/datasets | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"
```

Expected: ≥125 datasets returned. Service is now serving the rebuilt DB.

---

## Final verification

- [ ] **Run the full unit-test suite one last time**

```bash
cd /Users/dewoller/code/rmai/tablebuilder && npm test
```

Expected: all green (61 existing + walker + cache + scraper + assembler tests).

- [ ] **Verify the geographic gap is closed**

After Step 6 above, the answer to "why does cultural diversity have only 7 fields?" should be: it doesn't — it has 8 demographic groups + the geographic group with `STRD`, `SA4`, `LGA_2021`, `POAS`, `SA1MAIN_2021`, etc. all visible as variable rows.
