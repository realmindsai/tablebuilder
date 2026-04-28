/**
 * Source-level regression checks for the runner-UI ↔ dictionary.db integration.
 *
 * These are lightweight string-matching guards that prevent the original picker
 * bugs from creeping back in. Browser-level UI coverage (real picker behavior,
 * geography dropdown population, browse modal) is verified manually via
 * Task 14's deployment smoketest, since the JSX-no-build UI doesn't have a
 * Playwright harness wired up.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

const ROOT = join(__dirname, '..');

describe('UI regression: variable picker', () => {
  it('form.jsx does not contain slice(0, 7) (the original 7-cap bug)', () => {
    const text = readFileSync(join(ROOT, 'ui/form.jsx'), 'utf8');
    expect(text).not.toMatch(/slice\(0,\s*7\)/);
  });

  it('data.js does not define a hardcoded VARIABLES list', () => {
    const text = readFileSync(join(ROOT, 'ui/data.js'), 'utf8');
    expect(text).not.toMatch(/^const VARIABLES\s*=/m);
    expect(text).not.toMatch(/window\.VARIABLES\s*=/);
  });

  it('no UI file references window.VARIABLES (it must be gone, not just hidden)', () => {
    for (const f of ['ui/form.jsx', 'ui/app.jsx', 'ui/run.jsx', 'ui/applyEvent.js']) {
      const text = readFileSync(join(ROOT, f), 'utf8');
      expect(text, `${f} still references window.VARIABLES`).not.toMatch(/window\.VARIABLES/);
    }
  });
});

describe('UI regression: dataset-store + browse modal', () => {
  it('ui/dataset-store.js exists and exposes window.DatasetStore', () => {
    const path = join(ROOT, 'ui/dataset-store.js');
    expect(existsSync(path)).toBe(true);
    const text = readFileSync(path, 'utf8');
    expect(text).toMatch(/window\.DatasetStore/);
    expect(text).toMatch(/loadMetadata/);
  });

  it('ui/browse-modal.jsx exists and exposes window.BrowseModal', () => {
    const path = join(ROOT, 'ui/browse-modal.jsx');
    expect(existsSync(path)).toBe(true);
    const text = readFileSync(path, 'utf8');
    expect(text).toMatch(/window\.BrowseModal/);
  });

  it('index.html loads dataset-store.js and browse-modal.jsx', () => {
    const text = readFileSync(join(ROOT, 'ui/index.html'), 'utf8');
    expect(text).toMatch(/<script[^>]+src=["']dataset-store\.js["']/);
    expect(text).toMatch(/<script[^>]+src=["']browse-modal\.jsx["']/);
  });
});

describe('UI regression: phase list', () => {
  it('PHASES in data.js includes a geography step', () => {
    const text = readFileSync(join(ROOT, 'ui/data.js'), 'utf8');
    expect(text).toMatch(/id:\s*["']geography["']/);
  });

  it('PHASE_INDEX in applyEvent.js maps geography to 2 (between dataset and tree)', () => {
    const text = readFileSync(join(ROOT, 'ui/applyEvent.js'), 'utf8');
    expect(text).toMatch(/geography:\s*2/);
    expect(text).toMatch(/tree:\s*3/);
  });
});
