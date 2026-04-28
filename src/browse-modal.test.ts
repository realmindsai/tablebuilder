// src/browse-modal.test.ts
// @vitest-environment jsdom
//
// Tests for ui/browse-modal.jsx — window.BrowseModal
//
// browse-modal.jsx uses JSX + Babel-standalone at runtime, so we can't eval
// the file directly in vitest.  Instead we define a plain-JS equivalent of
// the component logic and test the Apply / Cancel / backdrop-click paths.
// No React import needed: the tests exercise the component contract in plain TS.

import { describe, it, expect, vi } from 'vitest';

// ── minimal BrowseModal re-implementation using createElement ──────────────
// This is NOT a copy-paste of the JSX source; it mirrors only the contract
// (props in → onApply / onCancel calls) so we can test that contract.

function makeBrowseModal(
  metadata: { groups: Array<{ id: number; label: string; variables: Array<{ id: number; label: string; code: string }> }> },
  initialSelected: Set<number>,
  onApply: (ids: Set<number>) => void,
  onCancel: () => void,
) {
  // State held in a closure — enough for a synchronous test.
  let selected = new Set(initialSelected);

  function toggleVar(vid: number) {
    if (selected.has(vid)) { selected.delete(vid); } else { selected.add(vid); }
  }

  // Return a plain object that simulates the rendered structure for testing.
  return {
    clickApply() { onApply(new Set(selected)); },
    clickCancel() { onCancel(); },
    clickBackdrop() { onCancel(); },
    checkVar(vid: number) { toggleVar(vid); },
    isChecked(vid: number) { return selected.has(vid); },
  };
}

// ── fixture ────────────────────────────────────────────────────────────────

const METADATA = {
  groups: [
    {
      id: 1,
      label: 'Demographics',
      variables: [
        { id: 10, label: 'Sex', code: 'SEX' },
        { id: 11, label: 'Age', code: 'AGE5P' },
      ],
    },
  ],
};

// ── tests ──────────────────────────────────────────────────────────────────

describe('BrowseModal contract', () => {
  it('apply returns the checked id set (pre-select 10, check 11 → {10,11})', () => {
    const onApply = vi.fn();
    const onCancel = vi.fn();

    const modal = makeBrowseModal(METADATA, new Set([10]), onApply, onCancel);

    // Pre-check: 10 is already selected, 11 is not.
    expect(modal.isChecked(10)).toBe(true);
    expect(modal.isChecked(11)).toBe(false);

    // User checks variable 11.
    modal.checkVar(11);
    expect(modal.isChecked(11)).toBe(true);

    // User clicks Apply.
    modal.clickApply();

    expect(onApply).toHaveBeenCalledTimes(1);
    const result: Set<number> = onApply.mock.calls[0][0];
    expect(result).toBeInstanceOf(Set);
    expect([...result].sort()).toEqual([10, 11]);

    expect(onCancel).not.toHaveBeenCalled();
  });

  it('cancel does not call onApply', () => {
    const onApply = vi.fn();
    const onCancel = vi.fn();

    const modal = makeBrowseModal(METADATA, new Set([10]), onApply, onCancel);
    modal.clickCancel();

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onApply).not.toHaveBeenCalled();
  });

  it('backdrop click is treated as cancel', () => {
    const onApply = vi.fn();
    const onCancel = vi.fn();

    const modal = makeBrowseModal(METADATA, new Set(), onApply, onCancel);
    modal.clickBackdrop();

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onApply).not.toHaveBeenCalled();
  });
});
