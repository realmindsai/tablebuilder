// scripts/probe-catalogue.ts
//
// Discover the actual selectors on the ABS catalogue page so we can implement
// a fast search-driven selectDataset path. Login + navigate to catalogue +
// dump every <input>, <button>, and likely-search element with its id, name,
// placeholder, classes, and text. Also screenshot for reference.
//
// Run on totoro (needs Xvfb because Playwright headless behaves differently
// for some JSF AJAX flows):
//   xvfb-run -a npx tsx scripts/probe-catalogue.ts
//
// Output:
//   data/probe/catalogue-elements.json   structured dump of relevant elements
//   data/probe/catalogue.png             full-page screenshot
//   data/probe/catalogue.html            page HTML at probe time

import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { mkdir, writeFile } from 'fs/promises';

import { loadCredentials, login } from '../src/shared/abs/auth.js';

const CATALOGUE_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/dataCatalogueExplorer.xhtml';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const OUT_DIR = join(__dirname, '..', 'data', 'probe');

interface ElementInfo {
  tag: string;
  id: string;
  name: string;
  type: string;
  placeholder: string;
  classes: string;
  visible: boolean;
  text: string;
}

async function main(): Promise<void> {
  await mkdir(OUT_DIR, { recursive: true });

  const creds = loadCredentials();
  const browser = await chromium.launch({ headless: false });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();

  try {
    console.log('[probe] logging in…');
    await login(page, creds);

    console.log('[probe] navigating to catalogue…');
    try {
      await page.goto(CATALOGUE_URL, { waitUntil: 'networkidle', timeout: 60_000 });
    } catch {
      await page.waitForLoadState('load').catch(() => null);
    }
    await page.waitForSelector('.treeNodeElement', { timeout: 30_000 }).catch(() => null);
    await new Promise(r => setTimeout(r, 3000)); // let JSF AJAX finish

    console.log('[probe] dumping page elements…');
    const elements = await page.evaluate(() => {
      const out: Array<{
        tag: string; id: string; name: string; type: string; placeholder: string;
        classes: string; visible: boolean; text: string;
      }> = [];
      const interesting = ['input', 'button', 'a[role="button"]', 'select', 'textarea', '[onclick]'];
      const nodes = document.querySelectorAll(interesting.join(','));
      nodes.forEach(n => {
        const el = n as HTMLElement;
        const rect = el.getBoundingClientRect();
        out.push({
          tag: el.tagName.toLowerCase(),
          id: el.id ?? '',
          name: (el as HTMLInputElement).name ?? '',
          type: (el as HTMLInputElement).type ?? '',
          placeholder: (el as HTMLInputElement).placeholder ?? '',
          classes: el.className ?? '',
          visible: rect.width > 0 && rect.height > 0,
          text: (el.textContent ?? '').trim().slice(0, 80),
        });
      });
      return out;
    });

    const interesting = elements.filter((e: ElementInfo) =>
      /search|filter|find|query/i.test(`${e.id} ${e.name} ${e.placeholder} ${e.classes}`)
    );

    console.log(`[probe] ${elements.length} total interactive elements; ${interesting.length} look search-related`);
    if (interesting.length > 0) {
      console.log('[probe] search-related elements:');
      for (const e of interesting) {
        console.log(`  ${e.tag}#${e.id || '(no id)'} name="${e.name}" placeholder="${e.placeholder}" classes="${e.classes}" visible=${e.visible}`);
      }
    } else {
      console.log('[probe] no obvious search elements — dumping all visible inputs:');
      for (const e of elements.filter((x: ElementInfo) => x.tag === 'input' && x.visible)) {
        console.log(`  ${e.tag}#${e.id || '(no id)'} type="${e.type}" name="${e.name}" placeholder="${e.placeholder}"`);
      }
    }

    await writeFile(
      join(OUT_DIR, 'catalogue-elements.json'),
      JSON.stringify({ url: page.url(), interesting, all: elements }, null, 2),
    );
    await writeFile(join(OUT_DIR, 'catalogue.html'), await page.content());
    await page.screenshot({ path: join(OUT_DIR, 'catalogue.png'), fullPage: true });

    console.log(`[probe] wrote ${OUT_DIR}/catalogue-elements.json, .html, .png`);
  } finally {
    await ctx.close();
    await browser.close();
  }
}

main().catch(err => { console.error(err); process.exit(1); });
