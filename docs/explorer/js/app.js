// ABOUTME: Main application logic for the ABS Dictionary Explorer.
// ABOUTME: Handles routing, UI rendering, search interaction, and data loading.

const App = (() => {
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    let datasets = [];
    let debounceTimer = null;
    let selectedTypeaheadIdx = -1;

    // --- Loading ---
    async function init() {
        // Phase 1: Load Fuse index (fast, enables typeahead)
        updateLoadingStatus("Loading search index...");
        try {
            await Search.loadIndex();
            updateLoadingStatus("Search ready! Loading full database...");
        } catch (e) {
            updateLoadingStatus("Warning: fuzzy search unavailable");
        }

        // Load datasets list for browse view
        try {
            const resp = await fetch("data/datasets.json");
            datasets = await resp.json();
        } catch (_) {}

        // Phase 2: Load full SQLite DB (slow, enables FTS5)
        try {
            await DictDB.load((progress) => {
                const pct = Math.round(progress * 100);
                $("#progress-fill").style.width = pct + "%";
                updateLoadingStatus(`Loading database... ${pct}%`);
            });
            updateLoadingStatus("Ready!");
        } catch (e) {
            updateLoadingStatus("Database load failed — using fuzzy search only");
        }

        // Hide loading overlay
        setTimeout(() => {
            $("#loading-overlay").classList.add("hidden");
        }, 300);

        // Set up event listeners
        setupSearch();
        setupRouting();

        // Render initial view
        handleRoute();
        renderBrowseList();
    }

    function updateLoadingStatus(msg) {
        const el = $("#loading-status");
        if (el) el.textContent = msg;
    }

    // --- Routing ---
    function setupRouting() {
        window.addEventListener("hashchange", handleRoute);
    }

    function handleRoute() {
        const hash = location.hash || "#";
        if (hash.startsWith("#dataset/")) {
            const name = decodeURIComponent(hash.slice(9));
            showDatasetView(name);
        } else if (hash.startsWith("#variable/")) {
            const parts = hash.slice(10).split("/");
            const code = decodeURIComponent(parts[0]);
            const dataset = parts[1] ? decodeURIComponent(parts[1]) : null;
            showVariableView(code, dataset);
        } else {
            showSearchView();
        }
    }

    function showSearchView() {
        $("#search-section").classList.remove("hidden");
        $("#dataset-section").classList.add("hidden");
        $("#variable-section").classList.add("hidden");
    }

    function showDatasetView(name) {
        $("#search-section").classList.add("hidden");
        $("#dataset-section").classList.remove("hidden");
        $("#variable-section").classList.add("hidden");
        renderDataset(name);
    }

    function showVariableView(code, dataset) {
        $("#search-section").classList.add("hidden");
        $("#dataset-section").classList.add("hidden");
        $("#variable-section").classList.remove("hidden");
        renderVariable(code, dataset);
    }

    // --- Search ---
    function setupSearch() {
        const input = $("#search-input");
        const dropdown = $("#typeahead-dropdown");

        input.addEventListener("input", () => {
            clearTimeout(debounceTimer);
            const q = input.value.trim();
            if (q.length < 2) {
                hideTypeahead();
                clearResults();
                return;
            }
            // Instant typeahead
            showTypeahead(Search.fuzzySearch(q));
            // Debounced full search
            debounceTimer = setTimeout(() => {
                renderSearchResults(Search.fullSearch(q));
            }, 300);
        });

        input.addEventListener("keydown", (e) => {
            const items = $$(".typeahead-item");
            if (e.key === "ArrowDown") {
                e.preventDefault();
                selectedTypeaheadIdx = Math.min(selectedTypeaheadIdx + 1, items.length - 1);
                updateTypeaheadSelection(items);
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                selectedTypeaheadIdx = Math.max(selectedTypeaheadIdx - 1, -1);
                updateTypeaheadSelection(items);
            } else if (e.key === "Enter") {
                e.preventDefault();
                if (selectedTypeaheadIdx >= 0 && items[selectedTypeaheadIdx]) {
                    items[selectedTypeaheadIdx].click();
                } else {
                    hideTypeahead();
                    renderSearchResults(Search.fullSearch(input.value.trim()));
                }
            } else if (e.key === "Escape") {
                hideTypeahead();
            }
        });

        // Close typeahead when clicking outside
        document.addEventListener("click", (e) => {
            if (!e.target.closest(".search-container")) hideTypeahead();
        });

        // Back buttons
        $("#back-btn").addEventListener("click", () => { location.hash = "#"; });
        $("#var-back-btn").addEventListener("click", () => { history.back(); });
    }

    function showTypeahead(results) {
        const dropdown = $("#typeahead-dropdown");
        selectedTypeaheadIdx = -1;
        if (!results.length) {
            hideTypeahead();
            return;
        }
        dropdown.innerHTML = results.map((r, i) => `
            <div class="typeahead-item" data-index="${i}"
                 data-code="${esc(r.code)}" data-dataset="${esc(r.dataset_name)}">
                <span class="item-label">${esc(r.label)}</span>
                ${r.code ? `<span class="item-code">${esc(r.code)}</span>` : ""}
                <span class="item-dataset">${esc(r.dataset_name)} &rsaquo; ${esc(r.group_path)}</span>
            </div>
        `).join("");
        dropdown.classList.remove("hidden");

        dropdown.querySelectorAll(".typeahead-item").forEach(item => {
            item.addEventListener("click", () => {
                const code = item.dataset.code;
                const dataset = item.dataset.dataset;
                if (code) {
                    location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(dataset)}`;
                } else {
                    location.hash = `#dataset/${encodeURIComponent(dataset)}`;
                }
                hideTypeahead();
            });
        });
    }

    function hideTypeahead() {
        $("#typeahead-dropdown").classList.add("hidden");
        selectedTypeaheadIdx = -1;
    }

    function updateTypeaheadSelection(items) {
        items.forEach((el, i) => {
            el.classList.toggle("active", i === selectedTypeaheadIdx);
        });
    }

    function clearResults() {
        $("#search-results").innerHTML = "";
        $("#search-status").textContent = "";
    }

    // --- Rendering ---
    function renderSearchResults(results) {
        const container = $("#search-results");
        const status = $("#search-status");

        if (!results.length) {
            status.textContent = "No results found.";
            container.innerHTML = "";
            return;
        }

        status.textContent = `${results.length} result${results.length === 1 ? "" : "s"}`;
        container.innerHTML = results.map(r => `
            <div class="result-card" data-code="${esc(r.code)}" data-dataset="${esc(r.dataset_name)}">
                <div>
                    <span class="result-label">${esc(r.label)}</span>
                    ${r.code ? `<span class="result-code">${esc(r.code)}</span>` : ""}
                </div>
                <div class="result-dataset">${esc(r.dataset_name)}</div>
                <div class="result-group">${esc(r.group_path)}</div>
                ${r.categories_text ? `<div class="result-categories">${esc(truncate(r.categories_text, 150))}</div>` : ""}
            </div>
        `).join("");

        container.querySelectorAll(".result-card").forEach(card => {
            card.addEventListener("click", () => {
                const code = card.dataset.code;
                const dataset = card.dataset.dataset;
                if (code) {
                    location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(dataset)}`;
                } else {
                    location.hash = `#dataset/${encodeURIComponent(dataset)}`;
                }
            });
        });
    }

    function renderBrowseList() {
        // Add browse section below search results
        const main = $("main");
        let browseSection = $("#browse-section");
        if (!browseSection) {
            browseSection = document.createElement("section");
            browseSection.id = "browse-section";
            browseSection.className = "browse-header";
            main.appendChild(browseSection);
        }

        browseSection.innerHTML = `
            <h2>Browse All Datasets (${datasets.length})</h2>
            ${datasets.map(ds => `
                <div class="dataset-list-item" data-name="${esc(ds.name)}">
                    <div class="ds-name">${esc(ds.name)}</div>
                    <div class="ds-summary">${esc(truncate(ds.summary, 120))}</div>
                </div>
            `).join("")}
        `;

        browseSection.querySelectorAll(".dataset-list-item").forEach(item => {
            item.addEventListener("click", () => {
                location.hash = `#dataset/${encodeURIComponent(item.dataset.name)}`;
            });
        });
    }

    function renderDataset(name) {
        const container = $("#dataset-detail");
        const ds = DictDB.isReady() ? DictDB.getDataset(name) : null;

        if (!ds) {
            container.innerHTML = `<p>Dataset "${esc(name)}" not found. Database may still be loading.</p>`;
            return;
        }

        const geoHtml = ds.geographies.length
            ? `<div class="dataset-geographies">
                 <strong>Geographies:</strong>
                 ${ds.geographies.map(g => `<span>${esc(g)}</span>`).join("")}
               </div>`
            : "";

        container.innerHTML = `
            <div class="dataset-header">
                <h2>${esc(ds.name)}</h2>
                <div class="dataset-summary">${esc(ds.summary)}</div>
                ${geoHtml}
            </div>
            ${ds.groups.map(grp => `
                <div class="group-section">
                    <div class="group-header" data-expanded="false">
                        <span>${esc(grp.path)} (${grp.variables.length})</span>
                        <span class="toggle">&#x25B6;</span>
                    </div>
                    <div class="group-body hidden">
                        ${grp.variables.map(v => `
                            <div class="variable-row"
                                 data-code="${esc(v.code)}" data-dataset="${esc(name)}">
                                ${v.code ? `<span class="var-code">${esc(v.code)}</span>` : ""}
                                ${esc(v.label)}
                                <span style="color:var(--slate-gray);font-size:12px;margin-left:4px;">(${v.categories.length})</span>
                            </div>
                        `).join("")}
                    </div>
                </div>
            `).join("")}
        `;

        // Group expand/collapse
        container.querySelectorAll(".group-header").forEach(header => {
            header.addEventListener("click", () => {
                const body = header.nextElementSibling;
                const toggle = header.querySelector(".toggle");
                const expanded = header.dataset.expanded === "true";
                body.classList.toggle("hidden", expanded);
                header.dataset.expanded = expanded ? "false" : "true";
                toggle.innerHTML = expanded ? "&#x25B6;" : "&#x25BC;";
            });
        });

        // Variable click
        container.querySelectorAll(".variable-row").forEach(row => {
            row.addEventListener("click", () => {
                const code = row.dataset.code;
                const dataset = row.dataset.dataset;
                if (code) {
                    location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(dataset)}`;
                }
            });
        });
    }

    function renderVariable(code, datasetName) {
        const container = $("#variable-detail");

        if (!DictDB.isReady()) {
            container.innerHTML = "<p>Database still loading...</p>";
            return;
        }

        // Get the specific variable from the dataset context
        let variable = null;
        if (datasetName) {
            const ds = DictDB.getDataset(datasetName);
            if (ds) {
                for (const grp of ds.groups) {
                    for (const v of grp.variables) {
                        if (v.code === code) {
                            variable = { ...v, group_path: grp.path, dataset_name: datasetName };
                            break;
                        }
                    }
                    if (variable) break;
                }
            }
        }

        // Cross-reference: find same code in other datasets
        const crossRefs = DictDB.getVariablesByCode(code);

        if (!variable && crossRefs.length) {
            variable = crossRefs[0];
            // Load categories for this variable
            const cats = DictDB.query(
                "SELECT label FROM categories WHERE variable_id = ? ORDER BY label",
                [variable.id]
            );
            variable.categories = cats.map(c => c.label);
        }

        if (!variable) {
            container.innerHTML = `<p>Variable "${esc(code)}" not found.</p>`;
            return;
        }

        const crossRefHtml = crossRefs.length > 1
            ? `<div class="cross-ref">
                 <h3>Also appears in (${crossRefs.length} datasets)</h3>
                 ${crossRefs.map(cr => `
                     <div class="cross-ref-item" data-dataset="${esc(cr.dataset_name)}">
                         ${esc(cr.dataset_name)} &rsaquo; ${esc(cr.group_path)}
                     </div>
                 `).join("")}
               </div>`
            : "";

        container.innerHTML = `
            <div class="var-detail-header">
                <h2>${esc(variable.label)}</h2>
                ${variable.code ? `<div class="var-detail-code">${esc(variable.code)}</div>` : ""}
                <div class="var-detail-meta">
                    ${esc(variable.dataset_name || datasetName)} &rsaquo; ${esc(variable.group_path)}
                </div>
            </div>
            <h3 style="margin-top:16px;font-size:15px;font-weight:600;">
                Categories (${variable.categories ? variable.categories.length : 0})
            </h3>
            <div class="categories-grid">
                ${(variable.categories || []).map(c => `
                    <div class="category-chip">${esc(c)}</div>
                `).join("")}
            </div>
            ${crossRefHtml}
        `;

        // Cross-ref click
        container.querySelectorAll(".cross-ref-item").forEach(item => {
            item.addEventListener("click", () => {
                location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(item.dataset.dataset)}`;
            });
        });
    }

    // --- Helpers ---
    function esc(str) {
        if (!str) return "";
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function truncate(str, len) {
        if (!str || str.length <= len) return str || "";
        return str.slice(0, len) + "...";
    }

    // --- Start ---
    document.addEventListener("DOMContentLoaded", init);

    return { init };
})();
