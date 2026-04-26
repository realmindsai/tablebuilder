// tests/e2e/abs-tablebuilder.e2e.ts
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';
import { existsSync, unlinkSync, readFileSync } from 'fs';
import { join } from 'path';
import { loadCredentials, login, acceptTerms } from '../../src/shared/abs/auth.js';
import { selectDataset, selectVariables } from '../../src/shared/abs/navigator.js';
import { retrieveTable } from '../../src/shared/abs/jsf.js';
import { downloadCsv } from '../../src/shared/abs/downloader.js';
import type { PhaseEvent } from '../../src/shared/abs/reporter.js';

const RUN_E2E = process.env.ABS_RUN_E2E === '1';

// Navigate back to the dataset catalogue between tests (session stays logged in)
const CATALOGUE_URL = 'https://tablebuilder.abs.gov.au/webapi/jsf/dataCatalogueExplorer.xhtml';

async function returnToCatalogue(page: Page): Promise<void> {
  await page.goto(CATALOGUE_URL, { waitUntil: 'load' });
}

function cleanupFile(path: string): void {
  if (existsSync(path)) unlinkSync(path);
}

describe.skipIf(!RUN_E2E)('ABS TableBuilder E2E', () => {
  let browser: Browser;
  let context: BrowserContext;
  let page: Page;

  beforeAll(async () => {
    browser = await chromium.launch({ headless: true });
    context = await browser.newContext({ acceptDownloads: true });
    page = await context.newPage();

    // Log in once — all tests share this session
    const creds = loadCredentials();
    await login(page, creds);
    await acceptTerms(page);
  });

  afterAll(async () => {
    await context.close();
    await browser.close();
  });

  // ─── Test 1: Original ────────────────────────────────────────────────────

  it('fetches a 2006 Census (Usual Residence) Sex table', async () => {
    const outputPath = join('output', 'e2e-usual-residence.csv');
    try {
      const dataset = await selectDataset(page, '2006 Census Persons Usual Residence');
      expect(dataset).toContain('2006');

      await selectVariables(page, { rows: ['Sex'], columns: [] });
      await retrieveTable(page);
      const { csvPath, rowCount } = await downloadCsv(page, outputPath);

      expect(existsSync(csvPath)).toBe(true);
      expect(rowCount).toBeGreaterThan(0);
      expect(readFileSync(csvPath, 'utf-8').length).toBeGreaterThan(0);
    } finally {
      cleanupFile(outputPath);
    }
  }, 600_000);

  // ─── Test 2: Different dataset (Place of Enumeration) ────────────────────

  it('fetches a 2006 Census (Place of Enumeration) Sex table', async () => {
    const outputPath = join('output', 'e2e-enumeration.csv');
    try {
      await returnToCatalogue(page);

      const dataset = await selectDataset(page, '2006 Census Persons Enumeration');
      expect(dataset).toContain('2006');

      await selectVariables(page, { rows: ['Sex'], columns: [] });
      await retrieveTable(page);
      const { csvPath, rowCount } = await downloadCsv(page, outputPath);

      expect(existsSync(csvPath)).toBe(true);
      expect(rowCount).toBeGreaterThan(0);
    } finally {
      cleanupFile(outputPath);
    }
  }, 600_000);

  // ─── Test 3: Two variables (rows + columns) ───────────────────────────────

  it('fetches a 2006 Census table with Sex rows and Registered Marital Status columns', async () => {
    const outputPath = join('output', 'e2e-sex-by-marital-status.csv');
    try {
      await returnToCatalogue(page);

      const dataset = await selectDataset(page, '2006 Census Persons Usual Residence');
      expect(dataset).toContain('2006');

      await selectVariables(page, {
        rows: ['Sex'],
        columns: ['Registered Marital Status'],
      });
      await retrieveTable(page);
      const { csvPath, rowCount } = await downloadCsv(page, outputPath);

      expect(existsSync(csvPath)).toBe(true);
      expect(rowCount).toBeGreaterThan(0);
    } finally {
      cleanupFile(outputPath);
    }
  }, 600_000);

  // ─── Test 4: Third dataset (Place of Work) ────────────────────────────────

  it('fetches a 2006 Census (Place of Work) Sex table', async () => {
    const outputPath = join('output', 'e2e-place-of-work.csv');
    try {
      await returnToCatalogue(page);

      const dataset = await selectDataset(page, '2006 Census Persons Work');
      expect(dataset).toContain('2006');

      await selectVariables(page, { rows: ['Sex'], columns: [] });
      await retrieveTable(page);
      const { csvPath, rowCount } = await downloadCsv(page, outputPath);

      expect(existsSync(csvPath)).toBe(true);
      expect(rowCount).toBeGreaterThan(0);
    } finally {
      cleanupFile(outputPath);
    }
  }, 600_000);

  // ─── Test 5: All 7 phases fire in order ───────────────────────────────────

  it('all 7 phases fire in order and result has rowCount > 0', async () => {
    const creds = loadCredentials();
    const events: Array<{ type: string; phaseId?: string }> = [];
    const reporter = (e: PhaseEvent) => events.push(e);

    await login(page, creds, reporter, AbortSignal.timeout(300_000));
    const dataset = await selectDataset(page, 'Census 2021', reporter);
    expect(dataset).toContain('2021');

    await selectVariables(page, { rows: ['Sex'], columns: ['Age'] }, reporter);
    await retrieveTable(page, reporter);

    const OUTPUT_PATH = join('output', 'e2e-phase-test.csv');
    const { csvPath, rowCount } = await downloadCsv(page, OUTPUT_PATH, reporter);

    expect(existsSync(csvPath)).toBe(true);
    expect(rowCount).toBeGreaterThan(0);

    const EXPECTED_PHASES = ['login', 'dataset', 'tree', 'check', 'submit', 'retrieve', 'download'];
    const phaseStarts = events
      .filter(e => e.type === 'phase_start')
      .map(e => e.phaseId);
    expect(phaseStarts).toEqual(EXPECTED_PHASES);

    const phaseCompletes = events
      .filter(e => e.type === 'phase_complete')
      .map(e => e.phaseId);
    expect(new Set(phaseCompletes)).toEqual(new Set(EXPECTED_PHASES));
  }, 300_000);
});
