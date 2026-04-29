// src/shared/abs/instrumentation.test.ts
import { describe, it, expect, vi } from 'vitest';
import type { Page } from 'playwright-core';
import type { PhaseEvent } from './reporter.js';

function collectReporter(): { events: PhaseEvent[]; reporter: (e: PhaseEvent) => void } {
  const events: PhaseEvent[] = [];
  return { events, reporter: (e) => events.push(e) };
}

// ── auth.ts ──────────────────────────────────────────────────────────────────

describe('login — reporter events', () => {
  function makeMockPage(finalUrl = 'https://tablebuilder.abs.gov.au/dataCatalogueExplorer.xhtml'): Page {
    return {
      goto: vi.fn().mockResolvedValue(null),
      fill: vi.fn().mockResolvedValue(undefined),
      click: vi.fn().mockResolvedValue(undefined),
      waitForURL: vi.fn().mockResolvedValue(undefined),
      url: vi.fn().mockReturnValue(finalUrl),
    } as unknown as Page;
  }

  it('emits phase_start login before phase_complete login', async () => {
    const { events, reporter } = collectReporter();
    const { login } = await import('./auth.js');
    await login(makeMockPage(), { userId: 'u', password: 'p' }, reporter);
    const starts = events.filter(e => e.type === 'phase_start').map(e => (e as { phaseId: string }).phaseId);
    const completes = events.filter(e => e.type === 'phase_complete').map(e => (e as { phaseId: string }).phaseId);
    expect(starts).toContain('login');
    expect(completes).toContain('login');
    expect(events.findIndex(e => e.type === 'phase_start')).toBeLessThan(events.findIndex(e => e.type === 'phase_complete'));
  });
});

// ── navigator.ts ─────────────────────────────────────────────────────────────

describe('selectDataset — reporter events', () => {
  it('emits phase_start dataset and phase_complete dataset', async () => {
    const { events, reporter } = collectReporter();
    const { selectDataset } = await import('./navigator.js');

    const DATASET_NAME = 'Census 2021 Persons Usual Residence';

    const mockLeafExpander = { getAttribute: vi.fn().mockResolvedValue('treeNodeExpander leaf') };
    const mockLeafLabelEl = { textContent: vi.fn().mockResolvedValue(DATASET_NAME) };
    const mockLeafNode = {
      locator: vi.fn().mockImplementation((sel: string) =>
        sel.includes('treeNodeExpander') ? { first: () => mockLeafExpander } : { first: () => mockLeafLabelEl }
      ),
    };

    const mockTargetLabel = {
      textContent: vi.fn().mockResolvedValue(DATASET_NAME),
      dblclick: vi.fn().mockResolvedValue(undefined),
    };

    const page = {
      waitForSelector: vi.fn().mockResolvedValue(null),
      waitForURL: vi.fn().mockResolvedValue(undefined),
      url: vi.fn().mockReturnValue('https://tablebuilder.abs.gov.au/tableView.xhtml'),
      evaluate: vi.fn().mockResolvedValue(null),
      locator: vi.fn().mockImplementation((sel: string) => {
        if (sel === '.treeNodeElement .label') return { all: vi.fn().mockResolvedValue([mockTargetLabel]) };
        if (sel === '.treeNodeExpander.collapsed') return { all: vi.fn().mockResolvedValue([]) };
        if (sel === '.treeNodeElement') return {
          all: vi.fn().mockResolvedValue([mockLeafNode]),
          count: vi.fn().mockResolvedValue(1),
        };
        // Force selectDataset's header-search fast path to bail out at the
        // first check (count=0) so the test exercises the slow-path fallback
        // the rest of this mock is wired for.
        if (sel.includes('headerSearchForm') || sel.includes('searchResultTable')) return {
          count: vi.fn().mockResolvedValue(0),
          first: () => ({ count: vi.fn().mockResolvedValue(0), click: vi.fn().mockResolvedValue(undefined) }),
        };
        return { all: vi.fn().mockResolvedValue([]), count: vi.fn().mockResolvedValue(0) };
      }),
    } as unknown as Page;

    await selectDataset(page, 'Census 2021', reporter);

    const starts = events.filter(e => e.type === 'phase_start').map(e => (e as { phaseId: string }).phaseId);
    const completes = events.filter(e => e.type === 'phase_complete').map(e => (e as { phaseId: string }).phaseId);
    expect(starts).toContain('dataset');
    expect(completes).toContain('dataset');
  });
});

// ── jsf.ts ────────────────────────────────────────────────────────────────────

describe('retrieveTable — reporter events', () => {
  it('emits phase_start retrieve and phase_complete retrieve', async () => {
    const { events, reporter } = collectReporter();
    const { retrieveTable } = await import('./jsf.js');

    const page = {
      locator: vi.fn().mockReturnValue({
        count: vi.fn().mockResolvedValue(0),
        click: vi.fn().mockResolvedValue(undefined),
      }),
      selectOption: vi.fn().mockResolvedValue(undefined),
      waitForSelector: vi.fn().mockResolvedValue(null),
    } as unknown as Page;

    await retrieveTable(page, reporter);

    const starts = events.filter(e => e.type === 'phase_start').map(e => (e as { phaseId: string }).phaseId);
    const completes = events.filter(e => e.type === 'phase_complete').map(e => (e as { phaseId: string }).phaseId);
    expect(starts).toContain('retrieve');
    expect(completes).toContain('retrieve');
  });
});
