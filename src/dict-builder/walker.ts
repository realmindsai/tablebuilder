// src/dict-builder/walker.ts

// Variable labels in the ABS schema tree match: CODE LABEL (N)
// where CODE is uppercase + digits + underscores (>= 3 chars total).
// LABEL can contain anything (including inner parens) — the trailing
// "(\d+)" must be the LAST parenthesised group.
const VAR_LABEL_RE = /^([A-Z][A-Z0-9_]{2,})\s+(.+)\s+\((\d+)\)\s*$/;

export interface ParsedVariableLabel {
  code: string;
  label: string;
  category_count: number;
}

export function parseVariableLabel(raw: string): ParsedVariableLabel | null {
  const m = raw.match(VAR_LABEL_RE);
  if (!m) return null;
  return {
    code: m[1],
    label: m[2].trim(),
    category_count: parseInt(m[3], 10),
  };
}

export function isVariableLabel(raw: string): boolean {
  return VAR_LABEL_RE.test(raw);
}

export const SLUG_MAX = 80;

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, SLUG_MAX);
}

export const CATEGORY_THRESHOLD = 100;

export function shouldExpandVariable(category_count: number): boolean {
  return category_count <= CATEGORY_THRESHOLD;
}
