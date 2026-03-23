// ABOUTME: Main application logic for the ABS TableBuilder Query Planner.
// ABOUTME: Handles database access, wizard state, UI rendering, and JSON export.

(function () {
  'use strict';

  // ── Constants ──────────────────────────────────────────────────────────────
  const CELL_LIMIT = 1_000_000;
  const DB_PATH = 'dictionary.db';
  const STORAGE_KEY = 'tablebuilder_query_planner_state';

  // ── State ──────────────────────────────────────────────────────────────────
  let db = null;
  let state = {
    step: 1,
    dataset: null,
    selected_variables: [],
    geography: null,
    cell_estimate: 0,
    active_variable_id: null,
    query_mode: 'cross-tab', // 'cross-tab' or 'pairwise'
  };

  // ── Database Layer ─────────────────────────────────────────────────────────

  async function initDatabase() {
    const SQL = await initSqlJs({
      locateFile: file => `https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/${file}`,
    });
    const response = await fetch(DB_PATH);
    if (!response.ok) {
      throw new Error(`Failed to load database: ${response.statusText}. Make sure dictionary.db is in the same directory as index.html.`);
    }
    const buf = await response.arrayBuffer();
    db = new SQL.Database(new Uint8Array(buf));
    document.getElementById('loading-overlay').classList.add('hidden');
  }

  function dbQuery(sql, params = {}) {
    const stmt = db.prepare(sql);
    stmt.bind(params);
    const results = [];
    while (stmt.step()) {
      results.push(stmt.getAsObject());
    }
    stmt.free();
    return results;
  }

  function getAllDatasets() {
    return dbQuery(`
      SELECT d.id, d.name, d.summary,
             CASE WHEN json_array_length(d.geographies_json) > 0
                  THEN 'census' ELSE 'survey' END AS type,
             CASE WHEN json_array_length(d.geographies_json) > 0
                  OR EXISTS (
                    SELECT 1 FROM groups g
                    WHERE g.dataset_id = d.id AND g.label LIKE 'Geographical Areas%'
                  )
                  THEN 1 ELSE 0 END AS has_geo
      FROM datasets d
      ORDER BY name
    `);
  }

  function searchDatasets(query) {
    return dbQuery(`
      SELECT d.id, d.name, d.summary,
             CASE WHEN json_array_length(d.geographies_json) > 0
                  THEN 'census' ELSE 'survey' END AS type,
             CASE WHEN json_array_length(d.geographies_json) > 0
                  OR EXISTS (
                    SELECT 1 FROM groups g
                    WHERE g.dataset_id = d.id AND g.label LIKE 'Geographical Areas%'
                  )
                  THEN 1 ELSE 0 END AS has_geo
      FROM datasets_fts
      JOIN datasets d ON datasets_fts.rowid = d.id
      WHERE datasets_fts MATCH :query
      ORDER BY rank
      LIMIT 30
    `, { ':query': query + '*' });
  }

  function getVariableTree(datasetId) {
    return dbQuery(`
      SELECT g.id AS group_id,
             g.label AS group_label,
             v.id AS variable_id,
             v.code,
             v.label AS variable_label,
             COUNT(c.id) AS category_count
      FROM groups g
      JOIN variables v ON v.group_id = g.id
      LEFT JOIN categories c ON c.variable_id = v.id
      WHERE g.dataset_id = :dataset_id
        AND g.label NOT LIKE 'Geographical Areas%'
      GROUP BY v.id
      HAVING COUNT(c.id) > 0
      ORDER BY g.label, v.label
    `, { ':dataset_id': datasetId });
  }

  function getCategories(variableId) {
    return dbQuery(`
      SELECT id, label
      FROM categories
      WHERE variable_id = :variable_id
      ORDER BY rowid
    `, { ':variable_id': variableId });
  }

  function searchVariables(query, datasetId) {
    return dbQuery(`
      SELECT v.id, v.code, v.label, g.label AS group_label
      FROM variables_fts
      JOIN variables v ON variables_fts.rowid = v.id
      JOIN groups g ON v.group_id = g.id
      WHERE variables_fts MATCH :query
        AND g.label NOT LIKE 'Geographical Areas%'
        AND EXISTS (
          SELECT 1 FROM groups g2
          WHERE g2.id = v.group_id AND g2.dataset_id = :dataset_id
        )
      ORDER BY rank
      LIMIT 50
    `, { ':query': query + '*', ':dataset_id': datasetId });
  }

  function getGeographies(datasetId) {
    // First try geographies_json from the datasets table
    const rows = dbQuery(`
      SELECT geographies_json FROM datasets WHERE id = :id
    `, { ':id': datasetId });
    if (rows.length > 0) {
      try {
        const geos = JSON.parse(rows[0].geographies_json);
        if (geos.length > 0) return geos;
      } catch {
        // fall through
      }
    }

    // Fall back: detect geography types from group labels containing "Geographical Areas"
    // Extract distinct geography type names from the group hierarchy
    const geoGroups = dbQuery(`
      SELECT DISTINCT g.label
      FROM groups g
      WHERE g.dataset_id = :dataset_id
        AND g.label LIKE 'Geographical Areas%'
      ORDER BY g.label
    `, { ':dataset_id': datasetId });

    if (geoGroups.length === 0) return [];

    // Parse geography type names from group paths like
    // "Geographical Areas (Enumeration) > Remoteness Areas > South Australia"
    // We want the second-level name: "Remoteness Areas"
    const typeSet = new Set();
    const geoPrefix = geoGroups[0].label.split(' > ')[0]; // e.g. "Geographical Areas (Enumeration)"
    for (const row of geoGroups) {
      const parts = row.label.split(' > ');
      if (parts.length >= 2) {
        // Second level is the geography type (e.g. "Remoteness Areas", "Postal Areas")
        typeSet.add(parts[1]);
      }
    }
    return Array.from(typeSet).sort();
  }

  function getGeographyAreas(datasetId, typeLabel) {
    // First try matching variable labels (for datasets with geographies_json)
    let results = dbQuery(`
      SELECT c.id, c.label
      FROM categories c
      JOIN variables v ON c.variable_id = v.id
      JOIN groups g ON v.group_id = g.id
      WHERE g.dataset_id = :dataset_id
        AND g.label LIKE '%Geographical Areas%'
        AND LOWER(v.label) = LOWER(:type_label)
      ORDER BY c.label
    `, { ':dataset_id': datasetId, ':type_label': typeLabel });

    if (results.length > 0) return results;

    // Fall back: for datasets where geo is stored as variable tree,
    // the typeLabel is a group path segment. Find all categories under
    // groups matching "Geographical Areas% > {typeLabel}%"
    results = dbQuery(`
      SELECT c.id, c.label
      FROM categories c
      JOIN variables v ON c.variable_id = v.id
      JOIN groups g ON v.group_id = g.id
      WHERE g.dataset_id = :dataset_id
        AND g.label LIKE '%Geographical Areas%'
        AND g.label LIKE '%' || :type_label || '%'
      ORDER BY c.label
    `, { ':dataset_id': datasetId, ':type_label': typeLabel });

    return results;
  }

  // ── State Management ──────────────────────────────────────────────────────

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // localStorage may be unavailable
    }
  }

  function loadState() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        state = { ...state, ...parsed };
        return true;
      }
    } catch {
      // ignore
    }
    return false;
  }

  function clearState() {
    state = {
      step: 1,
      dataset: null,
      selected_variables: [],
      geography: null,
      cell_estimate: 0,
      active_variable_id: null,
      query_mode: 'cross-tab',
    };
    saveState();
  }

  // ── Cell Count Calculation ─────────────────────────────────────────────────

  function calculateCellCount() {
    const vars = state.selected_variables;
    if (vars.length === 0) {
      state.cell_estimate = 0;
      return 0;
    }
    const geoMultiplier = (state.geography && state.geography.effective_count > 0)
      ? state.geography.effective_count : 1;

    if (state.query_mode === 'pairwise' && vars.length >= 2) {
      // For pairwise: find the largest single-pair cell count
      let maxPairCells = 0;
      for (let i = 0; i < vars.length; i++) {
        for (let j = i + 1; j < vars.length; j++) {
          const pairCells = vars[i].effective_count * vars[j].effective_count * geoMultiplier;
          if (pairCells > maxPairCells) maxPairCells = pairCells;
        }
      }
      state.cell_estimate = maxPairCells;
      return maxPairCells;
    }

    // Cross-tab mode: full Cartesian product
    let cells = 1;
    for (const v of vars) {
      cells *= v.effective_count;
    }
    cells *= geoMultiplier;
    state.cell_estimate = cells;
    return cells;
  }

  function countPairs() {
    const n = state.selected_variables.length;
    return n >= 2 ? (n * (n - 1)) / 2 : 0;
  }

  function updateCellCountBar() {
    const cells = calculateCellCount();
    const bar = document.getElementById('cell-count-bar');
    const valueEl = document.getElementById('cell-count-value');
    const pctEl = document.getElementById('cell-count-pct');
    const statusEl = document.getElementById('cell-count-status');
    const splitsEl = document.getElementById('cell-count-splits');

    if (state.step !== 2 && state.step !== 3) {
      bar.style.display = 'none';
      return;
    }
    bar.style.display = '';

    if (state.query_mode === 'pairwise' && state.selected_variables.length >= 2) {
      const nPairs = countPairs();
      valueEl.textContent = cells.toLocaleString() + ' cells (largest pair)';
      const pct = ((cells / CELL_LIMIT) * 100);
      pctEl.textContent = `${nPairs} pairs / ${pct.toFixed(1)}% of limit`;

      statusEl.className = 'status-badge';
      if (pct <= 80) {
        statusEl.classList.add('status-green');
        statusEl.textContent = 'OK';
      } else if (pct <= 100) {
        statusEl.classList.add('status-amber');
        statusEl.textContent = 'Near limit';
      } else {
        statusEl.classList.add('status-red');
        statusEl.textContent = 'Over limit';
      }
      splitsEl.textContent = `${nPairs} sub-queries (one per pair)`;
      splitsEl.style.display = '';
    } else {
      valueEl.textContent = cells.toLocaleString() + ' cells';
      const pct = ((cells / CELL_LIMIT) * 100);
      pctEl.textContent = pct.toFixed(1) + '% of limit';

      statusEl.className = 'status-badge';
      if (pct <= 80) {
        statusEl.classList.add('status-green');
        statusEl.textContent = 'OK';
      } else if (pct <= 100) {
        statusEl.classList.add('status-amber');
        statusEl.textContent = 'Near limit';
      } else {
        statusEl.classList.add('status-red');
        statusEl.textContent = 'Over limit';
      }

      if (cells > CELL_LIMIT) {
        const nSubs = Math.ceil(cells / CELL_LIMIT);
        splitsEl.textContent = `Will require ${nSubs} sub-queries`;
        splitsEl.style.display = '';
      } else {
        splitsEl.style.display = 'none';
      }
    }
    saveState();
  }

  // ── Split Algorithm ────────────────────────────────────────────────────────

  function computeSplitPlan() {
    const cells = state.cell_estimate;
    if (cells <= CELL_LIMIT) return null;

    const vars = state.selected_variables;
    if (vars.length === 0) return null;

    // Find the variable with the highest effective_count
    let splitVar = vars[0];
    for (const v of vars) {
      if (v.effective_count > splitVar.effective_count) {
        splitVar = v;
      }
    }

    const otherCells = cells / splitVar.effective_count;
    const maxCatsPerQ = Math.floor(CELL_LIMIT / otherCells);
    if (maxCatsPerQ < 1) {
      // Even one category exceeds the limit — shouldn't happen in practice
      return { splitVar, chunks: [[]], maxCatsPerQ: 1, otherCells };
    }

    // Get the actual category list for the split variable
    let catList;
    if (splitVar.selected_categories === 'all') {
      catList = getCategories(splitVar.variable_id).map(c => c.label);
    } else {
      catList = splitVar.selected_categories;
    }

    const chunks = [];
    for (let i = 0; i < catList.length; i += maxCatsPerQ) {
      chunks.push(catList.slice(i, i + maxCatsPerQ));
    }

    return { splitVar, chunks, maxCatsPerQ, otherCells };
  }

  // ── JSON Export ────────────────────────────────────────────────────────────

  function buildPairwiseSubQueries(variablesArray, geoObj, datasetObj) {
    const subQueries = [];
    let idx = 0;
    for (let i = 0; i < variablesArray.length; i++) {
      for (let j = i + 1; j < variablesArray.length; j++) {
        idx++;
        const pairVars = [variablesArray[i], variablesArray[j]];
        let pairCells = pairVars[0].effective_count * pairVars[1].effective_count;
        if (geoObj) pairCells *= geoObj.effective_count;

        subQueries.push({
          sub_query_index: idx,
          pair: [pairVars[0].code || pairVars[0].label, pairVars[1].code || pairVars[1].label],
          dataset: datasetObj,
          variables: pairVars,
          geography: geoObj,
          cell_estimate: {
            total_cells: pairCells,
            limit: CELL_LIMIT,
            within_limit: pairCells <= CELL_LIMIT,
            split_required: false,
            n_sub_queries: 1,
          },
          sub_queries: null,
        });
      }
    }
    return subQueries;
  }

  function buildExportJSON() {
    const ds = state.dataset;
    const vars = state.selected_variables;
    const geo = state.geography;
    const cells = state.cell_estimate;
    const isPairwise = state.query_mode === 'pairwise' && vars.length >= 2;

    const variablesArray = vars.map(v => ({
      variable_id: v.variable_id,
      code: v.code || '',
      label: v.label,
      group_path: v.group_path,
      total_categories: v.total_categories,
      selected_categories: v.selected_categories,
      effective_count: v.effective_count,
    }));

    const geoObj = geo ? {
      type_label: geo.type_label,
      total_areas: geo.total_areas,
      selections: geo.selections,
      effective_count: geo.effective_count,
    } : null;

    const datasetObj = {
      name: ds.name,
      type: ds.type,
      dataset_id: ds.id,
    };

    if (isPairwise) {
      const pairSubQueries = buildPairwiseSubQueries(variablesArray, geoObj, datasetObj);
      const maxPairCells = Math.max(...pairSubQueries.map(sq => sq.cell_estimate.total_cells));

      return {
        schema_version: '1.0',
        created_at: new Date().toISOString(),
        query_mode: 'pairwise',
        dataset: datasetObj,
        variables: variablesArray,
        geography: geoObj,
        cell_estimate: {
          total_cells: maxPairCells,
          limit: CELL_LIMIT,
          within_limit: maxPairCells <= CELL_LIMIT,
          split_required: false,
          n_sub_queries: pairSubQueries.length,
        },
        sub_queries: pairSubQueries,
      };
    }

    // Cross-tab mode
    const withinLimit = cells <= CELL_LIMIT;
    const splitPlan = computeSplitPlan();
    const nSubQueries = splitPlan ? splitPlan.chunks.length : 1;

    const result = {
      schema_version: '1.0',
      created_at: new Date().toISOString(),
      query_mode: 'cross-tab',
      dataset: datasetObj,
      variables: variablesArray,
      geography: geoObj,
      cell_estimate: {
        total_cells: cells,
        limit: CELL_LIMIT,
        within_limit: withinLimit,
        split_required: !withinLimit,
        n_sub_queries: nSubQueries,
      },
      sub_queries: null,
    };

    if (splitPlan) {
      result.sub_queries = splitPlan.chunks.map((chunk, idx) => {
        const subVars = variablesArray.map(v => {
          if (v.variable_id === splitPlan.splitVar.variable_id) {
            return {
              ...v,
              selected_categories: chunk,
              effective_count: chunk.length,
            };
          }
          return { ...v };
        });

        let subCells = 1;
        for (const sv of subVars) {
          subCells *= sv.effective_count;
        }
        if (geoObj) {
          subCells *= geoObj.effective_count;
        }

        return {
          sub_query_index: idx + 1,
          split_variable_code: splitPlan.splitVar.code || '',
          dataset: datasetObj,
          variables: subVars,
          geography: geoObj,
          cell_estimate: {
            total_cells: subCells,
            limit: CELL_LIMIT,
            within_limit: subCells <= CELL_LIMIT,
            split_required: false,
            n_sub_queries: 1,
          },
          sub_queries: null,
        };
      });
    }

    return result;
  }

  function downloadJSON() {
    const json = buildExportJSON();
    const blob = new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);

    const slug = state.dataset.name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '')
      .slice(0, 40);
    const date = new Date().toISOString().slice(0, 10);
    const filename = `tablebuilder_query_${slug}_${date}.json`;

    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ── Wizard Navigation ─────────────────────────────────────────────────────

  function datasetHasGeo() {
    return state.dataset && state.dataset.has_geo;
  }

  function goToStep(step) {
    // Skip geography step for datasets without geography
    if (step === 3 && state.dataset && !datasetHasGeo()) {
      step = state.step < 3 ? 4 : 2;
    }
    if (step < 1) step = 1;
    if (step > 4) step = 4;

    state.step = step;

    // Show/hide sections
    document.querySelectorAll('.wizard-step').forEach(s => s.style.display = 'none');
    const activeSection = document.getElementById(`step-${step}`);
    if (activeSection) activeSection.style.display = '';

    // Update progress bar
    document.querySelectorAll('#progress-bar .step').forEach(s => {
      const sStep = parseInt(s.dataset.step);
      s.classList.remove('active', 'completed', 'disabled');
      if (sStep === step) {
        s.classList.add('active');
      } else if (sStep < step) {
        s.classList.add('completed');
      }
      // Hide geography step indicator for datasets without geography
      if (sStep === 3 && state.dataset && !datasetHasGeo()) {
        s.classList.add('disabled');
      }
    });

    // Navigation buttons
    const btnBack = document.getElementById('btn-back');
    const btnNext = document.getElementById('btn-next');

    btnBack.style.display = step === 1 ? 'none' : '';

    if (step === 4) {
      btnNext.style.display = 'none';
      renderReview();
    } else {
      btnNext.style.display = '';
      updateNextButton();
    }

    updateCellCountBar();

    if (step === 2 && state.dataset) {
      document.getElementById('step2-dataset-name').textContent = state.dataset.name;
      renderVariableTree();
      // Restore mode toggle state
      document.querySelectorAll('.mode-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === state.query_mode);
      });
      const desc = document.getElementById('mode-description');
      if (state.query_mode === 'pairwise') {
        desc.textContent = 'One sub-query per pair of variables. Higher data quality, less sparsity.';
      } else {
        desc.textContent = 'Full Cartesian product of all selected variables.';
      }
    }
    if (step === 3 && state.dataset) {
      document.getElementById('step3-dataset-name').textContent = state.dataset.name;
      renderGeography();
    }

    saveState();
  }

  function updateNextButton() {
    const btnNext = document.getElementById('btn-next');
    if (state.step === 1) {
      btnNext.disabled = !state.dataset;
    } else if (state.step === 2) {
      // Always enabled — spec says Next is always enabled regardless of cell count
      btnNext.disabled = state.selected_variables.length === 0;
    } else if (state.step === 3) {
      btnNext.disabled = false;
    }
  }

  // ── Step 1: Dataset Selection ──────────────────────────────────────────────

  let datasetSearchTimeout = null;
  let allDatasets = null;
  let currentFilter = 'all';

  function renderDatasetList(datasets) {
    const list = document.getElementById('dataset-list');
    if (datasets.length === 0) {
      list.innerHTML = '<p style="padding:20px;text-align:center;color:var(--text-secondary)">No datasets found.</p>';
      return;
    }
    list.innerHTML = datasets.map(d => `
      <div class="dataset-card ${state.dataset && state.dataset.id === d.id ? 'selected' : ''}"
           data-id="${d.id}">
        <div class="dataset-card-header">
          <span class="dataset-card-name">${escapeHtml(d.name)}</span>
          <span class="badge ${d.type === 'census' ? 'badge-census' : 'badge-survey'}">${d.type}</span>
          ${d.has_geo ? '<span class="chip-geo">Geo available</span>' : ''}
        </div>
        <div class="dataset-card-summary">${escapeHtml((d.summary || '').slice(0, 120))}</div>
      </div>
    `).join('');

    list.querySelectorAll('.dataset-card').forEach(card => {
      const selectCard = () => {
        const id = parseInt(card.dataset.id);
        const ds = datasets.find(d => d.id === id);
        if (!ds) return;

        // If switching datasets, clear variables and geography
        if (!state.dataset || state.dataset.id !== id) {
          state.selected_variables = [];
          state.geography = null;
          state.active_variable_id = null;
        }

        state.dataset = ds;
        list.querySelectorAll('.dataset-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        updateNextButton();
        saveState();
      };

      card.addEventListener('click', selectCard);
      card.addEventListener('dblclick', () => {
        selectCard();
        goToStep(2);
      });
    });
  }

  function filterAndRenderDatasets() {
    const searchInput = document.getElementById('dataset-search');
    const query = searchInput.value.trim();

    let datasets;
    if (query) {
      try {
        datasets = searchDatasets(query);
      } catch {
        datasets = allDatasets || [];
      }
    } else {
      datasets = allDatasets || [];
    }

    if (currentFilter !== 'all') {
      datasets = datasets.filter(d => d.type === currentFilter);
    }

    renderDatasetList(datasets);
  }

  function initStep1() {
    allDatasets = getAllDatasets();
    renderDatasetList(allDatasets);

    const searchInput = document.getElementById('dataset-search');
    searchInput.addEventListener('input', () => {
      clearTimeout(datasetSearchTimeout);
      datasetSearchTimeout = setTimeout(filterAndRenderDatasets, 250);
    });

    document.querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFilter = btn.dataset.filter;
        filterAndRenderDatasets();
      });
    });
  }

  // ── Step 2: Variables & Categories ─────────────────────────────────────────

  let variableTreeData = null;
  let variableSearchTimeout = null;

  function getVariableCount(datasetId) {
    const rows = dbQuery(`
      SELECT COUNT(*) AS cnt FROM variables v
      JOIN groups g ON v.group_id = g.id
      WHERE g.dataset_id = :dataset_id
    `, { ':dataset_id': datasetId });
    return rows[0].cnt;
  }

  function renderVariableTree() {
    if (!state.dataset) return;

    variableTreeData = getVariableTree(state.dataset.id);
    const container = document.getElementById('variable-tree');

    // Check for incomplete data (variables missing categories)
    const totalVars = getVariableCount(state.dataset.id);
    const loadedVars = variableTreeData.length;
    const warningEl = document.getElementById('step2-dataset-name');
    if (loadedVars < totalVars) {
      warningEl.innerHTML = `${escapeHtml(state.dataset.name)} <span style="color:var(--amber);font-size:12px">(${totalVars - loadedVars} variables hidden — missing category data in dictionary)</span>`;
    } else {
      warningEl.textContent = state.dataset.name;
    }

    // Group by group_label
    const groups = {};
    const groupOrder = [];
    for (const row of variableTreeData) {
      if (!groups[row.group_label]) {
        groups[row.group_label] = [];
        groupOrder.push(row.group_label);
      }
      groups[row.group_label].push(row);
    }

    let html = '';
    for (const groupLabel of groupOrder) {
      const vars = groups[groupLabel];
      html += `
        <div class="tree-group">
          <div class="tree-group-header" data-group="${escapeAttr(groupLabel)}">
            <span class="expander">&#9660;</span>
            <span>${escapeHtml(groupLabel)}</span>
          </div>
          <div class="tree-group-children">
      `;
      for (const v of vars) {
        const selected = state.selected_variables.find(sv => sv.variable_id === v.variable_id);
        const isActive = state.active_variable_id === v.variable_id;
        html += `
          <div class="tree-variable ${isActive ? 'active' : ''}" data-var-id="${v.variable_id}">
            <input type="checkbox" ${selected ? 'checked' : ''} data-var-id="${v.variable_id}" title="Include in query">
            ${v.code ? `<span class="var-code">${escapeHtml(v.code)}</span>` : ''}
            <span class="var-label" title="${escapeAttr(v.variable_label)}">${escapeHtml(v.variable_label)}</span>
            <span class="var-cat-count">${v.category_count} cats</span>
          </div>
        `;
      }
      html += '</div></div>';
    }

    container.innerHTML = html;

    // Group toggle handlers
    container.querySelectorAll('.tree-group-header').forEach(header => {
      header.addEventListener('click', () => {
        header.classList.toggle('collapsed');
        const children = header.nextElementSibling;
        children.classList.toggle('collapsed');
      });
    });

    // Variable click handlers (show categories)
    container.querySelectorAll('.tree-variable').forEach(varEl => {
      varEl.addEventListener('click', (e) => {
        if (e.target.type === 'checkbox') return;
        const varId = parseInt(varEl.dataset.varId);
        state.active_variable_id = varId;
        container.querySelectorAll('.tree-variable').forEach(v => v.classList.remove('active'));
        varEl.classList.add('active');
        renderCategorySelector(varId);
        saveState();
      });
    });

    // Checkbox handlers
    container.querySelectorAll('.tree-variable input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', (e) => {
        const varId = parseInt(cb.dataset.varId);
        if (cb.checked) {
          // Select all categories for this variable
          selectAllCategoriesForVariable(varId);
        } else {
          // Remove variable from selection
          state.selected_variables = state.selected_variables.filter(v => v.variable_id !== varId);
        }
        updateCellCountBar();
        updateNextButton();
        // Re-render category selector if this is the active variable
        if (state.active_variable_id === varId) {
          renderCategorySelector(varId);
        }
      });
    });

    // Variable search
    const searchInput = document.getElementById('variable-search');
    searchInput.value = '';
    searchInput.addEventListener('input', () => {
      clearTimeout(variableSearchTimeout);
      variableSearchTimeout = setTimeout(() => {
        filterVariableTree(searchInput.value.trim());
      }, 250);
    });
  }

  function selectAllCategoriesForVariable(varId) {
    const row = variableTreeData.find(r => r.variable_id === varId);
    if (!row) return;

    const existing = state.selected_variables.find(v => v.variable_id === varId);
    if (existing) {
      existing.selected_categories = 'all';
      existing.effective_count = row.category_count;
    } else {
      state.selected_variables.push({
        variable_id: varId,
        code: row.code,
        label: row.variable_label,
        group_path: row.group_label,
        total_categories: row.category_count,
        selected_categories: 'all',
        effective_count: row.category_count,
      });
    }
    saveState();
  }

  function filterVariableTree(query) {
    const container = document.getElementById('variable-tree');
    if (!query) {
      // Show all
      container.querySelectorAll('.tree-variable').forEach(v => v.classList.remove('hidden'));
      container.querySelectorAll('.tree-group-children').forEach(c => c.classList.remove('collapsed'));
      container.querySelectorAll('.tree-group-header').forEach(h => h.classList.remove('collapsed'));
      return;
    }

    try {
      const matchIds = new Set(searchVariables(query, state.dataset.id).map(r => r.id));

      container.querySelectorAll('.tree-group').forEach(group => {
        const children = group.querySelector('.tree-group-children');
        const header = group.querySelector('.tree-group-header');
        let hasVisible = false;

        children.querySelectorAll('.tree-variable').forEach(varEl => {
          const varId = parseInt(varEl.dataset.varId);
          if (matchIds.has(varId)) {
            varEl.classList.remove('hidden');
            hasVisible = true;
          } else {
            varEl.classList.add('hidden');
          }
        });

        if (hasVisible) {
          children.classList.remove('collapsed');
          header.classList.remove('collapsed');
        } else {
          children.classList.add('collapsed');
          header.classList.add('collapsed');
        }
      });
    } catch {
      // FTS query error — show all
      container.querySelectorAll('.tree-variable').forEach(v => v.classList.remove('hidden'));
    }
  }

  function renderCategorySelector(varId) {
    const container = document.getElementById('category-selector');
    const categories = getCategories(varId);
    const row = variableTreeData.find(r => r.variable_id === varId);
    if (!row) return;

    const selectedVar = state.selected_variables.find(v => v.variable_id === varId);
    const selectedCats = selectedVar ? selectedVar.selected_categories : null;
    const isAllSelected = selectedCats === 'all';
    const selectedSet = isAllSelected
      ? new Set(categories.map(c => c.label))
      : new Set(selectedCats || []);

    const selectedCount = isAllSelected ? categories.length : selectedSet.size;

    container.innerHTML = `
      <div class="category-header">
        <h3>${escapeHtml(row.variable_label)}${row.code ? ` (${escapeHtml(row.code)})` : ''}</h3>
        <div class="category-controls">
          <button class="btn-small" id="cat-select-all">Select All</button>
          <button class="btn-small" id="cat-deselect-all">Deselect All</button>
          <span class="count-indicator" id="cat-count">${selectedCount} of ${categories.length} selected</span>
        </div>
        <input type="text" class="category-filter" id="cat-filter" placeholder="Filter categories..." autocomplete="off">
      </div>
      <div class="checklist" id="cat-checklist">
        ${categories.map(c => `
          <div class="checklist-item" data-label="${escapeAttr(c.label)}">
            <input type="checkbox" id="cat-${c.id}" data-label="${escapeAttr(c.label)}" ${selectedSet.has(c.label) ? 'checked' : ''}>
            <label for="cat-${c.id}">${escapeHtml(c.label)}</label>
          </div>
        `).join('')}
      </div>
    `;

    // Select All
    container.querySelector('#cat-select-all').addEventListener('click', () => {
      selectAllCategoriesForVariable(varId);
      renderCategorySelector(varId);
      updateVariableCheckbox(varId, true);
      updateCellCountBar();
    });

    // Deselect All
    container.querySelector('#cat-deselect-all').addEventListener('click', () => {
      state.selected_variables = state.selected_variables.filter(v => v.variable_id !== varId);
      renderCategorySelector(varId);
      updateVariableCheckbox(varId, false);
      updateCellCountBar();
      updateNextButton();
    });

    // Individual checkbox changes
    container.querySelectorAll('#cat-checklist input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', () => {
        updateCategorySelection(varId, categories);
      });
    });

    // Filter
    container.querySelector('#cat-filter').addEventListener('input', (e) => {
      const filter = e.target.value.toLowerCase();
      container.querySelectorAll('.checklist-item').forEach(item => {
        const label = item.dataset.label.toLowerCase();
        item.classList.toggle('hidden', filter && !label.includes(filter));
      });
    });
  }

  function updateCategorySelection(varId, categories) {
    const container = document.getElementById('category-selector');
    const checkboxes = container.querySelectorAll('#cat-checklist input[type="checkbox"]');
    const selected = [];
    checkboxes.forEach(cb => {
      if (cb.checked) selected.push(cb.dataset.label);
    });

    const row = variableTreeData.find(r => r.variable_id === varId);
    if (!row) return;

    if (selected.length === 0) {
      // Remove variable
      state.selected_variables = state.selected_variables.filter(v => v.variable_id !== varId);
      updateVariableCheckbox(varId, false);
    } else {
      const isAll = selected.length === categories.length;
      const existing = state.selected_variables.find(v => v.variable_id === varId);
      const varState = {
        variable_id: varId,
        code: row.code,
        label: row.variable_label,
        group_path: row.group_label,
        total_categories: row.category_count,
        selected_categories: isAll ? 'all' : selected,
        effective_count: selected.length,
      };
      if (existing) {
        Object.assign(existing, varState);
      } else {
        state.selected_variables.push(varState);
      }
      updateVariableCheckbox(varId, true);
    }

    // Update count indicator
    const countEl = container.querySelector('#cat-count');
    if (countEl) {
      countEl.textContent = `${selected.length} of ${categories.length} selected`;
    }

    updateCellCountBar();
    updateNextButton();
    saveState();
  }

  function updateVariableCheckbox(varId, checked) {
    const cb = document.querySelector(`#variable-tree input[data-var-id="${varId}"]`);
    if (cb) cb.checked = checked;
  }

  // ── Step 3: Geography ─────────────────────────────────────────────────────

  let geoAreasData = null;

  function renderGeography() {
    if (!state.dataset) return;
    const geographies = getGeographies(state.dataset.id);
    const dropdown = document.getElementById('geo-type-dropdown');

    dropdown.innerHTML = '<option value="">-- Select a geography level --</option>';
    for (const geo of geographies) {
      const opt = document.createElement('option');
      opt.value = geo;
      opt.textContent = geo;
      if (state.geography && state.geography.type_label === geo) {
        opt.selected = true;
      }
      dropdown.appendChild(opt);
    }

    dropdown.addEventListener('change', () => {
      const typeLabel = dropdown.value;
      if (!typeLabel) {
        document.getElementById('geo-areas').style.display = 'none';
        state.geography = null;
        updateCellCountBar();
        saveState();
        return;
      }
      loadGeographyAreas(typeLabel);
    });

    // If we have a saved geography, load it
    if (state.geography && state.geography.type_label) {
      loadGeographyAreas(state.geography.type_label);
    }
  }

  function loadGeographyAreas(typeLabel) {
    geoAreasData = getGeographyAreas(state.dataset.id, typeLabel);
    const areasContainer = document.getElementById('geo-areas');
    const areaList = document.getElementById('geo-area-list');

    if (geoAreasData.length === 0) {
      areasContainer.style.display = '';
      areaList.innerHTML = '<p style="padding:20px;color:var(--text-secondary)">No areas found for this geography level. The variable label may not match exactly.</p>';
      return;
    }

    areasContainer.style.display = '';

    const savedGeo = state.geography;
    const isAll = savedGeo && savedGeo.type_label === typeLabel && savedGeo.selections === 'all';
    const selectedSet = isAll
      ? new Set(geoAreasData.map(a => a.label))
      : new Set(savedGeo && savedGeo.type_label === typeLabel ? savedGeo.selections || [] : []);

    areaList.innerHTML = geoAreasData.map(a => `
      <div class="checklist-item" data-label="${escapeAttr(a.label)}">
        <input type="checkbox" id="geo-${a.id}" data-label="${escapeAttr(a.label)}" ${selectedSet.has(a.label) ? 'checked' : ''}>
        <label for="geo-${a.id}">${escapeHtml(a.label)}</label>
      </div>
    `).join('');

    updateGeoCount();

    // Select All / Deselect All
    document.getElementById('geo-select-all').onclick = () => {
      areaList.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
      updateGeoSelection(typeLabel);
    };
    document.getElementById('geo-deselect-all').onclick = () => {
      areaList.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
      updateGeoSelection(typeLabel);
    };

    // Individual changes
    areaList.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', () => updateGeoSelection(typeLabel));
    });

    // Filter
    const filterInput = document.getElementById('geo-filter');
    filterInput.value = '';
    filterInput.addEventListener('input', (e) => {
      const filter = e.target.value.toLowerCase();
      areaList.querySelectorAll('.checklist-item').forEach(item => {
        const label = item.dataset.label.toLowerCase();
        item.classList.toggle('hidden', filter && !label.includes(filter));
      });
    });
  }

  function updateGeoSelection(typeLabel) {
    const areaList = document.getElementById('geo-area-list');
    const checkboxes = areaList.querySelectorAll('input[type="checkbox"]');
    const selected = [];
    checkboxes.forEach(cb => {
      if (cb.checked) selected.push(cb.dataset.label);
    });

    if (selected.length === 0) {
      state.geography = null;
    } else {
      const isAll = selected.length === geoAreasData.length;
      state.geography = {
        type_label: typeLabel,
        total_areas: geoAreasData.length,
        selections: isAll ? 'all' : selected,
        effective_count: selected.length,
      };
    }

    updateGeoCount();
    updateCellCountBar();
    saveState();
  }

  function updateGeoCount() {
    const areaList = document.getElementById('geo-area-list');
    const countEl = document.getElementById('geo-count');
    const total = areaList.querySelectorAll('input[type="checkbox"]').length;
    const selected = areaList.querySelectorAll('input[type="checkbox"]:checked').length;
    countEl.textContent = `${selected} of ${total} selected`;
  }

  // ── Step 4: Review & Export ────────────────────────────────────────────────

  function renderReview() {
    const container = document.getElementById('review-content');
    const ds = state.dataset;
    const vars = state.selected_variables;
    const geo = state.geography;
    const cells = state.cell_estimate;
    const splitPlan = computeSplitPlan();

    let html = '';

    // Dataset section
    html += `
      <div class="review-section">
        <div class="review-section-header">
          <h3>Dataset</h3>
          <a class="edit-link" data-goto="1">Edit</a>
        </div>
        <div class="review-item">
          <span class="value">${escapeHtml(ds.name)}</span>
          <span class="badge ${ds.type === 'census' ? 'badge-census' : 'badge-survey'}" style="margin-left:8px">${ds.type}</span>
        </div>
      </div>
    `;

    // Variables section
    html += `
      <div class="review-section">
        <div class="review-section-header">
          <h3>Variables (${vars.length})</h3>
          <a class="edit-link" data-goto="2">Edit</a>
        </div>
    `;
    for (const v of vars) {
      const catSummary = v.selected_categories === 'all'
        ? `All ${v.total_categories} categories`
        : `${v.effective_count} categories: ${v.selected_categories.slice(0, 5).join(', ')}${v.selected_categories.length > 5 ? '...' : ''}`;
      html += `
        <div class="review-item">
          <div class="label">${escapeHtml(v.group_path)}</div>
          <div class="value">
            ${v.code ? `<span class="var-code">${escapeHtml(v.code)}</span> ` : ''}${escapeHtml(v.label)}
          </div>
          <div style="font-size:13px;color:var(--text-secondary)">${escapeHtml(catSummary)}</div>
        </div>
      `;
    }
    html += '</div>';

    // Geography section (for datasets with geography data)
    if (datasetHasGeo()) {
      html += `
        <div class="review-section">
          <div class="review-section-header">
            <h3>Geography</h3>
            <a class="edit-link" data-goto="3">Edit</a>
          </div>
      `;
      if (geo) {
        const areasSummary = geo.selections === 'all'
          ? `All ${geo.total_areas} areas`
          : `${geo.effective_count} areas: ${geo.selections.slice(0, 5).join(', ')}${geo.selections.length > 5 ? '...' : ''}`;
        html += `
          <div class="review-item">
            <div class="value">${escapeHtml(geo.type_label)}</div>
            <div style="font-size:13px;color:var(--text-secondary)">${escapeHtml(areasSummary)}</div>
          </div>
        `;
      } else {
        html += '<div class="review-item"><span class="value" style="color:var(--text-secondary)">No geography selected</span></div>';
      }
      html += '</div>';
    }

    // Query mode section
    const isPairwise = state.query_mode === 'pairwise' && vars.length >= 2;
    html += `
      <div class="review-section">
        <div class="review-section-header">
          <h3>Query Mode</h3>
          <a class="edit-link" data-goto="2">Edit</a>
        </div>
        <div class="review-item">
          <span class="value">${isPairwise ? 'Pairwise' : 'Cross-tab'}</span>
          <span style="font-size:13px;color:var(--text-secondary);margin-left:8px">
            ${isPairwise
              ? 'One query per pair of variables (' + countPairs() + ' pairs)'
              : 'Full Cartesian product of all variables'}
          </span>
        </div>
      </div>
    `;

    // Cell estimate section
    const pct = ((cells / CELL_LIMIT) * 100);
    const statusClass = pct <= 80 ? 'status-green' : pct <= 100 ? 'status-amber' : 'status-red';
    html += `
      <div class="review-section">
        <div class="review-section-header">
          <h3>Cell Estimate</h3>
        </div>
        <div class="review-item" style="display:flex;align-items:center;gap:12px">
          <span class="value" style="font-size:18px">${cells.toLocaleString()} cells${isPairwise ? ' (largest pair)' : ''}</span>
          <span class="status-badge ${statusClass}">${pct.toFixed(1)}% of limit</span>
        </div>
      </div>
    `;

    // Pairwise plan section
    if (isPairwise) {
      const geoMultiplier = (geo && geo.effective_count > 0) ? geo.effective_count : 1;
      html += `
        <div class="review-section">
          <div class="review-section-header">
            <h3>Pairwise Queries (${countPairs()} sub-queries)</h3>
          </div>
          <div class="subquery-list">
      `;
      let idx = 0;
      const showMax = 15;
      const totalPairs = countPairs();
      for (let i = 0; i < vars.length && idx < showMax; i++) {
        for (let j = i + 1; j < vars.length && idx < showMax; j++) {
          idx++;
          const pairCells = vars[i].effective_count * vars[j].effective_count * geoMultiplier;
          const v1 = vars[i].code || vars[i].label;
          const v2 = vars[j].code || vars[j].label;
          html += `
            <div class="subquery-item">
              <div class="sq-header">Pair ${idx}: ${escapeHtml(v1)} × ${escapeHtml(v2)} (${pairCells.toLocaleString()} cells)</div>
            </div>
          `;
        }
      }
      if (totalPairs > showMax) {
        html += `<div class="subquery-item" style="text-align:center;color:var(--text-secondary)">... and ${totalPairs - showMax} more pairs</div>`;
      }
      html += '</div></div>';
    }

    // Split plan section (cross-tab mode only)
    if (!isPairwise && splitPlan) {
      html += `
        <div class="review-section">
          <div class="review-section-header">
            <h3>Split Plan (${splitPlan.chunks.length} sub-queries)</h3>
          </div>
          <div class="review-item">
            <div class="label">Split variable</div>
            <div class="value">${escapeHtml(splitPlan.splitVar.label)} (${escapeHtml(splitPlan.splitVar.code || 'no code')})</div>
            <div style="font-size:13px;color:var(--text-secondary)">Max ${splitPlan.maxCatsPerQ} categories per sub-query</div>
          </div>
          <div class="subquery-list">
      `;
      const showMax = 10;
      for (let i = 0; i < Math.min(splitPlan.chunks.length, showMax); i++) {
        const chunk = splitPlan.chunks[i];
        const subCells = chunk.length * splitPlan.otherCells;
        html += `
          <div class="subquery-item">
            <div class="sq-header">Sub-query ${i + 1}: ${chunk.length} categories (${subCells.toLocaleString()} cells)</div>
            <div style="font-size:12px;color:var(--text-secondary)">${chunk.slice(0, 5).map(escapeHtml).join(', ')}${chunk.length > 5 ? '...' : ''}</div>
          </div>
        `;
      }
      if (splitPlan.chunks.length > showMax) {
        html += `<div class="subquery-item" style="text-align:center;color:var(--text-secondary)">... and ${splitPlan.chunks.length - showMax} more sub-queries</div>`;
      }
      html += '</div></div>';
    }

    container.innerHTML = html;

    // Edit link handlers
    container.querySelectorAll('.edit-link').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        goToStep(parseInt(link.dataset.goto));
      });
    });
  }

  // ── Utilities ──────────────────────────────────────────────────────────────

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function escapeAttr(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // ── Initialization ────────────────────────────────────────────────────────

  async function init() {
    try {
      await initDatabase();
    } catch (err) {
      document.getElementById('loading-overlay').innerHTML = `
        <div class="loading-content">
          <p style="color:var(--red);font-weight:600">Failed to load database</p>
          <p class="loading-sub">${escapeHtml(err.message)}</p>
          <p class="loading-sub" style="margin-top:12px">
            Copy or symlink <code>~/.tablebuilder/dictionary.db</code> to the same directory as <code>index.html</code>.
          </p>
        </div>
      `;
      return;
    }

    // Load saved state
    const hadSavedState = loadState();

    // Init Step 1
    initStep1();

    // Navigation buttons
    document.getElementById('btn-next').addEventListener('click', () => {
      goToStep(state.step + 1);
    });
    document.getElementById('btn-back').addEventListener('click', () => {
      goToStep(state.step - 1);
    });

    // Progress bar clicks
    document.querySelectorAll('#progress-bar .step').forEach(step => {
      step.addEventListener('click', () => {
        if (step.classList.contains('disabled')) return;
        const targetStep = parseInt(step.dataset.step);
        // Only allow going to steps we've reached
        if (targetStep <= state.step || (state.dataset && targetStep <= 4)) {
          goToStep(targetStep);
        }
      });
    });

    // Download button
    document.getElementById('download-json').addEventListener('click', downloadJSON);

    // Mode toggle (Cross-tab / Pairwise)
    document.querySelectorAll('.mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.query_mode = btn.dataset.mode;
        const desc = document.getElementById('mode-description');
        if (state.query_mode === 'pairwise') {
          desc.textContent = 'One sub-query per pair of variables. Higher data quality, less sparsity.';
        } else {
          desc.textContent = 'Full Cartesian product of all selected variables.';
        }
        updateCellCountBar();
        saveState();
      });
    });

    // Restore to saved step
    if (hadSavedState && state.dataset) {
      goToStep(state.step);
    } else {
      goToStep(1);
    }
  }

  init();
})();
