// src/dict-builder/scraper.ts
import type { Page } from 'playwright-core';
import type { ExtractedDataset, ExtractedGroup, ExtractedVariable } from './types.js';
import { parseVariableLabel, shouldExpandVariable } from './walker.js';

// ── Raw node shape returned by page.evaluate ────────────────────────────────

export interface RawNode {
  label: string;
  depth: number;          // counted from root container by ancestor <ul> nesting
  is_leaf: boolean;
  is_collapsed: boolean;
  has_checkbox: boolean;
}

// JS evaluated inside the page. Walks the schema tree and returns a flat
// array of raw node descriptors with accurate depth.
const TREE_EXTRACT_JS = `
(() => {
  const container = document.querySelector('#tableViewSchemaTree')
                  || document.querySelector('.treeControl');
  if (!container) return [];

  const nodes = container.querySelectorAll('.treeNodeElement');
  return Array.from(nodes).map(node => {
    const label = node.querySelector('.label');
    const expander = node.querySelector('.treeNodeExpander');
    const checkbox = node.querySelector('input[type=checkbox]');

    let depth = 0;
    let el = node.parentElement;
    while (el && el !== container) {
      if (el.tagName === 'UL') depth++;
      el = el.parentElement;
    }

    const expClass = expander ? expander.className : '';
    return {
      label: label ? (label.textContent || '').trim() : '',
      depth,
      is_leaf: expClass.includes('leaf'),
      is_collapsed: expClass.includes('collapsed'),
      has_checkbox: !!checkbox,
    };
  });
})()
`;

// ── Pure helpers ────────────────────────────────────────────────────────────

export function splitGeographyAndVariables(nodes: RawNode[]): {
  geographies: string[];
  varNodes: RawNode[];
} {
  if (nodes.length === 0) return { geographies: [], varNodes: [] };

  // Two distinct cases by page type:
  //
  // (a) CATALOGUE page — dataset names are leaf nodes after a header section
  //     of leaf nodes that have NO checkbox (those are the geographic
  //     classifications, listed once at the top before the dataset tree
  //     starts). Detect by: any leaf without a checkbox appearing before
  //     any node with a checkbox.
  //
  // (b) DATASET tableView page — the schema tree is rooted at top-level
  //     groups including "Geographical Areas (Usual Residence)" or
  //     "Geographical Areas (Place of Enumeration)". The classification
  //     names are this group's IMMEDIATE children (depth = group.depth + 1).
  //     Variables and categories live alongside in the demographic groups.
  //
  // We always return ALL nodes as varNodes for the classifier to walk. The
  // geographies_json list populates from whichever case matches.

  // Case (b): dataset schema tree
  for (let i = 0; i < nodes.length; i++) {
    if (/Geographical Areas/i.test(nodes[i].label) && !nodes[i].is_leaf) {
      const parentDepth = nodes[i].depth;
      const geos: string[] = [];
      for (let j = i + 1; j < nodes.length; j++) {
        if (nodes[j].depth <= parentDepth) break;
        if (nodes[j].depth === parentDepth + 1) geos.push(nodes[j].label);
      }
      if (geos.length > 0) return { geographies: geos, varNodes: nodes };
    }
  }

  // Case (a): catalogue page — no-checkbox leaves before first checkbox
  let firstCheckIdx = -1;
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i].has_checkbox) { firstCheckIdx = i; break; }
  }
  if (firstCheckIdx === -1) {
    return {
      geographies: nodes.filter(n => n.is_leaf).map(n => n.label),
      varNodes: [],
    };
  }
  const minDepth = Math.min(...nodes.map(n => n.depth));
  let varStartIdx = firstCheckIdx;
  for (let i = firstCheckIdx - 1; i >= 0; i--) {
    if (nodes[i].depth === minDepth) { varStartIdx = i; break; }
  }
  const geos = nodes.slice(0, varStartIdx).filter(n => n.is_leaf).map(n => n.label);
  return { geographies: geos, varNodes: nodes.slice(varStartIdx) };
}

// Split a variable label like "STRD State/Territory of Usual Residence" into
// {code: "STRD", label: "State/Territory of Usual Residence"}. The first
// whitespace-delimited token is treated as the code only if it is ALL-UPPERCASE
// (digits and underscores allowed) and ≤ 16 chars. Otherwise code is empty
// and the entire label stays as the label. Matches legacy Python behaviour
// for dataset-tree variables, which (unlike catalogue dataset names) lack a
// trailing "(N)" suffix.
function splitCodeAndLabel(raw: string): { code: string; label: string } {
  // Strip a trailing " (N)" if present — catalogue labels include the count
  // ("SEXP Sex (2)") but dataset-tree labels usually don't ("SEXP Sex").
  // Either way, the count belongs in `category_count`, not the visible label.
  const stripped = raw.replace(/\s+\(\d+\)\s*$/, '').trim();
  const idx = stripped.indexOf(' ');
  if (idx < 0) return { code: '', label: stripped };
  const candidate = stripped.slice(0, idx);
  if (candidate.length <= 16 && /^[A-Z][A-Z0-9_]*$/.test(candidate)) {
    return { code: candidate, label: stripped.slice(idx + 1).trim() };
  }
  return { code: '', label: stripped };
}

type Role = 'group' | 'variable' | 'category';

// Variables in the ABS schema tree have a stable label format: an ALL-UPPERCASE
// code (3-16 chars, digits and underscores allowed) followed by a space and the
// human-readable name. Examples: "SEXP Sex", "AGE5P Age in Five Year Groups",
// "STRD State/Territory of Usual Residence", "SA1MAIN_2021 SA1 by Main ASGS".
// Categories, classification-release groups, and structural groups don't follow
// this pattern.
//
// We previously tried structural classification (variable = non-leaf with leaf
// children) but it failed on two real cases:
//   1. Hierarchical category bins (e.g. "Postal Areas" → "New South Wales POAs"
//      → individual postcodes) were tagged as variables because they had leaf
//      grandchildren.
//   2. Variables whose categories form their OWN sub-tree (e.g. BPMP Country of
//      Birth of Father → "Asia" → "South Asia" → "India") have NO leaf children
//      at depth+1, so they were tagged as groups, and child variables ended up
//      with corrupted paths like "Cultural Diversity > BPMP > Not stated > ENGLP".
//
// Label-based classification doesn't have either problem.
// Two requirements distinguish real variable labels from classification-
// release group labels:
// 1) Code is at LEAST 4 chars. Real ABS variable codes are 4+ chars (SEXP,
//    AGEP, STRD, BPLP, LGA_2021, SA1MAIN_2021). 3-char strings like SA1, SA2,
//    LGA, POA are classification-release name prefixes — they head groups
//    like "SA1 by Main ASGS", "LGA (2021 Boundaries)", "POA Postcode" — not
//    variables.
// 2) After the code + space, the label must start with a LETTER. This
//    excludes "LGA (2021 Boundaries)" where the post-code part starts with
//    a paren.
const VAR_LABEL_FULL_RE = /^([A-Z][A-Z0-9_]{3,15})\s+[A-Za-z]/;

function classifyNodes(nodes: RawNode[]): Role[] {
  const roles: Role[] = new Array(nodes.length);
  // Pass 1: label-based — works for ABS census/social datasets that name
  // variables with code prefixes (SEXP, AGEP, STRD, …).
  let varDepth = -1;
  let labelMatchedAny = false;
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    if (varDepth >= 0 && n.depth <= varDepth) varDepth = -1;

    const looksLikeVariable = !n.is_leaf && VAR_LABEL_FULL_RE.test(n.label);

    if (looksLikeVariable) {
      roles[i] = 'variable';
      varDepth = n.depth;
      labelMatchedAny = true;
    } else if (varDepth >= 0) {
      roles[i] = 'category';
    } else {
      roles[i] = n.is_leaf ? 'category' : 'group';
    }
  }
  if (labelMatchedAny) return roles;

  // Pass 2 (fallback): structural — for datasets with plain-English variable
  // labels (e.g. Motor Vehicle Use, Crime Victimisation surveys). A non-leaf
  // is a variable when its IMMEDIATE depth+1 children are leaves; otherwise
  // it's a structural group. Only kicks in when label-based finds NOTHING in
  // the entire tree, so it can't regress census datasets where hierarchical
  // category bins (Postal Areas → state buckets → postcodes) live alongside
  // real code-prefixed variables.
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    if (n.is_leaf) { roles[i] = 'category'; continue; }
    let hasLeafChild = false;
    for (let j = i + 1; j < nodes.length; j++) {
      if (nodes[j].depth <= n.depth) break;
      if (nodes[j].depth === n.depth + 1 && nodes[j].is_leaf) { hasLeafChild = true; break; }
    }
    roles[i] = hasLeafChild ? 'variable' : 'group';
  }
  return roles;
}

// Count the IMMEDIATE children of a non-leaf node (the "category buckets" of a
// variable, leaf or non-leaf). For the >100 threshold we count direct children,
// not all descendants — a postcode-style variable with 9 state buckets each
// containing thousands of leaves is best summarised as 9 categories.
function countDirectChildren(nodes: RawNode[], i: number): number {
  const parent = nodes[i];
  let count = 0;
  for (let j = i + 1; j < nodes.length; j++) {
    if (nodes[j].depth <= parent.depth) break;
    if (nodes[j].depth === parent.depth + 1) count++;
  }
  return count;
}

export function classifyAndBuildGroups(
  varNodes: RawNode[],
  _warn: (msg: string) => void,
): ExtractedGroup[] {
  if (varNodes.length === 0) return [];

  const roles = classifyNodes(varNodes);
  const groups: ExtractedGroup[] = [];
  const groupStack: Map<number, string> = new Map();
  let currentGroup: ExtractedGroup | null = null;
  let currentVar: ExtractedVariable | null = null;
  let currentVarDepth = -1;
  let captureCategories = false;
  let lastPath = '';

  const flushVar = () => {
    if (currentVar && currentGroup) {
      currentGroup.variables.push(currentVar);
      currentVar = null;
    }
    captureCategories = false;
  };
  const flushGroup = () => {
    flushVar();
    if (currentGroup && currentGroup.variables.length > 0) groups.push(currentGroup);
    currentGroup = null;
  };

  for (let i = 0; i < varNodes.length; i++) {
    const node = varNodes[i];
    const role = roles[i];

    if (role === 'group') {
      // Update the path stack to this depth and emit a new group if it changed
      groupStack.set(node.depth, node.label);
      for (const d of [...groupStack.keys()]) {
        if (d > node.depth) groupStack.delete(d);
      }
      const path = [...groupStack.keys()].sort((a, b) => a - b)
        .map(d => groupStack.get(d)!)
        .join(' > ');
      if (path !== lastPath) {
        flushGroup();
        currentGroup = { label: node.label, path, variables: [] };
        lastPath = path;
      }
    } else if (role === 'variable') {
      flushVar();
      // Variables can appear at any depth (e.g. STRD at depth 2 directly under
      // "Geographical Areas"), with or without a parent group. Synthesise an
      // (ungrouped) bucket if we don't have one yet.
      if (currentGroup === null) {
        currentGroup = { label: '(ungrouped)', path: '(ungrouped)', variables: [] };
        lastPath = '(ungrouped)';
      }
      const { code, label } = splitCodeAndLabel(node.label);
      const childCount = countDirectChildren(varNodes, i);
      currentVar = {
        code,
        label,
        category_count: childCount,
        categories: [],
      };
      currentVarDepth = node.depth;
      captureCategories = shouldExpandVariable(childCount);
    } else if (role === 'category') {
      // Only capture immediate (depth = varDepth + 1) children. Deeper nodes
      // are sub-categories of categories — they'd duplicate or pollute the
      // category list (e.g. BPMP Country of Birth → "Asia" → "India" → "Mumbai"
      // — only "Asia" belongs in the variable's category list).
      if (currentVar && captureCategories && node.depth === currentVarDepth + 1) {
        currentVar.categories.push(node.label);
      }
    }
  }

  flushGroup();
  return groups;
}

// ── Playwright entry point ──────────────────────────────────────────────────

async function fetchRawTree(page: Page): Promise<RawNode[]> {
  return await page.evaluate(TREE_EXTRACT_JS) as RawNode[];
}

// Maximum tree depth to expand into. Variables we care about live at depth
// 1-3 (top-level group → optional sub-group → variable). Beyond that we're
// walking the geographic regional hierarchy (Greater Sydney → Eastern Suburbs
// → ... → SA1 codes) which has nothing useful for a dictionary — those leaves
// are categories of variables we already captured at depth 2 or 3.
export const MAX_EXPAND_DEPTH = 3;

async function expandTreeForExtraction(page: Page): Promise<void> {
  // Expand collapsed nodes that are: (a) at depth <= MAX_EXPAND_DEPTH, and (b)
  // either a group (no variable pattern in label) OR a variable with
  // category_count <= 100.
  //
  // CRITICAL: re-fetch the raw tree after EVERY click. Earlier versions used
  // a per-round fetch and a `for i in nodes` click loop with `locator(...).nth(i)`
  // — but `.nth(i)` re-evaluates against the live DOM, so once an earlier click
  // expanded a node and inserted children, the nth(i) handle pointed at a
  // different element than `nodes[i]`. The classic symptom: a click meant for
  // a small group accidentally hit a large variable's expander, exploding the
  // tree from ~600 nodes to ~7000 in one round.
  //
  // Per-click fetch is slower (≈100 ms × N nodes per round) but correct: the
  // nth-index is always valid for THIS click because no other clicks have
  // happened since the fetch.
  //
  // Termination: deadline (10 min), iteration cap (1000 clicks safety net),
  // or "tried this label at this depth before" (skip — node either expanded
  // and lost its `.collapsed` class or click failed unrecoverably).
  const deadline = Date.now() + 10 * 60 * 1000;
  const triedKeys = new Set<string>();
  let round = 0;
  let lastNodeCount = -1;

  for (let click = 0; click < 1000; click++) {
    if (Date.now() > deadline) {
      console.warn(`expandTreeForExtraction: deadline exceeded after ${click} clicks`);
      break;
    }
    const nodes = await fetchRawTree(page);

    // Round-style log when the tree size changes meaningfully
    if (nodes.length !== lastNodeCount) {
      const remaining = nodes.filter(n => {
        if (!n.is_collapsed) return false;
        if (n.depth > MAX_EXPAND_DEPTH) return false;
        const p = parseVariableLabel(n.label);
        if (p && !shouldExpandVariable(p.category_count)) return false;
        return !triedKeys.has(`${n.depth}:${n.label}`);
      }).length;
      console.log(`expandTreeForExtraction: round ${round++}, ${nodes.length} nodes, ${remaining} to expand`);
      lastNodeCount = nodes.length;
    }

    // Find the first eligible-and-untried collapsed node
    let targetIdx = -1;
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      if (!n.is_collapsed) continue;
      if (n.depth > MAX_EXPAND_DEPTH) continue;
      const parsed = parseVariableLabel(n.label);
      if (parsed && !shouldExpandVariable(parsed.category_count)) continue;
      const key = `${n.depth}:${n.label}`;
      if (triedKeys.has(key)) continue;
      targetIdx = i;
      triedKeys.add(key);
      break;
    }
    if (targetIdx === -1) break;

    // Click using nth(targetIdx) — this is safe because we just fetched the
    // tree and no other Playwright actions have happened since.
    const expander = page.locator('.treeNodeElement').nth(targetIdx).locator('.treeNodeExpander').first();
    try {
      await expander.click({ timeout: 10000 });
      await new Promise(r => setTimeout(r, 300));
    } catch { /* skip — already added to triedKeys, won't retry */ }
  }
}

export async function extract(page: Page, datasetName: string): Promise<ExtractedDataset> {
  await page.waitForSelector('.treeNodeElement', { timeout: 30000 }).catch(() => null);
  await expandTreeForExtraction(page);
  const raw = await fetchRawTree(page);
  const mid = Math.floor(raw.length / 2);
  console.log(`[extract] raw nodes: ${raw.length}`);
  console.log(`[extract] first 3:`, JSON.stringify(raw.slice(0, 3)));
  console.log(`[extract] mid (${mid}-${mid+3}):`, JSON.stringify(raw.slice(mid, mid + 3)));
  console.log(`[extract] last 3:`, JSON.stringify(raw.slice(-3)));
  const { geographies, varNodes } = splitGeographyAndVariables(raw);
  console.log(`[extract] geographies: ${geographies.length}, varNodes: ${varNodes.length}`);
  const groups = classifyAndBuildGroups(varNodes, msg => console.warn(`[${datasetName}] ${msg}`));
  return {
    dataset_name: datasetName,
    geographies,
    groups,
    scraped_at: new Date().toISOString(),
    tree_node_count: raw.length,
  };
}
