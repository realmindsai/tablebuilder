// src/dict-builder/walker.test.ts
import { describe, it, expect } from 'vitest';
import {
  parseVariableLabel,
  isVariableLabel,
  slugify,
  shouldExpandVariable,
  CATEGORY_THRESHOLD,
} from './walker.js';

describe('parseVariableLabel', () => {
  it('parses standard CODE Label (N) format', () => {
    expect(parseVariableLabel('STRD State/Territory (9)')).toEqual({
      code: 'STRD',
      label: 'State/Territory',
      category_count: 9,
    });
  });

  it('parses codes with underscores (real ABS uses these)', () => {
    expect(parseVariableLabel('SA1MAIN_2021 SA1 by Main Statistical Area Structure (61845)')).toEqual({
      code: 'SA1MAIN_2021',
      label: 'SA1 by Main Statistical Area Structure',
      category_count: 61845,
    });
  });

  it('parses codes with digits in the middle', () => {
    expect(parseVariableLabel('AGE10P Age in Ten Year Groups (11)')).toEqual({
      code: 'AGE10P',
      label: 'Age in Ten Year Groups',
      category_count: 11,
    });
  });

  it('parses labels with parentheses inside', () => {
    expect(parseVariableLabel('TENLLD Tenure (Landlord Type) (8)')).toEqual({
      code: 'TENLLD',
      label: 'Tenure (Landlord Type)',
      category_count: 8,
    });
  });

  it('returns null for non-variable labels', () => {
    expect(parseVariableLabel('Selected Person Characteristics')).toBeNull();
    expect(parseVariableLabel('Geographical Areas (Usual Residence)')).toBeNull();
    expect(parseVariableLabel('LGA (2021 Boundaries)')).toBeNull();
    expect(parseVariableLabel('IFAGEP')).toBeNull();
    expect(parseVariableLabel('')).toBeNull();
  });
});

describe('isVariableLabel', () => {
  it('mirrors parseVariableLabel boolean result', () => {
    expect(isVariableLabel('STRD State/Territory (9)')).toBe(true);
    expect(isVariableLabel('Cultural Diversity')).toBe(false);
  });
});

describe('slugify', () => {
  it('lowercases, replaces non-alphanumeric with underscore, trims', () => {
    expect(slugify('2021 Census - counting persons, place of usual residence'))
      .toBe('2021_census_counting_persons_place_of_usual_residence');
  });

  it('collapses multiple non-alphanumeric runs into a single underscore', () => {
    expect(slugify('Foo --- Bar,, Baz')).toBe('foo_bar_baz');
  });

  it('caps at 80 chars', () => {
    const long = 'a'.repeat(120);
    expect(slugify(long).length).toBe(80);
  });

  it('strips leading and trailing underscores after substitution', () => {
    expect(slugify(' (Survey) ')).toBe('survey');
  });
});

describe('shouldExpandVariable', () => {
  it('expands variables with <= 100 categories', () => {
    expect(shouldExpandVariable(0)).toBe(true);
    expect(shouldExpandVariable(1)).toBe(true);
    expect(shouldExpandVariable(100)).toBe(true);
  });

  it('does not expand variables with > 100 categories', () => {
    expect(shouldExpandVariable(101)).toBe(false);
    expect(shouldExpandVariable(61845)).toBe(false);
  });

  it('exposes the threshold constant', () => {
    expect(CATEGORY_THRESHOLD).toBe(100);
  });
});
