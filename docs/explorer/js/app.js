// ABOUTME: Split-panel workbench app for the ABS Dictionary Explorer.
// ABOUTME: Sidebar search/browse + detail panel with clickable code pills and inline expansion.

const App = (() => {
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    let datasets = [];
    let debounceTimer = null;
    let activeNavItem = null;

    // ── Loading ──
    async function init() {
        updateLoadingStatus("Loading search index...");
        try {
            await Search.loadIndex();
            updateLoadingStatus("Search ready! Loading full database...");
        } catch (e) {
            updateLoadingStatus("Warning: fuzzy search unavailable");
        }

        try {
            const resp = await fetch("data/datasets.json");
            datasets = await resp.json();
        } catch (_) {}

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

        // Fade out loading overlay
        const overlay = $("#loading-overlay");
        overlay.classList.add("fade-out");
        setTimeout(() => overlay.remove(), 500);

        setupTabs();
        setupSearch();
        setupRouting();
        renderBrowseTree();
        handleRoute();
    }

    function updateLoadingStatus(msg) {
        const el = $("#loading-status");
        if (el) el.textContent = msg;
    }

    // ── Tabs ──
    function setupTabs() {
        $$(".nav-tab").forEach(tab => {
            tab.addEventListener("click", () => {
                $$(".nav-tab").forEach(t => t.classList.remove("active"));
                tab.classList.add("active");
                $$(".tab-panel").forEach(p => p.classList.remove("active"));
                $(`#${tab.dataset.tab}-panel`).classList.add("active");
            });
        });
    }

    function switchToTab(name) {
        $$(".nav-tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
        $$(".tab-panel").forEach(p => p.classList.remove("active"));
        $(`#${name}-panel`).classList.add("active");
    }

    // ── Routing ──
    function setupRouting() {
        window.addEventListener("hashchange", handleRoute);
    }

    function handleRoute() {
        const hash = location.hash || "#";
        if (hash.startsWith("#dataset/")) {
            const name = decodeURIComponent(hash.slice(9));
            renderDatasetDetail(name);
        } else if (hash.startsWith("#variable/")) {
            const parts = hash.slice(10).split("/");
            const code = decodeURIComponent(parts[0]);
            const dataset = parts[1] ? decodeURIComponent(parts[1]) : null;
            renderVariableDetail(code, dataset);
        } else {
            renderWelcome();
        }
    }

    // ── Search ──
    function setupSearch() {
        const input = $("#search-input");

        // "/" shortcut to focus
        document.addEventListener("keydown", (e) => {
            if (e.key === "/" && document.activeElement !== input) {
                e.preventDefault();
                input.focus();
                switchToTab("results");
            }
        });

        input.addEventListener("input", () => {
            clearTimeout(debounceTimer);
            const q = input.value.trim();
            if (q.length < 2) {
                clearResults();
                return;
            }
            switchToTab("results");
            debounceTimer = setTimeout(() => {
                renderSearchResults(Search.fullSearch(q));
            }, 200);
        });

        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                const q = input.value.trim();
                if (q.length >= 2) {
                    renderSearchResults(Search.fullSearch(q));
                }
            } else if (e.key === "Escape") {
                input.blur();
            }
        });

        // Welcome hint pills
        document.addEventListener("click", (e) => {
            const hint = e.target.closest(".hint-pill");
            if (hint) {
                input.value = hint.dataset.query;
                input.focus();
                switchToTab("results");
                renderSearchResults(Search.fullSearch(hint.dataset.query));
            }
        });

        // Global code pill click handler
        document.addEventListener("click", (e) => {
            const pill = e.target.closest(".code-pill");
            if (pill && pill.dataset.code) {
                e.stopPropagation();
                const code = pill.dataset.code;
                const dataset = pill.dataset.dataset || null;
                if (dataset) {
                    location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(dataset)}`;
                } else {
                    location.hash = `#variable/${encodeURIComponent(code)}`;
                }
            }
        });
    }

    function clearResults() {
        $("#results-list").innerHTML = "";
        $("#results-status").textContent = "";
    }

    function renderSearchResults(results) {
        const container = $("#results-list");
        const status = $("#results-status");

        if (!results.length) {
            status.textContent = "No results found";
            container.innerHTML = "";
            return;
        }

        // Group by label to deduplicate variables across datasets
        const grouped = new Map();
        for (const r of results) {
            const key = (r.label || "").toLowerCase();
            if (!grouped.has(key)) {
                grouped.set(key, { code: r.code || "", label: r.label, datasets: [], codeDataset: null });
            }
            const g = grouped.get(key);
            // Prefer a code over no code; track a dataset that has the code
            if (r.code) {
                if (!g.code) g.code = r.code;
                if (!g.codeDataset) g.codeDataset = r.dataset_name;
            }
            g.datasets.push(r.dataset_name);
        }

        const groups = [...grouped.values()];
        status.textContent = `${groups.length} variable${groups.length === 1 ? "" : "s"}`;

        container.innerHTML = groups.map(g => {
            const dsCount = g.datasets.length;
            const dsLabel = dsCount === 1
                ? esc(g.datasets[0])
                : `${dsCount} datasets`;
            // Use a dataset that has the code for navigation, else first dataset
            const defaultDs = g.codeDataset || g.datasets[0];
            return `
                <div class="nav-item" data-code="${esc(g.code)}" data-dataset="${esc(defaultDs)}">
                    <div class="nav-item-label">
                        ${g.code ? `<span class="code-pill" data-code="${esc(g.code)}" data-dataset="${esc(defaultDs)}">${esc(g.code)}</span>` : ""}
                        <span>${esc(g.label)}</span>
                    </div>
                    <div class="nav-item-meta">${dsLabel}</div>
                </div>
            `;
        }).join("");

        container.querySelectorAll(".nav-item").forEach(item => {
            item.addEventListener("click", (e) => {
                if (e.target.closest(".code-pill")) return;
                setActiveNavItem(item);
                const code = item.dataset.code;
                const dataset = item.dataset.dataset;
                if (code) {
                    location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(dataset)}`;
                } else {
                    location.hash = `#dataset/${encodeURIComponent(dataset)}`;
                }
            });
        });
    }

    function setActiveNavItem(el) {
        if (activeNavItem) activeNavItem.classList.remove("active");
        if (el) el.classList.add("active");
        activeNavItem = el;
    }

    // ── Browse Tree ──
    function renderBrowseTree() {
        const container = $("#dataset-tree");
        container.innerHTML = datasets.map(ds => `
            <div class="tree-dataset" data-name="${esc(ds.name)}">
                <div class="tree-dataset-header">
                    <span class="tree-toggle">&#x25B6;</span>
                    <span class="tree-dataset-name">${esc(ds.name)}</span>
                </div>
                <div class="tree-children"></div>
            </div>
        `).join("");

        container.querySelectorAll(".tree-dataset-header").forEach(header => {
            header.addEventListener("click", () => {
                const ds = header.closest(".tree-dataset");
                const children = ds.querySelector(".tree-children");
                const toggle = header.querySelector(".tree-toggle");
                const isOpen = children.classList.contains("open");

                if (isOpen) {
                    children.classList.remove("open");
                    toggle.classList.remove("open");
                } else {
                    toggle.classList.add("open");
                    children.classList.add("open");
                    // Lazy-load tree content
                    if (!children.dataset.loaded) {
                        loadDatasetTree(ds.dataset.name, children);
                        children.dataset.loaded = "true";
                    }
                }

                // Also show dataset detail
                location.hash = `#dataset/${encodeURIComponent(ds.dataset.name)}`;
            });
        });
    }

    function loadDatasetTree(name, container) {
        if (!DictDB.isReady()) {
            container.innerHTML = '<div style="padding:8px 16px;font-size:12px;color:#5C5D69;">Loading...</div>';
            return;
        }

        const ds = DictDB.getDataset(name);
        if (!ds) return;

        container.innerHTML = ds.groups.map(grp => `
            <div class="tree-group">
                <div class="tree-group-header">
                    <span class="tree-toggle">&#x25B6;</span>
                    <span>${esc(grp.path)}</span>
                </div>
                <div class="tree-children">
                    ${grp.variables.map(v => `
                        <div class="tree-variable" data-code="${esc(v.code)}" data-dataset="${esc(name)}">
                            ${v.code ? `<span class="code-pill" data-code="${esc(v.code)}" data-dataset="${esc(name)}">${esc(v.code)}</span>` : ""}
                            <span>${esc(v.label)}</span>
                        </div>
                    `).join("")}
                </div>
            </div>
        `).join("");

        // Group expand/collapse
        container.querySelectorAll(".tree-group-header").forEach(gh => {
            gh.addEventListener("click", () => {
                const children = gh.nextElementSibling;
                const toggle = gh.querySelector(".tree-toggle");
                children.classList.toggle("open");
                toggle.classList.toggle("open");
            });
        });

        // Variable click
        container.querySelectorAll(".tree-variable").forEach(v => {
            v.addEventListener("click", (e) => {
                if (e.target.closest(".code-pill")) return;
                const code = v.dataset.code;
                const dataset = v.dataset.dataset;
                if (code) {
                    location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(dataset)}`;
                }
            });
        });
    }

    // ── Detail: Welcome ──
    function renderWelcome() {
        setBreadcrumbs([]);
        const content = $("#detail-content");
        content.innerHTML = `
            <div class="welcome-state">
                <div class="welcome-icon">
                    <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
                        <rect x="6" y="6" width="36" height="36" rx="4"/>
                        <line x1="6" y1="18" x2="42" y2="18"/>
                        <line x1="18" y1="18" x2="18" y2="42"/>
                        <line x1="6" y1="28" x2="42" y2="28"/>
                        <line x1="6" y1="36" x2="42" y2="36"/>
                    </svg>
                </div>
                <h2>Explore ABS Data</h2>
                <p>Search for variables, codes, or categories in the box to the left. Or browse datasets by clicking the Browse tab.</p>
                <div class="welcome-hints">
                    <span class="hint-pill" data-query="sex">sex</span>
                    <span class="hint-pill" data-query="income">income</span>
                    <span class="hint-pill" data-query="country of birth">country of birth</span>
                    <span class="hint-pill" data-query="remoteness">remoteness</span>
                    <span class="hint-pill" data-query="employment">employment</span>
                    <span class="hint-pill" data-query="ANCP">ANCP</span>
                </div>
            </div>
        `;
    }

    // ── Detail: Dataset ──
    function renderDatasetDetail(name) {
        const content = $("#detail-content");

        if (!DictDB.isReady()) {
            content.innerHTML = '<p style="color:var(--slate-gray);">Database still loading...</p>';
            return;
        }

        const ds = DictDB.getDataset(name);
        if (!ds) {
            content.innerHTML = `<p style="color:var(--slate-gray);">Dataset "${esc(name)}" not found.</p>`;
            return;
        }

        setBreadcrumbs([{ label: "Datasets", hash: "#" }, { label: name }]);

        const geoHtml = ds.geographies.length
            ? `<div class="geo-tags">${ds.geographies.map(g => `<span class="geo-tag">${esc(g)}</span>`).join("")}</div>`
            : "";

        const totalVars = ds.groups.reduce((sum, g) => sum + g.variables.length, 0);

        content.innerHTML = `
            <div class="detail-header">
                <h2>${esc(ds.name)}</h2>
                <div class="detail-summary">${esc(ds.summary)}</div>
                <div class="detail-summary" style="margin-top:4px;">${ds.groups.length} groups, ${totalVars} variables</div>
                ${geoHtml}
            </div>
            ${ds.groups.map(grp => `
                <div class="group-section">
                    <div class="group-header">
                        <span class="group-toggle">&#x25B6;</span>
                        <span class="group-name">${esc(grp.path)}</span>
                        <span class="group-count">${grp.variables.length}</span>
                    </div>
                    <div class="group-body">
                        ${grp.variables.map(v => `
                            <div class="var-row" data-code="${esc(v.code)}" data-dataset="${esc(name)}">
                                ${v.code ? `<span class="code-pill code-pill-light" data-code="${esc(v.code)}" data-dataset="${esc(name)}">${esc(v.code)}</span>` : ""}
                                <span class="var-row-label">${esc(v.label)}</span>
                                <span class="var-row-count">${v.categories.length} cat</span>
                            </div>
                        `).join("")}
                    </div>
                </div>
            `).join("")}
        `;

        // Group expand/collapse
        content.querySelectorAll(".group-header").forEach(header => {
            header.addEventListener("click", () => {
                const body = header.nextElementSibling;
                const toggle = header.querySelector(".group-toggle");
                body.classList.toggle("open");
                toggle.classList.toggle("open");
            });
        });

        // Variable row click → show variable detail
        content.querySelectorAll(".var-row").forEach(row => {
            row.addEventListener("click", (e) => {
                if (e.target.closest(".code-pill")) return;
                const code = row.dataset.code;
                const dataset = row.dataset.dataset;
                if (code) {
                    location.hash = `#variable/${encodeURIComponent(code)}/${encodeURIComponent(dataset)}`;
                }
            });
        });
    }

    // ── Detail: Variable ──
    function renderVariableDetail(code, datasetName) {
        const content = $("#detail-content");

        if (!DictDB.isReady()) {
            content.innerHTML = '<p style="color:var(--slate-gray);">Database still loading...</p>';
            return;
        }

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

        const crossRefs = DictDB.getVariablesByCode(code);

        if (!variable && crossRefs.length) {
            variable = crossRefs[0];
            const cats = DictDB.query(
                "SELECT label FROM categories WHERE variable_id = ? ORDER BY label",
                [variable.id]
            );
            variable.categories = cats.map(c => c.label);
        }

        if (!variable) {
            content.innerHTML = `<p style="color:var(--slate-gray);">Variable "${esc(code)}" not found.</p>`;
            return;
        }

        const dsName = variable.dataset_name || datasetName;
        setBreadcrumbs([
            { label: "Datasets", hash: "#" },
            { label: dsName, hash: `#dataset/${encodeURIComponent(dsName)}` },
            { label: variable.label }
        ]);

        const crossRefHtml = crossRefs.length > 1
            ? `<div class="cross-ref-section">
                 <h3>Also in ${crossRefs.length} datasets</h3>
                 ${crossRefs.map(cr => `
                     <div class="cross-ref-row" data-code="${esc(code)}" data-dataset="${esc(cr.dataset_name)}">
                         <span class="cross-ref-dataset">${esc(cr.dataset_name)}</span>
                         <span class="cross-ref-group">${esc(cr.group_path)}</span>
                     </div>
                 `).join("")}
               </div>`
            : "";

        content.innerHTML = `
            <div class="var-detail-header">
                <h2>${esc(variable.label)}</h2>
                ${variable.code ? `<div class="var-detail-code"><span class="code-pill code-pill-light" data-code="${esc(variable.code)}">${esc(variable.code)}</span></div>` : ""}
                <div class="var-detail-meta">
                    <span class="crumb" data-hash="#dataset/${encodeURIComponent(dsName)}">${esc(dsName)}</span>
                    <span class="crumb-sep">/</span>
                    <span>${esc(variable.group_path)}</span>
                </div>
            </div>
            <div class="categories-section">
                <h3>Categories (${variable.categories ? variable.categories.length : 0})</h3>
                <div class="categories-grid">
                    ${(variable.categories || []).map(c => `<div class="cat-chip">${esc(c)}</div>`).join("")}
                </div>
            </div>
            ${crossRefHtml}
        `;

        // Clickable crumbs in meta
        content.querySelectorAll(".var-detail-meta .crumb[data-hash]").forEach(crumb => {
            crumb.addEventListener("click", () => {
                location.hash = crumb.dataset.hash;
            });
        });

        // Cross-ref clicks
        content.querySelectorAll(".cross-ref-row").forEach(row => {
            row.addEventListener("click", () => {
                location.hash = `#variable/${encodeURIComponent(row.dataset.code)}/${encodeURIComponent(row.dataset.dataset)}`;
            });
        });
    }

    // ── Breadcrumbs ──
    function setBreadcrumbs(items) {
        const el = $("#breadcrumbs");
        if (!items.length) {
            el.innerHTML = "";
            return;
        }
        el.innerHTML = items.map((item, i) => {
            const isLast = i === items.length - 1;
            if (isLast) return `<span style="color:var(--core-black);font-weight:500;">${esc(item.label)}</span>`;
            return `<span class="crumb" data-hash="${esc(item.hash)}">${esc(item.label)}</span><span class="crumb-sep">&rsaquo;</span>`;
        }).join("");

        el.querySelectorAll(".crumb[data-hash]").forEach(crumb => {
            crumb.addEventListener("click", () => {
                location.hash = crumb.dataset.hash;
            });
        });
    }

    // ── Helpers ──
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

    // ── Start ──
    document.addEventListener("DOMContentLoaded", init);

    return { init };
})();
