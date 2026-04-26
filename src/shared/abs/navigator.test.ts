// src/shared/abs/navigator.test.ts
import { describe, it, expect } from 'vitest';
import { fuzzyMatchDataset } from './navigator.js';

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
