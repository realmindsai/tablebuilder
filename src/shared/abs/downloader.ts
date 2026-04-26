// src/shared/abs/downloader.ts
import { mkdir, writeFile, readFile } from 'fs/promises';
import { dirname, join } from 'path';
import { tmpdir } from 'os';
import { randomUUID } from 'crypto';
import AdmZip from 'adm-zip';
import type { Page } from 'playwright-core';
import { trySaveViaResponse } from './response-capture.js';
import { queueDownload } from './queue-downloader.js';
import { noopReporter, type PhaseReporter } from './reporter.js';

function defaultOutputPath(): string {
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  return join('output', `abs-tablebuilder-${ts}.csv`);
}

async function ensureDir(filePath: string): Promise<void> {
  await mkdir(dirname(filePath), { recursive: true });
}

async function extractCsvFromZip(zipPath: string, outputPath: string): Promise<void> {
  const zip = new AdmZip(zipPath);
  const entry = zip.getEntries().find(e => e.entryName.endsWith('.csv'));
  if (!entry) throw new Error('Downloaded ZIP contains no CSV file.');
  const csvBytes = zip.readFile(entry);
  if (!csvBytes) throw new Error('Failed to read CSV from ZIP.');
  await ensureDir(outputPath);
  await writeFile(outputPath, csvBytes);
}

function countCsvRows(csv: string): number {
  const lines = csv.split('\n').filter(l => l.trim().length > 0);
  return Math.max(0, lines.length - 1); // subtract header row
}

const DOWNLOAD_BTN_SELECTORS = [
  '#downloadControl\\:downloadButton',
  'input[value="Download table"]',
  'a[title="Download table"]',
];

async function saveDownload(
  page: Page,
  downloadBtn: ReturnType<typeof page.locator>,
  tmpPath: string,
): Promise<boolean> {
  return trySaveViaResponse(
    page,
    () => downloadBtn.evaluate((el: HTMLElement) => el.click()),
    tmpPath,
    15000,
  );
}

async function readTableFromDom(page: Page, outputPath: string): Promise<boolean> {
  // Read the displayed table data directly from the page DOM.
  // The ABS table is visible after retrieveTable() populates it.
  const tableData = await page.evaluate(() => {
    // Log all tables for debugging
    const allTables = Array.from(document.querySelectorAll('table')).map(t => ({
      id: t.id, cls: t.className, rows: t.rows.length, cells: t.querySelectorAll('td').length,
      sample: Array.from(t.querySelectorAll('td')).slice(0, 3).map(c => c.textContent?.trim() ?? '').filter(Boolean),
    }));
    console.log('readTableFromDom tables:', JSON.stringify(allTables));

    // Target the ABS cross-tab results table specifically
    // The data table has class "crossTabTable" or contains the actual data
    let table: HTMLTableElement | null =
      document.querySelector<HTMLTableElement>('table.crossTabTable') ??
      document.querySelector<HTMLTableElement>('table#pageForm\\:dataTable') ??
      document.querySelector<HTMLTableElement>('table[id*="dataTable"]') ??
      document.querySelector<HTMLTableElement>('table[id*="data"]');

    // Fallback: find any table with numeric or "-" data (not just navigation tables)
    if (!table) {
      for (const t of Array.from(document.querySelectorAll('table'))) {
        const cells = Array.from(t.querySelectorAll('td'));
        const hasData = cells.some(c => {
          const text = (c.textContent ?? '').trim();
          return /^\d[\d,]*$/.test(text) || text === '-' || text === 'N/A';
        });
        if (hasData && cells.length >= 2) { table = t as HTMLTableElement; break; }
      }
    }

    if (!table) return null;

    const rows = Array.from(table.querySelectorAll('tr'));
    return rows.map(row =>
      Array.from(row.querySelectorAll('th, td')).map(cell => cell.textContent?.trim() ?? '')
    ).filter(row => row.length > 0 && row.some(cell => cell.length > 0));
  });

  if (!tableData || tableData.length === 0) {
    // Diagnostic: show what elements with numeric data exist on the page
    const diagnostic = await page.evaluate(() => {
      const allTables = Array.from(document.querySelectorAll('table')).map(t => ({
        id: t.id, cls: t.className, rows: t.rows.length, cells: t.querySelectorAll('td').length,
        sample: Array.from(t.querySelectorAll('td')).slice(0, 5).map(c => c.textContent?.trim()).filter(Boolean),
      }));
      const numericEls = Array.from(document.querySelectorAll('[class*="cell"], [class*="value"], [class*="data"], td, th'))
        .filter(el => /^\d[\d,]*$/.test((el.textContent ?? '').trim()))
        .slice(0, 10)
        .map(el => ({ tag: el.tagName, cls: (el as HTMLElement).className, text: el.textContent?.trim() }));
      return { allTables, numericEls, bodySnippet: document.body.innerText.substring(200, 800) };
    });
    console.log('DOM diagnostic - tables:', JSON.stringify(diagnostic.allTables.slice(0, 5)));
    console.log('DOM diagnostic - numeric elements:', JSON.stringify(diagnostic.numericEls));
    console.log('DOM diagnostic - body:', diagnostic.bodySnippet);
    return false;
  }

  console.log(`downloadCsv: reading table from DOM (${tableData.length} rows, ${tableData[0]?.length ?? 0} cols), first row:`, JSON.stringify(tableData[0]));
  // Escape cells for CSV
  const csv = tableData.map(row =>
    row.map(cell => cell.includes(',') || cell.includes('"') ? `"${cell.replace(/"/g, '""')}"` : cell).join(',')
  ).join('\n');

  await ensureDir(outputPath);
  await writeFile(outputPath, csv);
  return true;
}

export async function downloadCsv(
  page: Page,
  outputPath?: string,
  reporter: PhaseReporter = noopReporter,
): Promise<{ csvPath: string; rowCount: number }> {
  const resolvedPath = outputPath ?? defaultOutputPath();
  const t0 = Date.now();
  reporter({ type: 'phase_start', phaseId: 'download', phaseLabel: 'Downloading result', phaseSub: 'streaming CSV' });
  reporter({ type: 'log', level: 'phase', message: '» phase 7/7 — Downloading result' });
  reporter({ type: 'log', level: 'info', message: `  streaming bytes → ${resolvedPath}` });
  await ensureDir(resolvedPath);

  try {
    // Note: CSV format is selected in retrieveTable (before the retrieve click) per Python order

    let downloadBtn = null;
    for (const sel of DOWNLOAD_BTN_SELECTORS) {
      const el = page.locator(sel).first();
      if (await el.count() > 0) {
        downloadBtn = el;
        break;
      }
    }

    if (!downloadBtn) {
      throw new Error('Download button not found on page.');
    }

    const tmpPath = join(tmpdir(), `abs-download-${randomUUID()}`);

    // Try direct download first (quick 15s attempt via Playwright download event or response interception)
    const directSuccess = await saveDownload(page, downloadBtn, tmpPath);

    if (!directSuccess) {
      // 2. Queue-based download — submit to ABS server queue, poll, download the completed file
      try {
        await queueDownload(page, tmpPath);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        console.log(`downloadCsv: queue download failed (${msg}), trying DOM extraction`);

        // 3. DOM extraction — last resort, reads whatever is rendered on the page
        const domSuccess = await readTableFromDom(page, resolvedPath);
        if (!domSuccess) {
          throw new Error('Could not download table: all methods failed.');
        }
        const content = await readFile(resolvedPath, 'utf-8');
        reporter({ type: 'log', level: 'ok', message: '  ✓ table extracted from DOM' });
        reporter({ type: 'phase_complete', phaseId: 'download', elapsed: (Date.now() - t0) / 1000 });
        return { csvPath: resolvedPath, rowCount: countCsvRows(content) };
      }
    }

    const fileBuffer = await readFile(tmpPath);
    const isZip = fileBuffer[0] === 0x50 && fileBuffer[1] === 0x4b; // PK magic bytes

    if (isZip) {
      await extractCsvFromZip(tmpPath, resolvedPath);
    } else {
      await writeFile(resolvedPath, fileBuffer);
    }

    const content = await readFile(resolvedPath, 'utf-8');
    const rowCount = countCsvRows(content);
    reporter({ type: 'log', level: 'ok', message: `  ✓ downloaded ${rowCount} rows` });
    reporter({ type: 'phase_complete', phaseId: 'download', elapsed: (Date.now() - t0) / 1000 });
    return { csvPath: resolvedPath, rowCount };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    reporter({ type: 'phase_error', phaseId: 'download', message });
    throw err;
  }
}
