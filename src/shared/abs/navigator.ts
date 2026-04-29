// src/shared/abs/navigator.ts
import type { Page } from 'playwright-core';
import type { Axis } from './types.js';
import { submitJsfForm } from './jsf.js';
import { noopReporter, NEVER_ABORT, CancelledError, type PhaseReporter } from './reporter.js';

const SKIP_GROUPS = ['geographical', 'my saved tables', 'seifa'];
const isVarNode = (t: string) =>
  /^[A-Z][A-Z0-9]{3,}\s/.test(t) ||
  /^[A-Z][A-Z0-9]{2,}\s.+\(\d+\)\s*$/.test(t);

// ---------------------------------------------------------------------------
// Fuzzy match (pure function — no browser)
// ---------------------------------------------------------------------------

export function fuzzyMatchDataset(query: string, available: string[]): string {
  const q = query.toLowerCase();

  for (const name of available) {
    if (name === query) return name;
  }
  for (const name of available) {
    if (name.toLowerCase() === q) return name;
  }

  const words = q.split(/\s+/);
  for (const name of available) {
    if (words.every(w => name.toLowerCase().includes(w))) return name;
  }

  const tokens = q.match(/\w+/g) ?? [];
  for (const name of available) {
    const nameTokenStr = (name.match(/\w+/g) ?? []).join(' ').toLowerCase();
    if (tokens.every(t => nameTokenStr.includes(t))) return name;
  }

  const nonYearTokens = tokens.filter(t => !/^\d{4}$/.test(t));
  if (nonYearTokens.length < tokens.length && nonYearTokens.length > 0) {
    const candidates = available.filter(name => {
      const nts = (name.match(/\w+/g) ?? []).join(' ').toLowerCase();
      return nonYearTokens.every(t => nts.includes(t));
    });
    if (candidates.length === 1) return candidates[0];
    if (candidates.length > 1) {
      const queryYears = tokens.filter(t => /^\d{4}$/.test(t)).map(Number);
      if (queryYears.length > 0) {
        const target = Math.max(...queryYears);
        candidates.sort((a, b) => {
          const yearsA = (a.match(/\d{4}/g) ?? []).map(Number);
          const yearsB = (b.match(/\d{4}/g) ?? []).map(Number);
          const distA = yearsA.length ? Math.min(...yearsA.map(y => Math.abs(y - target))) : 9999;
          const distB = yearsB.length ? Math.min(...yearsB.map(y => Math.abs(y - target))) : 9999;
          if (distA !== distB) return distA - distB;
          // Tiebreak: prefer fewer years (single-year datasets over multi-year)
          return yearsA.length - yearsB.length;
        });
      }
      return candidates[0];
    }
  }

  throw new Error(
    `No dataset matching '${query}'. Available datasets:\n` +
    available.map(n => `  - ${n}`).join('\n')
  );
}

// ---------------------------------------------------------------------------
// Tree helpers
// ---------------------------------------------------------------------------

async function expandAllCollapsed(page: Page, maxMs = 30000, signal: AbortSignal = NEVER_ABORT): Promise<void> {
  const deadline = Date.now() + maxMs;
  let prevCollapsed = -1;
  for (let round = 0; round < 50; round++) {
    if (Date.now() > deadline) break;
    if (signal.aborted) throw new CancelledError();

    // JSF mounts .collapsed asynchronously, so poll until the count is stable
    // for two consecutive readings. This handles all three cases:
    //   - 0 stable: we're done (break round loop)
    //   - non-zero stable: this round's batch is ready to click
    //   - still changing: keep polling until it settles or deadline
    // page.evaluate is used instead of page.locator because the locator can
    // return stale results during active JSF AJAX processing. `?? 0` coerces
    // null/undefined (e.g. test mocks) to a safe numeric value.
    let collapsedCount = -1;
    let stableFor = 0;
    const settleDeadline = Math.min(deadline, Date.now() + 3000);
    while (Date.now() < settleDeadline) {
      const c = (await page.evaluate(() =>
        document.querySelectorAll('.treeNodeExpander.collapsed').length
      )) ?? 0;
      if (c === collapsedCount) {
        stableFor++;
        if (stableFor >= 2) break;
      } else {
        stableFor = 0;
        collapsedCount = c;
      }
      await new Promise(r => setTimeout(r, 300));
    }

    if (collapsedCount <= 0) break;
    if (collapsedCount === prevCollapsed) break;
    prevCollapsed = collapsedCount;
    console.log(`expandAllCollapsed: round ${round}, ${collapsedCount} nodes`);

    // Disable CSS transitions so Playwright's actionability check returns fast.
    await page.addStyleTag({ content: '* { animation:none!important; transition:none!important; }' }).catch(() => null);
    const expanders = await page.locator('.treeNodeExpander.collapsed').all();
    for (const expander of expanders) {
      if (Date.now() > deadline) break;
      if (signal.aborted) throw new CancelledError();
      try {
        await expander.click();
        await new Promise(r => setTimeout(r, 300));
      } catch { /* stale handle — skip */ }
    }

    // Wait briefly for node count to stabilise after clicking (children load
    // async via JSF AJAX). 5s ceiling — if children haven't loaded by then,
    // we'll catch them on the next outer round.
    let lastCount = await page.locator('.treeNodeElement').count();
    let sameFor = 0;
    const stableDeadline = Date.now() + 5000;
    while (Date.now() < stableDeadline) {
      await new Promise(r => setTimeout(r, 500));
      const nowCount = await page.locator('.treeNodeElement').count();
      if (nowCount === lastCount) {
        sameFor++;
        if (sameFor >= 3) break;
      } else {
        sameFor = 0;
        lastCount = nowCount;
      }
    }
  }
}

export async function listDatasets(page: Page, signal: AbortSignal = NEVER_ABORT): Promise<string[]> {
  await page.waitForSelector('.treeNodeElement', { timeout: 45000 });
  await expandAllCollapsed(page, 600000, signal);
  const nodes = await page.locator('.treeNodeElement').all();
  const names: string[] = [];
  for (const node of nodes) {
    const expander = node.locator('.treeNodeExpander').first();
    const cls = await expander.getAttribute('class').catch(() => '');
    if (cls?.includes('leaf')) {
      const text = (await node.locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
      if (text) names.push(text);
    }
  }
  return names;
}

// ---------------------------------------------------------------------------
// Dataset selection
// ---------------------------------------------------------------------------

export async function selectDataset(
  page: Page,
  dataset: string,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<string> {
  const t0 = Date.now();
  reporter({ type: 'phase_start', phaseId: 'dataset', phaseLabel: 'Selecting dataset', phaseSub: 'resolving dataset from catalog' });
  reporter({ type: 'log', level: 'phase', message: '» phase 2/7 — Selecting dataset' });
  reporter({ type: 'log', level: 'info', message: `  resolving dataset: ${dataset}` });

  if (signal.aborted) throw new CancelledError();
  await page.waitForSelector('.treeNodeElement', { timeout: 45000 });

  // Fast path: type the dataset name into the catalogue's #searchPattern box
  // so JSF filters the tree to a small candidate set, then match against that.
  // The legacy full-tree enumeration (listDatasets + expandAllCollapsed) takes
  // 5–15 min on the runtime path because it walks every node in the catalogue.
  // Search-driven filtering brings it to ~10–30 s in the common case.
  const fastMatch = await trySearchDatasetMatch(page, dataset, signal);
  let matched: string;
  if (fastMatch) {
    matched = fastMatch;
    console.log(`selectDataset: fast-path matched='${matched}' in ${Date.now() - t0}ms`);
  } else {
    // Fallback: clear search and walk the full catalogue. Slow but handles
    // fuzzy queries that don't survive the JSF search filter.
    await clearDatasetSearch(page).catch(() => null);
    const available = await listDatasets(page, signal);
    if (available.length === 0) {
      throw new Error('Dataset catalogue returned 0 datasets — session may have expired.');
    }
    console.log(`selectDataset: slow-path ${available.length} available:`, available.slice(0, 20));
    matched = fuzzyMatchDataset(dataset, available);
    console.log(`selectDataset: slow-path matched='${matched}'`);
  }
  reporter({ type: 'log', level: 'info', message: `  ✓ resolved dataset: ${matched}` });

  if (signal.aborted) throw new CancelledError();

  const labels = await page.locator('.treeNodeElement .label').all();
  let target = null;
  for (const lbl of labels) {
    if ((await lbl.textContent())?.trim() === matched) {
      target = lbl;
      break;
    }
  }
  if (!target) {
    throw new Error(`Found '${matched}' in dataset list but cannot locate it in the UI.`);
  }

  await target.dblclick();
  await page.waitForURL('**/tableView.xhtml*', { timeout: 15000 });
  console.log(`selectDataset: navigated to ${page.url()}`);

  reporter({ type: 'phase_complete', phaseId: 'dataset', elapsed: (Date.now() - t0) / 1000 });
  return matched;
}

// Returns the resolved dataset label if the JSF catalogue search surfaced a
// match, or null if the search box is unavailable or no match could be made
// in the filtered tree (caller should fall back to slow enumeration).
async function trySearchDatasetMatch(
  page: Page,
  dataset: string,
  signal: AbortSignal,
): Promise<string | null> {
  let boxCount = 0;
  try {
    boxCount = await page.locator('#searchPattern').count();
  } catch {
    return null;
  }
  if (boxCount === 0) return null;
  if (signal.aborted) throw new CancelledError();

  try {
    await page.fill('#searchPattern', '');
    await page.fill('#searchPattern', dataset);
    let clicked = false;
    try {
      const btnCount = await page.locator('#searchButton').count();
      if (btnCount > 0) {
        await page.locator('#searchButton').first().click();
        clicked = true;
      }
    } catch { /* fall through to Enter */ }
    if (!clicked) await page.keyboard.press('Enter');
  } catch {
    return null;
  }

  // Wait for the JSF AJAX-driven tree to settle (two consecutive same node
  // counts), bounded at 10 s. The filtered tree should be tiny.
  const deadline = Date.now() + 10_000;
  let prevCount = -1;
  let stableFor = 0;
  while (Date.now() < deadline) {
    if (signal.aborted) throw new CancelledError();
    await new Promise(r => setTimeout(r, 400));
    let count = 0;
    try { count = await page.locator('.treeNodeElement').count(); } catch { return null; }
    if (count === prevCount) {
      stableFor++;
      if (stableFor >= 2) break;
    } else {
      stableFor = 0;
      prevCount = count;
    }
  }

  // Filtered tree may still hide datasets behind a collapsed parent group
  // (e.g. "Census 2021"). Expand with a tight budget — the filtered set is
  // small so this is cheap.
  await expandAllCollapsed(page, 15_000, signal);

  let labels: string[] = [];
  try {
    labels = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.treeNodeElement .label'))
        .map(e => e.textContent?.trim() ?? '')
        .filter(Boolean),
    );
  } catch {
    return null;
  }
  console.log(`selectDataset: search returned ${labels.length} labels:`, labels.slice(0, 20));

  if (labels.includes(dataset)) return dataset;
  try {
    return fuzzyMatchDataset(dataset, labels);
  } catch {
    return null;
  }
}

async function clearDatasetSearch(page: Page): Promise<void> {
  const boxCount = await page.locator('#searchPattern').count();
  if (boxCount === 0) return;
  await page.fill('#searchPattern', '');
  const btnCount = await page.locator('#searchButton').count();
  if (btnCount > 0) {
    await page.locator('#searchButton').first().click();
  } else {
    await page.keyboard.press('Enter');
  }
  await new Promise(r => setTimeout(r, 1500));
}

// ---------------------------------------------------------------------------
// Variable selection
// ---------------------------------------------------------------------------

function labelMatches(uiText: string, varName: string): boolean {
  if (uiText === varName) return true;
  const spaceIdx = uiText.indexOf(' ');
  if (spaceIdx > 0) {
    const afterCode = uiText.slice(spaceIdx + 1);
    // Handle "SEXP Sex" (no suffix)
    if (afterCode === varName) return true;
    // Handle "SEXP Sex (2)" — label starts with varName followed by space or paren
    const vl = varName.toLowerCase();
    const al = afterCode.toLowerCase();
    if (al === vl || al.startsWith(vl + ' ') || al.startsWith(vl + '(')) return true;
  }
  return false;
}

function isVariableNode(labelText: string): boolean {
  // ABS variable headers look like "SEXP Sex (2)" — code prefix + digit-only count
  return /^[A-Z][A-Z0-9]{2,}\s.+\(\d+\)\s*$/.test(labelText);
}

async function searchVariable(page: Page, varName: string): Promise<void> {
  console.log(`searchVariable: URL=${page.url()}`);
  const searchBox = page.locator('#searchPattern').first();
  const boxExists = await searchBox.count() > 0;
  console.log(`searchVariable: #searchPattern exists=${boxExists}`);
  if (boxExists) {
    await page.fill('#searchPattern', '');
    await page.fill('#searchPattern', varName);
    const btn = page.locator('#searchButton').first();
    if (await btn.count() > 0) {
      await btn.click();
    } else {
      await page.keyboard.press('Enter');
    }
  }
  await new Promise(r => setTimeout(r, 5000)); // wait longer for AJAX to update tree
  const allLabels = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.treeNodeElement .label'))
      .map(e => e.textContent?.trim() ?? '')
      .filter(Boolean)
  );
  console.log(`searchVariable '${varName}': ${allLabels.length} nodes. Labels:`, allLabels.slice(0, 50));
}

// One-shot: expand the first collapsed geographic group node so variables like
// State/Territory (STRD) become visible. Does NOT recurse — callers must not
// call expandVariableGroups afterwards or the SA4 regional hierarchy will cascade.
async function tryExpandGeographic(page: Page): Promise<boolean> {
  const nodes = await page.locator('.treeNodeElement').all();
  for (const node of nodes) {
    const rawText = (await node.locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
    const cls = await node.locator('.treeNodeExpander').first().getAttribute('class').catch(() => '') ?? '';
    if (cls.includes('collapsed') && rawText.toLowerCase().includes('geographical')) {
      console.log(`tryExpandGeographic: expanding '${rawText}'`);
      await node.locator('.treeNodeExpander').first().click();
      await new Promise(r => setTimeout(r, 2000));
      return true;
    }
  }
  return false;
}

async function checkVariableCategories(page: Page, varName: string): Promise<number> {
  // Use Playwright's native click for expander and checkboxes — required to trigger
  // PrimeFaces AJAX event handlers. JavaScript el.click() bypasses these handlers.
  const vl = varName.toLowerCase();
  const vu = varName.toUpperCase();

  // Two attempts: if the variable is not found on the first scan, expand the
  // geographic group (for variables like State/Territory) and retry once.
  let allNodes = await page.locator('.treeNodeElement').all();
  let targetIdx = -1;

  for (let attempt = 0; attempt < 2; attempt++) {
    targetIdx = -1;
    for (let i = 0; i < allNodes.length; i++) {
      const text = (await allNodes[i].locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
      const cls = await allNodes[i].locator('.treeNodeExpander').first().getAttribute('class').catch(() => '') ?? '';
      if (cls.includes('leaf')) continue;
      const tl = text.toLowerCase();
      const si = text.indexOf(' ');
      const ac = si > 0 ? text.slice(si + 1).toLowerCase() : '';
      if (tl === vl || ac === vl || ac.startsWith(vl + ' ') || ac.startsWith(vl + '(') || text.toUpperCase().startsWith(vu + ' ')) {
        targetIdx = i;
        if (cls.includes('collapsed')) {
          console.log(`checkVariableCategories: expanding '${varName}' via Playwright click`);
          await allNodes[i].locator('.treeNodeExpander').first().click();
          await new Promise(r => setTimeout(r, 2000));
        }
        break;
      }
    }

    if (targetIdx >= 0) break;

    if (attempt === 0) {
      // Variable not visible — try exposing geographic variables (State, SA2, LGA…)
      const expanded = await tryExpandGeographic(page);
      if (!expanded) break;
      allNodes = await page.locator('.treeNodeElement').all();
    }
  }

  if (targetIdx < 0) {
    const labels = await Promise.all(allNodes.slice(0, 30).map(async n => {
      const text = (await n.locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
      const cls = await n.locator('.treeNodeExpander').first().getAttribute('class').catch(() => '') ?? '';
      return `[${cls.includes('leaf') ? 'L' : cls.includes('collapsed') ? 'C' : 'E'}] ${text}`;
    }));
    console.log(`Variable '${varName}' not found. Labels:`, labels.filter(l => l.length > 4));
    throw new Error(`Variable '${varName}' not found in tree.`);
  }

  // Re-query nodes after potential expansion
  const updatedNodes = await page.locator('.treeNodeElement').all();

  // Walk from targetIdx+1 clicking unchecked leaf checkboxes, stop at next variable
  let checked = 0;
  for (let i = targetIdx + 1; i < updatedNodes.length; i++) {
    const cls = await updatedNodes[i].locator('.treeNodeExpander').first().getAttribute('class').catch(() => '') ?? '';
    if (cls.includes('leaf')) {
      const cb = updatedNodes[i].locator('input[type=checkbox]').first();
      if (await cb.count() > 0) {
        if (!(await cb.isChecked())) {
          await cb.click(); // Playwright click — triggers PrimeFaces event handlers
          await new Promise(r => setTimeout(r, 200));
        }
        checked++;
      }
    } else {
      const text = (await updatedNodes[i].locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
      if (/^[A-Z][A-Z0-9]{2,}\s.+\(\d+\)\s*$/.test(text)) break;
    }
  }

  console.log(`checkVariableCategories: '${varName}' checked ${checked} categories`);
  return checked;
}

async function expandTargetVariable(page: Page, varName: string): Promise<void> {
  // Find the target variable node and expand it if collapsed (one level only)
  const vl = varName.toLowerCase();
  const vu = varName.toUpperCase();

  const nodes = await page.locator('.treeNodeElement').all();
  for (const node of nodes) {
    const text = (await node.locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
    const expander = node.locator('.treeNodeExpander').first();
    const cls = await expander.getAttribute('class').catch(() => '') ?? '';
    if (cls.includes('leaf')) continue;

    const tl = text.toLowerCase();
    const si = text.indexOf(' ');
    const ac = si > 0 ? text.slice(si + 1).toLowerCase() : '';
    if (tl === vl || ac === vl || ac.startsWith(vl + ' ') || ac.startsWith(vl + '(') || text.toUpperCase().startsWith(vu + ' ')) {
      if (cls.includes('collapsed')) {
        console.log(`expandTargetVariable: expanding '${text}'`);
        await expander.click();
        await new Promise(r => setTimeout(r, 1000));
      }
      break;
    }
  }
}

export async function expandVariableGroups(
  page: Page,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<void> {
  // Wait for at least one tree node to be in the DOM before scanning.
  // The JSF tree is rendered via AJAX; waitForLoadState('load') in submitJsfForm
  // does not guarantee nodes are present yet. Callers that need full count-
  // stability (e.g. post-submitJsfForm) must stabilise the tree before calling.
  await page.waitForSelector('.treeNodeElement', { timeout: 30000 }).catch(() => null);

  // Track labels already clicked this call — prevents re-clicking the same node
  // in subsequent rounds when the DOM hasn't updated yet (e.g. slow AJAX).
  const alreadyExpanded = new Set<string>();
  for (let round = 0; round < 5; round++) {
    if (signal.aborted) throw new CancelledError();
    const nodes = await page.locator('.treeNodeElement').all();
    let anyExpanded = false;
    for (const node of nodes) {
      if (signal.aborted) throw new CancelledError();
      const rawText = (await node.locator('.label').first().textContent().catch(() => ''))?.trim() ?? '';
      const text = rawText.toLowerCase();
      if (alreadyExpanded.has(rawText)) continue;
      const expander = node.locator('.treeNodeExpander').first();
      const cls = await expander.getAttribute('class').catch(() => '') ?? '';
      if (cls.includes('collapsed') && !SKIP_GROUPS.some(k => text.includes(k)) && !isVarNode(rawText)) {
        console.log(`expandVariableGroups: round ${round} expanding group '${rawText}'`);
        reporter({ type: 'log', level: 'info', message: `  expanded ${rawText}` });
        await expander.click();
        await new Promise(r => setTimeout(r, 1500));
        alreadyExpanded.add(rawText);
        anyExpanded = true;
      }
    }
    const total = await page.locator('.treeNodeElement').count();
    console.log(`expandVariableGroups: round ${round} done, total DOM nodes: ${total}`);
    if (!anyExpanded) break;
  }
}

// ---------------------------------------------------------------------------
// Geography selection
// ---------------------------------------------------------------------------

export async function selectGeography(
  page: Page,
  label: string,
  reporter: PhaseReporter = noopReporter,
): Promise<void> {
  const t0 = Date.now();
  reporter({ type: 'phase_start', phaseId: 'geography', phaseLabel: 'Selecting geography', phaseSub: 'navigating classification release' });
  reporter({ type: 'log', level: 'phase', message: '» phase geography — Selecting geography' });
  reporter({ type: 'log', level: 'info', message: `  selecting geography release: ${label}` });

  // After selectDataset returns, tableView.xhtml is loaded but its variable
  // tree is still being populated by JSF AJAX. Wait for the first tree node
  // to appear, then a brief settle so the geographic group is in the DOM.
  try {
    await page.waitForSelector('.treeNodeElement', { timeout: 30_000 });
  } catch {
    throw new Error(`selectGeography: variable tree never appeared on tableView page`);
  }
  // Settle for AJAX to finish populating remaining nodes
  await new Promise(r => setTimeout(r, 2000));

  // Geography classification releases are nested under "Geographical Areas
  // (Usual Residence)" group at depth 2. The group is collapsed by default,
  // so we expand it first to make the leaf locatable.
  const expanded = await tryExpandGeographic(page);
  if (!expanded) {
    reporter({ type: 'log', level: 'warn', message: '  geographic group not found in tree (already expanded?)' });
  }

  // Look for the leaf node by exact label match. Use page.evaluate to inspect
  // labels directly — Playwright's `hasText` does substring matching, but
  // labels like "Local Government Areas (2021 Boundaries) (UR)" can collide
  // partially across releases ("(UR)" appears in many). Match exact text.
  const nodeIndex = await page.evaluate((target) => {
    const nodes = Array.from(document.querySelectorAll('.treeNodeElement'));
    for (let i = 0; i < nodes.length; i++) {
      const lbl = nodes[i].querySelector('.label')?.textContent?.trim();
      if (lbl === target) return i;
    }
    return -1;
  }, label);

  if (nodeIndex < 0) {
    // Dump the visible label set into the log for debugging
    const labels = await page.evaluate(() => Array.from(document.querySelectorAll('.treeNodeElement .label'))
      .map(e => e.textContent?.trim() ?? '')
      .filter(Boolean));
    reporter({ type: 'log', level: 'warn', message: `  visible labels (${labels.length}): ${labels.slice(0, 30).join(' | ')}` });
    throw new Error(`selectGeography: no tree node found for "${label}"`);
  }

  const treeNodes = await page.locator('.treeNodeElement').all();
  await treeNodes[nodeIndex].locator('.label').first().click();
  // networkidle waits for JSF AJAX to settle after selection; ignore timeout (soft fail)
  await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => null);
  // Settle for JSF tree refresh after release click — state nodes load here.
  await new Promise(r => setTimeout(r, 2000));

  // Mirror the legacy Python flow: after the release loads its state/region
  // nodes, expand the non-leaf nodes to expose leaf checkboxes, then check
  // every leaf and submit to ROW axis. Without this submit, the runner would
  // continue with the tree scoped inside the LGA subtree — and selectVariables
  // would fail to find non-geographic variables like Sex.
  reporter({ type: 'log', level: 'info', message: '  expanding state/region nodes…' });
  const expanderNodes = await page.locator('.treeNodeElement').all();
  for (const node of expanderNodes) {
    const exp = node.locator('.treeNodeExpander').first();
    const cls = (await exp.getAttribute('class').catch(() => '')) ?? '';
    // Skip leaves (already terminal) and already-expanded nodes
    if (cls.includes('leaf') || !cls.includes('collapsed')) continue;
    try {
      await exp.click();
      await new Promise(r => setTimeout(r, 600));
    } catch { /* stale handle — skip */ }
  }
  // Final settle so JSF AJAX finishes populating leaves under each state.
  await new Promise(r => setTimeout(r, 2000));

  // Check every leaf checkbox in the geography subtree.
  const leafCheckboxes = await page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll('.treeNodeElement'));
    const indices: number[] = [];
    nodes.forEach((node, i) => {
      const exp = node.querySelector('.treeNodeExpander');
      const cb = node.querySelector('input[type="checkbox"]') as HTMLInputElement | null;
      if (!exp || !cb) return;
      if (!exp.className.includes('leaf')) return;
      if (!cb.checked) indices.push(i);
    });
    return indices;
  });
  reporter({ type: 'log', level: 'info', message: `  checking ${leafCheckboxes.length} geography categories…` });

  const allNodes = await page.locator('.treeNodeElement').all();
  let checkedCount = 0;
  for (const idx of leafCheckboxes) {
    if (idx >= allNodes.length) continue;
    const cb = allNodes[idx].locator('input[type="checkbox"]').first();
    try {
      await cb.click();
      checkedCount++;
      // Tiny delay every 50 checks to give PrimeFaces time to absorb events
      if (checkedCount % 50 === 0) await new Promise(r => setTimeout(r, 200));
    } catch { /* stale — skip */ }
  }

  if (checkedCount === 0) {
    throw new Error(`selectGeography: no geography categories were checkable for "${label}"`);
  }

  // Submit to the ROW axis. This reloads the page; the tree returns to the
  // top-level dataset variables, which is what subsequent selectVariables
  // calls need.
  reporter({ type: 'log', level: 'info', message: `  submitting ${checkedCount} geography categories to ROW axis…` });
  await submitJsfForm(page, 'row');
  await new Promise(r => setTimeout(r, 2000));

  reporter({ type: 'log', level: 'ok', message: `  ✓ geography selected: ${label}` });
  reporter({ type: 'phase_complete', phaseId: 'geography', elapsed: (Date.now() - t0) / 1000 });
}

export async function selectVariables(
  page: Page,
  vars: { rows: string[]; columns: string[]; wafers?: string[] },
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<void> {
  const assignments: Array<{ name: string; axis: Axis }> = [
    ...vars.rows.map(n => ({ name: n, axis: 'row' as Axis })),
    ...vars.columns.map(n => ({ name: n, axis: 'col' as Axis })),
    ...(vars.wafers ?? []).map(n => ({ name: n, axis: 'wafer' as Axis })),
  ];

  // ── Phase: tree ─────────────────────────────────────────────────────────────
  const treeStart = Date.now();
  reporter({ type: 'phase_start', phaseId: 'tree', phaseLabel: 'Expanding variable tree', phaseSub: 'walking classification nodes' });
  reporter({ type: 'log', level: 'phase', message: '» phase 3/7 — Expanding variable tree' });
  reporter({ type: 'log', level: 'info', message: '  walking classification nodes...' });

  const initialLabels = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.treeNodeElement .label'))
      .map(e => e.textContent?.trim() ?? '').filter(Boolean)
  );
  console.log(`selectVariables: initial tree (${initialLabels.length} nodes):`, initialLabels.slice(0, 30));

  await page.waitForSelector('.treeNodeElement', { timeout: 30000 }).catch(() => null);

  let prevCount = -1;
  for (let i = 0; i < 10; i++) {
    await new Promise(r => setTimeout(r, 2000));
    const count = await page.locator('.treeNodeElement').count();
    if (count === prevCount) break;
    prevCount = count;
  }

  const topGroupLabels = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.treeNodeElement .label'))
      .map(e => e.textContent?.trim() ?? '').filter(Boolean)
  );
  console.log(`selectVariables: tree stable (${topGroupLabels.length} nodes):`, topGroupLabels.slice(0, 20));

  await expandVariableGroups(page, reporter, signal);

  reporter({ type: 'log', level: 'ok', message: `  ✓ variable groups expanded` });
  reporter({ type: 'phase_complete', phaseId: 'tree', elapsed: (Date.now() - treeStart) / 1000 });

  // ── Phases: check and submit — single interleaved loop ──────────────────────
  //
  // The ABS JSF UI is stateful: submitJsfForm triggers page.form.submit() which
  // reloads the page, wiping any DOM checkbox state not yet submitted. Therefore
  // check+submit MUST remain interleaved per variable (check var1 → submit var1
  // → check var2 → submit var2). Two separate loops would cause vars 2..N to be
  // submitted with no categories selected after var1's submit reloads the page.
  //
  // Phase boundary: check phase starts before the loop. The check→submit
  // transition fires exactly once (on the first submitJsfForm call) using a
  // `firstSubmit` flag. For multi-variable runs, vars 2..N are checked and
  // submitted inside the "submit" phase — the log stream shows what's happening.
  const checkStart = Date.now();
  reporter({ type: 'phase_start', phaseId: 'check', phaseLabel: 'Checking categories', phaseSub: 'selecting leaf categories' });
  reporter({ type: 'log', level: 'phase', message: '» phase 4/7 — Checking categories' });

  let submitStart = 0;
  let firstSubmit = true;

  for (let i = 0; i < assignments.length; i++) {
    const { name, axis } = assignments[i];
    if (signal.aborted) throw new CancelledError();

    // Use the JSF search box to filter the tree to the requested variable
    // before walking it. Without this, the tree state is whatever was left by
    // previous actions (e.g. the LGA subtree after selectGeography), and
    // checkVariableCategories cannot find variables that aren't visible.
    // Legacy Python's add_variable does the same thing.
    await searchVariable(page, name);
    // Search filters the tree to matching parent groups (e.g. searching "Sex"
    // surfaces "Age and Sex" group as collapsed). Expand them so the named
    // variable's leaf node is reachable. Use a short deadline — at this stage
    // the filtered tree is tiny.
    await expandAllCollapsed(page, 30_000, signal);

    const checked = await checkVariableCategories(page, name);
    if (checked === 0) throw new Error(`No categories found for variable '${name}'.`);
    reporter({ type: 'log', level: 'info', message: `  selected ${checked} categories for ${name}` });

    // Transition check → submit exactly once (first variable)
    if (firstSubmit) {
      firstSubmit = false;
      reporter({ type: 'phase_complete', phaseId: 'check', elapsed: (Date.now() - checkStart) / 1000 });
      submitStart = Date.now();
      reporter({ type: 'phase_start', phaseId: 'submit', phaseLabel: 'Submitting table dimensions', phaseSub: 'POST /table/layout' });
      reporter({ type: 'log', level: 'phase', message: '» phase 5/7 — Submitting table dimensions' });
    }

    if (signal.aborted) throw new CancelledError();
    await new Promise(r => setTimeout(r, 300));
    await submitJsfForm(page, axis);
    reporter({ type: 'log', level: 'info', message: `  POST /TableBuilder/view/layout → 202 accepted for ${name}` });

    const bodyText = await page.evaluate(() => document.body.innerText.substring(0, 500)).catch(() => '');
    if (bodyText.includes('Your table is empty')) {
      throw new Error(`Failed to add '${name}' to ${axis} — table still empty after submission.`);
    }

    // Re-expand the variable tree after page reload so the next variable is findable.
    // submitJsfForm awaits waitForLoadState('load'), but the JSF tree renders via
    // AJAX after load fires. Wait here for the node count to stabilise before
    // calling expandVariableGroups (which only waits for the first node to appear).
    if (i < assignments.length - 1) {
      await page.waitForSelector('.treeNodeElement', { timeout: 30000 }).catch(() => null);
      let prevTreeCount = -1;
      for (let j = 0; j < 8; j++) {
        if (signal.aborted) throw new CancelledError();
        const count = await page.locator('.treeNodeElement').count();
        console.log(`selectVariables: post-submit tree stability wait ${j}, count=${count}`);
        if (count === prevTreeCount && count > 0) break;
        prevTreeCount = count;
        await new Promise(r => setTimeout(r, 2000));
      }
      await expandVariableGroups(page, reporter, signal);
    }
  }

  reporter({ type: 'log', level: 'ok', message: '  ✓ all dimensions submitted' });
  reporter({ type: 'phase_complete', phaseId: 'submit', elapsed: (Date.now() - submitStart) / 1000 });
}
