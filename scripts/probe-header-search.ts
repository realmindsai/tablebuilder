// scripts/probe-header-search.ts
//
// Test what the catalogue page's global header search does. Submits a query
// and captures: the resulting URL, every JSF request, all <a> links on the
// result page, anything that looks like a dataset row, plus a screenshot.
//
// Run on totoro:
//   xvfb-run -a npx tsx scripts/probe-header-search.ts ["query"]
//
// Default query: "2021 Census - cultural diversity"

import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { mkdir, writeFile } from 'fs/promises';

import { loadCredentials, login } from '../src/shared/abs/auth.js';

const CATALOGUE_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/dataCatalogueExplorer.xhtml';
const QUERY = process.argv[2] || '2021 Census - cultural diversity';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const OUT_DIR = join(__dirname, '..', 'data', 'probe');

interface ReqInfo {
  url: string;
  method: string;
  postData: string | null;
  status?: number;
  respContentType?: string;
}

async function main(): Promise<void> {
  await mkdir(OUT_DIR, { recursive: true });

  const creds = loadCredentials();
  const browser = await chromium.launch({ headless: false });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();

  try {
    console.log('[probe-header-search] login + navigate');
    await login(page, creds);
    try {
      await page.goto(CATALOGUE_URL, { waitUntil: 'networkidle', timeout: 60_000 });
    } catch {
      await page.waitForLoadState('load').catch(() => null);
    }
    await page.waitForSelector('input[name="headerSearchForm:searchText"]', { timeout: 30_000 });
    console.log(`[probe-header-search] catalogue ready, URL=${page.url()}`);

    // Hook listener BEFORE submitting search.
    const requests: ReqInfo[] = [];
    page.on('request', (req) => {
      if (!req.url().includes('/webapi/jsf/')) return;
      requests.push({
        url: req.url(),
        method: req.method(),
        postData: req.postData(),
      });
    });
    page.on('response', (res) => {
      if (!res.url().includes('/webapi/jsf/')) return;
      const entry = requests.find(r => r.url === res.url() && r.status == null);
      if (entry) {
        entry.status = res.status();
        entry.respContentType = res.headers()['content-type'];
      }
    });

    console.log(`[probe-header-search] typing query: '${QUERY}'`);
    await page.fill('input[name="headerSearchForm:searchText"]', QUERY);

    console.log('[probe-header-search] submitting search…');
    const beforeUrl = page.url();
    const t0 = Date.now();
    // Try clicking the submit button; some JSF forms require it to be the
    // synthetic button rather than form.submit().
    await page.locator('input[name="headerSearchForm:searchButton"]').click();

    // Wait for either a navigation or a JSF AJAX update to settle.
    await Promise.race([
      page.waitForURL(url => url.href !== beforeUrl, { timeout: 15_000 }).catch(() => null),
      page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => null),
    ]);
    await new Promise(r => setTimeout(r, 2500)); // tail-end AJAX
    const elapsed = Date.now() - t0;
    console.log(`[probe-header-search] settled in ${(elapsed / 1000).toFixed(1)}s, final URL=${page.url()}`);
    console.log(`[probe-header-search] navigated=${page.url() !== beforeUrl}`);

    // Snapshot the result page.
    const linkInfo = await page.evaluate(() => {
      const out: Array<{ href: string; text: string; onclick: string }> = [];
      document.querySelectorAll('a').forEach(a => {
        const href = (a as HTMLAnchorElement).href ?? '';
        const text = (a.textContent ?? '').trim().slice(0, 120);
        const onclick = a.getAttribute('onclick') ?? '';
        if (text || href) out.push({ href, text, onclick });
      });
      return out;
    });

    const treeLabels = await page.evaluate(() => {
      const out: Array<{ label: string; expanderClass: string; ancestorOnclick: string }> = [];
      document.querySelectorAll('.treeNodeElement').forEach(n => {
        const lbl = (n.querySelector('.label')?.textContent ?? '').trim();
        const exp = n.querySelector('.treeNodeExpander')?.className ?? '';
        // Look for a clickable ancestor or attribute that might encode a target
        const onclickEl = (n.querySelector('[onclick]') as HTMLElement | null);
        const onclick = onclickEl?.getAttribute('onclick')?.slice(0, 200) ?? '';
        if (lbl) out.push({ label: lbl, expanderClass: exp, ancestorOnclick: onclick });
      });
      return out;
    });

    // Dataset-like elements: things that mention "tableView" in href/onclick,
    // or rows in a result list.
    const datasetCandidates = linkInfo.filter(l =>
      /tableView|catalogue|dataset/i.test(`${l.href} ${l.onclick}`),
    );

    console.log(`\n[probe-header-search] requests captured: ${requests.length}`);
    for (const r of requests) {
      console.log(`  ${r.method} ${r.url}  status=${r.status ?? '?'}  ct=${r.respContentType ?? '?'}`);
      if (r.postData) {
        console.log(`    postData: ${r.postData.slice(0, 400)}${r.postData.length > 400 ? '…' : ''}`);
      }
    }

    console.log(`\n[probe-header-search] tree nodes after search: ${treeLabels.length}`);
    if (treeLabels.length > 0 && treeLabels.length <= 30) {
      treeLabels.forEach(t => console.log(`  [${t.expanderClass.includes('leaf') ? 'L' : t.expanderClass.includes('collapsed') ? 'C' : 'E'}] ${t.label}`));
    } else if (treeLabels.length > 30) {
      console.log('  (>30 — first 20 shown)');
      treeLabels.slice(0, 20).forEach(t => console.log(`  [${t.expanderClass.includes('leaf') ? 'L' : t.expanderClass.includes('collapsed') ? 'C' : 'E'}] ${t.label}`));
    }

    console.log(`\n[probe-header-search] anchors with tableView/dataset hint: ${datasetCandidates.length}`);
    datasetCandidates.slice(0, 20).forEach(l => console.log(`  href="${l.href}" text="${l.text}" onclick="${l.onclick.slice(0, 120)}"`));

    if (linkInfo.length > 0 && datasetCandidates.length === 0) {
      console.log(`\n[probe-header-search] (no obvious dataset anchors — first 20 anchors total)`);
      linkInfo.slice(0, 20).forEach(l => console.log(`  href="${l.href}" text="${l.text}"`));
    }

    await writeFile(
      join(OUT_DIR, 'header-search-result.json'),
      JSON.stringify({
        query: QUERY,
        beforeUrl,
        finalUrl: page.url(),
        navigated: page.url() !== beforeUrl,
        elapsedMs: elapsed,
        requests,
        treeLabels,
        anchors: linkInfo,
      }, null, 2),
    );
    await writeFile(join(OUT_DIR, 'header-search-result.html'), await page.content());
    await page.screenshot({ path: join(OUT_DIR, 'header-search-result.png'), fullPage: true });
    console.log(`\n[probe-header-search] wrote ${OUT_DIR}/header-search-result.{json,html,png}`);
  } finally {
    await ctx.close();
    await browser.close();
  }
}

main().catch(err => { console.error(err); process.exit(1); });
