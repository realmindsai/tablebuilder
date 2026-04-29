// scripts/probe-dblclick.ts
//
// Instrument a known-good catalogue dblclick → tableView navigation so we can
// see the exact JSF request shape. Captures every /webapi/jsf/ request from
// the moment we attach the listener until tableView.xhtml arrives, including
// method, URL, post body, and headers. Output to data/probe/dblclick-requests.json.
//
// Run on totoro:
//   xvfb-run -a npx tsx scripts/probe-dblclick.ts ["dataset name"]
//
// Default target is "2021 Census - cultural diversity" — known-good per the
// user's last live run.

import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { mkdir, writeFile } from 'fs/promises';

import { loadCredentials, login } from '../src/shared/abs/auth.js';
import { listDatasets } from '../src/shared/abs/navigator.js';

const CATALOGUE_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/dataCatalogueExplorer.xhtml';
const TARGET = process.argv[2] || '2021 Census - cultural diversity';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const OUT_DIR = join(__dirname, '..', 'data', 'probe');

interface ReqInfo {
  url: string;
  method: string;
  postData: string | null;
  headers: Record<string, string>;
  resourceType: string;
  status?: number;
  respHeaders?: Record<string, string>;
  respBodySnippet?: string;
}

async function main(): Promise<void> {
  await mkdir(OUT_DIR, { recursive: true });

  const creds = loadCredentials();
  const browser = await chromium.launch({ headless: false });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();

  try {
    console.log('[probe-dblclick] login + navigate');
    await login(page, creds);
    try {
      await page.goto(CATALOGUE_URL, { waitUntil: 'networkidle', timeout: 60_000 });
    } catch {
      await page.waitForLoadState('load').catch(() => null);
    }

    console.log('[probe-dblclick] expanding catalogue (this is the slow part — be patient)…');
    const t0 = Date.now();
    const available = await listDatasets(page);
    console.log(`[probe-dblclick] catalogue expanded in ${((Date.now() - t0) / 1000).toFixed(1)}s — ${available.length} datasets`);

    // Resolve target via DOM (single round-trip). Allow exact or whole-word fuzzy.
    const resolved = await page.evaluate((target: string) => {
      const labels = Array.from(document.querySelectorAll('.treeNodeElement .label'));
      const exact = labels.find(l => (l.textContent ?? '').trim() === target);
      if (exact) return (exact.textContent ?? '').trim();
      const tokens = target.toLowerCase().split(/\s+/).filter(Boolean);
      const fuzzy = labels.find(l => {
        const t = (l.textContent ?? '').toLowerCase();
        return tokens.every(tok => t.includes(tok));
      });
      return fuzzy ? (fuzzy.textContent ?? '').trim() : null;
    }, TARGET);

    if (!resolved) throw new Error(`could not match '${TARGET}' in catalogue`);
    console.log(`[probe-dblclick] resolved target: '${resolved}'`);

    // Hook listeners NOW, after the tree is expanded — filters out the
    // expansion AJAX noise and captures only the dblclick → tableView path.
    const requests: ReqInfo[] = [];
    page.on('request', (req) => {
      if (!req.url().includes('/webapi/jsf/')) return;
      requests.push({
        url: req.url(),
        method: req.method(),
        postData: req.postData(),
        headers: req.headers(),
        resourceType: req.resourceType(),
      });
    });
    page.on('response', async (res) => {
      const url = res.url();
      if (!url.includes('/webapi/jsf/')) return;
      const entry = requests.find(r => r.url === url && r.status == null);
      if (!entry) return;
      entry.status = res.status();
      entry.respHeaders = res.headers();
      // Capture a small snippet of the body so we can see what came back.
      try {
        const body = await res.text();
        entry.respBodySnippet = body.slice(0, 800);
      } catch { /* binary or unavailable */ }
    });

    console.log('[probe-dblclick] dblclicking target — capturing requests…');
    const labels = await page.locator('.treeNodeElement .label').all();
    let targetEl = null;
    for (const lbl of labels) {
      const t = (await lbl.textContent())?.trim() ?? '';
      if (t === resolved) { targetEl = lbl; break; }
    }
    if (!targetEl) throw new Error(`element vanished: '${resolved}'`);

    await targetEl.dblclick();
    await page.waitForURL('**/tableView.xhtml*', { timeout: 30_000 });
    console.log(`[probe-dblclick] arrived at: ${page.url()}`);

    // Brief settle for tail-end requests after tableView arrives.
    await new Promise(r => setTimeout(r, 2000));

    console.log(`\n[probe-dblclick] captured ${requests.length} JSF requests`);
    const posts = requests.filter(r => r.method === 'POST');
    console.log(`[probe-dblclick] ${posts.length} POSTs:`);
    for (const p of posts) {
      console.log(`\n  POST ${p.url}`);
      console.log(`    status: ${p.status ?? '?'}`);
      if (p.postData) {
        console.log(`    postData (${p.postData.length} chars):`);
        console.log(`      ${p.postData.slice(0, 600)}${p.postData.length > 600 ? '…' : ''}`);
      }
      if (p.respHeaders?.['content-type']) console.log(`    response content-type: ${p.respHeaders['content-type']}`);
    }

    const gets = requests.filter(r => r.method === 'GET');
    console.log(`\n[probe-dblclick] ${gets.length} GETs (urls only):`);
    for (const g of gets) console.log(`  GET ${g.url}`);

    await writeFile(
      join(OUT_DIR, 'dblclick-requests.json'),
      JSON.stringify({ target: resolved, finalUrl: page.url(), requests }, null, 2),
    );
    console.log(`\n[probe-dblclick] wrote ${OUT_DIR}/dblclick-requests.json`);
  } finally {
    await ctx.close();
    await browser.close();
  }
}

main().catch(err => { console.error(err); process.exit(1); });
