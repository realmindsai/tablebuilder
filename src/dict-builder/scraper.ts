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

export function classifyAndBuildGroups(
  varNodes: RawNode[],
  warn: (msg: string) => void,
): ExtractedGroup[] {
  if (varNodes.length === 0) return [];

  const groups: ExtractedGroup[] = [];
  const groupStack: Map<number, string> = new Map();
  let currentGroup: ExtractedGroup | null = null;
  let currentVar: ExtractedVariable | null = null;
  let lastPath = '';

  const flushVar = () => {
    if (currentVar && currentGroup) {
      currentGroup.variables.push(currentVar);
      currentVar = null;
    }
  };
  const flushGroup = () => {
    flushVar();
    if (currentGroup && currentGroup.variables.length > 0) groups.push(currentGroup);
    currentGroup = null;
  };

  for (const node of varNodes) {
    const parsed = parseVariableLabel(node.label);

    if (parsed) {
      // VARIABLE
      flushVar();
      if (currentGroup === null) {
        currentGroup = { label: '(ungrouped)', path: '(ungrouped)', variables: [] };
        lastPath = '(ungrouped)';
      }
      currentVar = {
        code: parsed.code,
        label: parsed.label,
        category_count: parsed.category_count,
        categories: [],
      };
    } else if (!node.is_leaf) {
      // GROUP (or malformed label that lacks "(N)" — treat as group, warn)
      if (!parseVariableLabel(node.label) && /\(\d+\)/.test(node.label)) {
        // Has parens with digits but didn't match — likely malformed
        warn(`malformed group-like label (treating as group): ${node.label}`);
      }
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
    } else if (node.is_leaf && currentVar !== null && shouldExpandVariable(currentVar.category_count)) {
      // CATEGORY (leaf under an expanded variable)
      currentVar.categories.push(node.label);
    }
    // else: orphan leaf or category under an unexpanded variable — skip
  }

  flushGroup();
  return groups;
}

// ── Playwright entry point ──────────────────────────────────────────────────

async function fetchRawTree(page: Page): Promise<RawNode[]> {
  return await page.evaluate(TREE_EXTRACT_JS) as RawNode[];
}

async function expandTreeForExtraction(page: Page): Promise<void> {
  // Repeatedly expand collapsed nodes that are EITHER groups (no variable
  // pattern in label) OR variables with category_count <= 100. Stop when
  // a round produces no new expansions OR after 30 rounds (safety cap).
  for (let round = 0; round < 30; round++) {
    const nodes = await fetchRawTree(page);
    let didExpand = false;
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      if (!n.is_collapsed) continue;
      const parsed = parseVariableLabel(n.label);
      if (parsed && !shouldExpandVariable(parsed.category_count)) continue; // big variable, skip
      // Click expander on the i-th element
      const expander = page.locator('.treeNodeElement').nth(i).locator('.treeNodeExpander').first();
      try {
        await expander.click();
        await new Promise(r => setTimeout(r, 300));
        didExpand = true;
      } catch { /* stale handle, next round will retry */ }
    }
    if (!didExpand) break;
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
