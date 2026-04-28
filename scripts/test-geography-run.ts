// scripts/test-geography-run.ts
// One-off test: invoke runTablebuilder directly (no Express, no Cloudflare).
// Verifies that selectGeography + the rest of the pipeline produce a real
// LGA-level CSV. Run on totoro:
//   xvfb-run -a npx tsx scripts/test-geography-run.ts

import { chromium } from 'playwright';
import { loadCredentials } from '../src/shared/abs/auth.js';
import { runTablebuilder } from '../src/shared/abs/runner.js';
import type { Input } from '../src/shared/abs/types.js';

const input: Input = {
  dataset: '2021 Census - cultural diversity',
  geography: { id: 0, label: 'Local Government Areas (2021 Boundaries) (UR)' },
  rows: [{ id: 0, label: 'Sex' }],
  columns: [],
  wafers: [],
  outputPath: '/tmp/test-geography-result.csv',
};

async function main() {
  const creds = loadCredentials();
  console.log('[test] launching Chromium…');
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  const startMs = Date.now();
  const ac = new AbortController();
  // 25-min hard deadline matching the server-side default
  const deadline = setTimeout(() => {
    console.log('[test] DEADLINE — aborting at 25 min');
    ac.abort();
  }, 25 * 60 * 1000);

  try {
    const result = await runTablebuilder(page, creds, input, (event) => {
      const t = ((Date.now() - startMs) / 1000).toFixed(1);
      console.log(`[${t}s] ${JSON.stringify(event)}`);
    }, ac.signal);
    clearTimeout(deadline);
    console.log('\n[test] SUCCESS');
    console.log(`  csvPath: ${result.csvPath}`);
    console.log(`  rowCount: ${result.rowCount}`);
    console.log(`  resolvedDataset: ${result.dataset}`);
  } catch (e) {
    clearTimeout(deadline);
    console.log('\n[test] FAILED');
    console.log(`  error: ${(e as Error).message}`);
    if ((e as Error).stack) console.log((e as Error).stack);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch(e => { console.error(e); process.exit(2); });
