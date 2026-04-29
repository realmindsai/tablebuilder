// scripts/probe-fast-path.ts
//
// End-to-end test of the search-driven selectDataset replacement: login,
// catalogue, header search, click matching result anchor, wait for tableView.
// If this works, the production fix in navigator.ts is just this sequence.
//
// Run on totoro:
//   xvfb-run -a npx tsx scripts/probe-fast-path.ts ["dataset"]
//
// Default: "2021 Census - cultural diversity"

import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { mkdir, writeFile } from 'fs/promises';

import { loadCredentials, login } from '../src/shared/abs/auth.js';

const CATALOGUE_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/dataCatalogueExplorer.xhtml';
const TARGET = process.argv[2] || '2021 Census - cultural diversity';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const OUT_DIR = join(__dirname, '..', 'data', 'probe');

async function main(): Promise<void> {
  await mkdir(OUT_DIR, { recursive: true });

  const creds = loadCredentials();
  const browser = await chromium.launch({ headless: false });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();

  const stages: Array<{ stage: string; elapsedMs: number; url: string; note?: string }> = [];
  const tStart = Date.now();
  const stamp = (stage: string, note?: string) => {
    stages.push({ stage, elapsedMs: Date.now() - tStart, url: page.url(), note });
    console.log(`[fast-path] ${((Date.now() - tStart) / 1000).toFixed(2)}s — ${stage} :: ${page.url()}${note ? ` (${note})` : ''}`);
  };

  try {
    stamp('start');
    await login(page, creds);
    stamp('after login');

    try {
      await page.goto(CATALOGUE_URL, { waitUntil: 'networkidle', timeout: 60_000 });
    } catch {
      await page.waitForLoadState('load').catch(() => null);
    }
    await page.waitForSelector('input[name="headerSearchForm:searchText"]', { timeout: 30_000 });
    stamp('catalogue ready');

    await page.fill('input[name="headerSearchForm:searchText"]', TARGET);
    await page.locator('input[name="headerSearchForm:searchButton"]').click();
    await page.waitForURL('**/dataCatalogueSearch.xhtml*', { timeout: 30_000 });
    stamp('search results landed');

    // Wait for result table render.
    await page.waitForSelector('a[id*="searchResultTable"]', { timeout: 15_000 });
    await new Promise(r => setTimeout(r, 500));
    stamp('result table rendered');

    // Find matching anchor.
    const match = await page.evaluate((target: string) => {
      const anchors = Array.from(document.querySelectorAll('a'))
        .filter((a) => /searchResultTable/.test(a.id))
        .map((a) => ({ id: a.id, text: (a.textContent ?? '').trim() }));
      const exact = anchors.find((c) => c.text === target);
      if (exact) return { matched: exact, total: anchors.length, candidates: null };
      const tokens = target.toLowerCase().split(/\s+/).filter(Boolean);
      const fuzzy = anchors.find((c) => {
        const t = c.text.toLowerCase();
        return tokens.every((tok) => t.includes(tok));
      });
      return {
        matched: fuzzy ?? null,
        total: anchors.length,
        candidates: fuzzy ? null : anchors.slice(0, 10),
      };
    }, TARGET);

    if (!match.matched) {
      console.log(`[fast-path] FAILED — no match in ${match.total} results`);
      console.log(`[fast-path] candidates: ${JSON.stringify(match.candidates, null, 2)}`);
      throw new Error(`no result anchor matched '${TARGET}'`);
    }
    stamp('match found', `id=${match.matched.id} text="${match.matched.text}"`);

    // Click via attribute selector — handles JSF colons cleanly.
    const matchId: string = match.matched.id;
    await page.locator(`a[id="${matchId}"]`).click();
    stamp('clicked result anchor');

    await page.waitForURL('**/tableView.xhtml*', { timeout: 30_000 });
    stamp('arrived at tableView');

    await page.waitForSelector('.treeNodeElement', { timeout: 30_000 }).catch(() => null);
    await new Promise(r => setTimeout(r, 1500));
    stamp('tableView tree visible');

    const treeNodeCount = await page.locator('.treeNodeElement').count();
    console.log(`\n[fast-path] SUCCESS — total elapsed ${((Date.now() - tStart) / 1000).toFixed(2)}s, ${treeNodeCount} tree nodes on tableView`);

    await writeFile(
      join(OUT_DIR, 'fast-path-result.json'),
      JSON.stringify({ target: TARGET, matched: match.matched, totalElapsedMs: Date.now() - tStart, stages, treeNodeCount }, null, 2),
    );
    await page.screenshot({ path: join(OUT_DIR, 'fast-path-tableview.png'), fullPage: false });
    console.log(`[fast-path] wrote ${OUT_DIR}/fast-path-result.json + .png`);
  } catch (err) {
    console.error(`\n[fast-path] FAILED at stage ${stages.length}:`);
    console.error(`  url=${page.url()}`);
    console.error(`  stages so far: ${JSON.stringify(stages, null, 2)}`);
    console.error(`  error: ${(err as Error).message}`);
    process.exitCode = 1;
  } finally {
    await ctx.close();
    await browser.close();
  }
}

main().catch(err => { console.error(err); process.exit(1); });
