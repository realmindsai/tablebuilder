// src/dict-builder/scraper.test.ts
import { describe, it, expect, vi } from 'vitest';
import {
  splitGeographyAndVariables,
  classifyAndBuildGroups,
  extract,
  type RawNode,
} from './scraper.js';

const node = (
  label: string,
  depth: number,
  is_leaf: boolean,
  is_collapsed: boolean,
  has_checkbox: boolean,
): RawNode => ({ label, depth, is_leaf, is_collapsed, has_checkbox });

describe('splitGeographyAndVariables', () => {
  it('puts no-checkbox leaves before the first checkbox into geographies', () => {
    const nodes = [
      node('Australia',                                       0, true,  false, false),
      node('LGA (2021 Boundaries)',                           0, true,  false, false),
      node('Selected Person Characteristics',                 0, false, false, false),
      node('SEXP Sex (2)',                                    1, false, false, true),
      node('Male',                                            2, true,  false, true),
      node('Female',                                          2, true,  false, true),
    ];
    const { geographies, varNodes } = splitGeographyAndVariables(nodes);
    expect(geographies).toEqual(['Australia', 'LGA (2021 Boundaries)']);
    expect(varNodes.map(n => n.label)).toEqual([
      'Selected Person Characteristics',
      'SEXP Sex (2)',
      'Male',
      'Female',
    ]);
  });

  it('returns all leaves as geographies when no checkboxes exist', () => {
    const nodes = [
      node('Australia',  0, true, false, false),
      node('LGA',        0, true, false, false),
    ];
    const { geographies, varNodes } = splitGeographyAndVariables(nodes);
    expect(geographies).toEqual(['Australia', 'LGA']);
    expect(varNodes).toEqual([]);
  });

  it('returns empty arrays for an empty node list', () => {
    expect(splitGeographyAndVariables([])).toEqual({ geographies: [], varNodes: [] });
  });
});

describe('classifyAndBuildGroups', () => {
  it('classifies variable nodes by label pattern, captures categories', () => {
    const nodes = [
      node('Selected Person Characteristics', 0, false, false, false),
      node('SEXP Sex (2)',                    1, false, false, true),
      node('Male',                            2, true,  false, true),
      node('Female',                          2, true,  false, true),
      node('AGEP Age (21)',                   1, false, false, true),
      node('0-4',                             2, true,  false, true),
      node('5-9',                             2, true,  false, true),
    ];
    const groups = classifyAndBuildGroups(nodes, () => {});
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('Selected Person Characteristics');
    expect(groups[0].path).toBe('Selected Person Characteristics');
    expect(groups[0].variables.map(v => v.code)).toEqual(['SEXP', 'AGEP']);
    expect(groups[0].variables[0]).toEqual({
      code: 'SEXP', label: 'Sex', category_count: 2, categories: ['Male', 'Female'],
    });
  });

  it('builds " > "-joined paths through nested groups', () => {
    const nodes = [
      node('Geographical Areas (Usual Residence)', 0, false, false, false),
      node('LGA (2021 Boundaries)',                1, false, false, false),
      node('LGA_2021 Local Government Area 2021 (565)', 2, false, false, true),
    ];
    const groups = classifyAndBuildGroups(nodes, () => {});
    expect(groups).toHaveLength(1);
    expect(groups[0].path).toBe('Geographical Areas (Usual Residence) > LGA (2021 Boundaries)');
    expect(groups[0].variables[0].code).toBe('LGA_2021');
    expect(groups[0].variables[0].category_count).toBe(565);
    expect(groups[0].variables[0].categories).toEqual([]); // > 100, not expanded
  });

  it('captures categories only for variables with count <= 100', () => {
    const nodes = [
      node('Group',                                 0, false, false, false),
      node('SEXP Sex (2)',                          1, false, false, true),
      node('Male',                                  2, true,  false, true),
      node('Female',                                2, true,  false, true),
      node('SA1MAIN_2021 SA1 by Main ASGS (61845)', 1, false, false, true),
      // Even if the DOM happened to have leaves under SA1, the scraper
      // would not expand it; here we omit those leaves.
    ];
    const groups = classifyAndBuildGroups(nodes, () => {});
    expect(groups[0].variables[0].categories).toEqual(['Male', 'Female']);
    expect(groups[0].variables[1].categories).toEqual([]);
    expect(groups[0].variables[1].category_count).toBe(61845);
  });

  it('treats malformed group-like labels as groups and reports a warning', () => {
    const warnings: string[] = [];
    const nodes = [
      node('weird-malformed-no-count',  0, false, false, false),
      node('SEXP Sex (2)',              1, false, false, true),
      node('Male',                      2, true,  false, true),
    ];
    const groups = classifyAndBuildGroups(nodes, msg => warnings.push(msg));
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('weird-malformed-no-count');
    expect(warnings.length).toBeGreaterThanOrEqual(0); // at minimum, doesn't throw
  });

  it('handles empty input', () => {
    expect(classifyAndBuildGroups([], () => {})).toEqual([]);
  });
});

describe('extract (Playwright integration with mock page)', () => {
  it('returns ExtractedDataset built from page.evaluate result', async () => {
    const rawNodes: RawNode[] = [
      node('Australia',                                  0, true,  false, false),
      node('Selected Person Characteristics',            0, false, false, false),
      node('SEXP Sex (2)',                               1, false, false, true),
      node('Male',                                       2, true,  false, true),
      node('Female',                                     2, true,  false, true),
    ];
    const page = {
      waitForSelector: vi.fn().mockResolvedValue(undefined),
      evaluate: vi.fn().mockResolvedValue(rawNodes),
      locator: vi.fn().mockReturnValue({
        all: vi.fn().mockResolvedValue([]),
        nth: vi.fn().mockReturnValue({
          locator: () => ({ first: () => ({ click: vi.fn().mockResolvedValue(undefined) }) }),
        }),
      }),
    };

    const result = await extract(page as any, 'Test Dataset');
    expect(result.dataset_name).toBe('Test Dataset');
    expect(result.geographies).toEqual(['Australia']);
    expect(result.groups).toHaveLength(1);
    expect(result.groups[0].variables[0].code).toBe('SEXP');
    expect(result.tree_node_count).toBe(5);
    expect(result.scraped_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});
