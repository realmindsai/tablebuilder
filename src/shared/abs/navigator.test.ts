// src/shared/abs/navigator.test.ts
import { describe, it, expect, vi } from 'vitest';
import { fuzzyMatchDataset, expandVariableGroups } from './navigator.js';

const AVAILABLE = [
  'Census of Population and Housing 2021',
  'Census of Population and Housing 2016',
  'Employee Earnings and Hours 2023',
];

describe('fuzzyMatchDataset', () => {
  it('exact match returns same string', () => {
    expect(fuzzyMatchDataset('Census of Population and Housing 2021', AVAILABLE))
      .toBe('Census of Population and Housing 2021');
  });

  it('case-insensitive match', () => {
    expect(fuzzyMatchDataset('census of population and housing 2021', AVAILABLE))
      .toBe('Census of Population and Housing 2021');
  });

  it('word substring match — all query words must appear', () => {
    expect(fuzzyMatchDataset('earnings hours 2023', AVAILABLE))
      .toBe('Employee Earnings and Hours 2023');
  });

  it('year-tolerant match picks dataset with closest year', () => {
    expect(fuzzyMatchDataset('census 2022', AVAILABLE))
      .toBe('Census of Population and Housing 2021');
  });

  it('throws with "No dataset matching" when no match', () => {
    expect(() => fuzzyMatchDataset('xyz nonsense', AVAILABLE))
      .toThrow('No dataset matching');
  });

  it('error message includes available dataset names', () => {
    expect(() => fuzzyMatchDataset('xyz', AVAILABLE))
      .toThrow('Census of Population');
  });
});

// ── Helpers to build mock Playwright nodes ───────────────────────────────────

function makeNode(label: string, expanderCls: string) {
  const clickFn = vi.fn().mockResolvedValue(undefined);
  return {
    locator: (sel: string) => {
      if (sel === '.label') {
        return { first: () => ({ textContent: vi.fn().mockResolvedValue(label) }) };
      }
      // '.treeNodeExpander'
      return {
        first: () => ({
          getAttribute: vi.fn().mockResolvedValue(expanderCls),
          click: clickFn,
        }),
      };
    },
    _click: clickFn,
  };
}

// makePage returns a stable locator object so spies on .all and .count
// are the same references that expandVariableGroups calls internally.
function makePage(nodes: ReturnType<typeof makeNode>[]) {
  const allFn = vi.fn().mockResolvedValue(nodes);
  const countFn = vi.fn().mockResolvedValue(nodes.length);
  const stableLocator = { all: allFn, count: countFn };
  return {
    locator: (_sel: string) => stableLocator,
    // waitForSelector resolves immediately — nodes are "already present" in mock land
    waitForSelector: vi.fn().mockResolvedValue(undefined),
    _allFn: allFn,
  };
}

const noopReporter = () => {};

describe('expandVariableGroups', () => {
  it('clicks collapsed non-skip non-variable group nodes', async () => {
    const collapsed = makeNode('Demographic Characteristics', 'collapsed');
    const expanded = makeNode('Dwelling Characteristics', 'expanded');
    const page = makePage([collapsed, expanded]);

    await expandVariableGroups(page as any, noopReporter, new AbortController().signal);

    expect(collapsed._click).toHaveBeenCalledOnce();
    expect(expanded._click).not.toHaveBeenCalled();
  });

  it('does not click collapsed nodes in SKIP_GROUPS', async () => {
    const geo   = makeNode('Geographical Areas (Usual Residence)', 'collapsed');
    const seifa = makeNode('SEIFA Index 2021', 'collapsed');
    const saved = makeNode('My Saved Tables', 'collapsed');
    const page  = makePage([geo, seifa, saved]);

    await expandVariableGroups(page as any, noopReporter, new AbortController().signal);

    // Geographic group is skipped by expandVariableGroups — tryExpandGeographic
    // handles it surgically inside checkVariableCategories when needed.
    expect(geo._click).not.toHaveBeenCalled();
    expect(seifa._click).not.toHaveBeenCalled();
    expect(saved._click).not.toHaveBeenCalled();
  });

  it('does not click variable-level nodes (matching isVarNode pattern)', async () => {
    // Variable nodes look like "SEXP Sex (2)" — matched by isVarNode
    const varNode = makeNode('SEXP Sex (2)', 'collapsed');
    const page = makePage([varNode]);

    await expandVariableGroups(page as any, noopReporter, new AbortController().signal);

    expect(varNode._click).not.toHaveBeenCalled();
  });

  it('breaks after a round with no new expansions', async () => {
    // All nodes already expanded — anyExpanded stays false → loop breaks after round 0
    const expanded = makeNode('Demographic Characteristics', 'expanded');
    const page = makePage([expanded]);

    await expandVariableGroups(page as any, noopReporter, new AbortController().signal);

    // _allFn is the spy for .all() only. makePage's stableLocator also has a separate
    // countFn spy for .count() — both share the same locator object but are distinct spies.
    // .all() is called exactly once (round 0 only — loop breaks immediately after no expansions).
    expect(page._allFn).toHaveBeenCalledTimes(1);
  });

  it('throws CancelledError when signal is aborted', async () => {
    const node = makeNode('Demographic Characteristics', 'collapsed');
    const page = makePage([node]);
    const ac = new AbortController();
    ac.abort();

    await expect(
      expandVariableGroups(page as any, noopReporter, ac.signal)
    ).rejects.toThrow('cancelled');
  });
});
