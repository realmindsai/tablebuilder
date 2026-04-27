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

const CATALOGUE_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/dataCatalogueExplorer.xhtml';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
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
  // Optimisation: if we're currently on tableView (just finished extracting a
  // dataset), use the browser back button instead of page.goto. goBack restores
  // the previous catalogue page including its expanded tree state — saving the
  // ~5-10 minutes of re-expansion that page.goto would otherwise force on every
  // dataset. Across 200 datasets that's a difference of ~30 hours.
  if (page.url().includes('tableView.xhtml')) {
    try {
      await page.goBack({ waitUntil: 'load', timeout: 30000 });
      if (page.url().includes('dataCatalogueExplorer.xhtml')) {
        // Successfully restored. Treat the existing tree state as expanded —
        // expandAllCollapsed will be a no-op if there's nothing left to click.
        await page.waitForSelector('.treeNodeElement', { timeout: 15000 }).catch(() => null);
        return;
      }
    } catch { /* fall through to fresh navigation */ }
  }

  // First navigation, or goBack failed to land on the catalogue. Use networkidle
  // (matches legacy Python builder) so JSF's AJAX has time to populate the
  // catalogue tree — `load` fires too early and the Census subtree is missing
  // from the result. Fall back to load if networkidle doesn't settle in time
  // (some JSF flows long-poll forever).
  try {
    await page.goto(CATALOGUE_URL, { waitUntil: 'networkidle', timeout: 60000 });
  } catch {
    await page.waitForLoadState('load').catch(() => null);
  }
  if (page.url().includes('login.xhtml')) {
    throw new Error('Session expired — re-login required');
  }
  await page.waitForSelector('.treeNodeElement', { timeout: 30000 }).catch(() => null);
  await new Promise(r => setTimeout(r, 2000));  // let any tail-end JSF AJAX settle
}

async function scrapeOne(page: Page, datasetName: string, cacheDir: string): Promise<void> {
  await navigateToCatalogue(page);
  await selectDataset(page, datasetName);
  const data = await extract(page, datasetName);
  await writeSuccess(cacheDir, data);
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
      const fsPromises = await import('fs/promises');
      const namesFromErrors: string[] = [];
      for (const slug of errorSlugs) {
        const path = join(args.cacheDir, `${slug}.error.json`);
        const text = await fsPromises.readFile(path, 'utf8');
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
        await scrapeOne(page, name, args.cacheDir);
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
