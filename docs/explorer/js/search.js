// ABOUTME: Dual search engine — Fuse.js for fuzzy typeahead, sql.js FTS5 for ranked results.
// ABOUTME: Loads variables_index.json for Fuse, delegates to DictDB for FTS5.

const Search = (() => {
    let fuse = null;
    let indexReady = false;

    async function loadIndex() {
        const resp = await fetch("data/variables_index.json");
        const data = await resp.json();
        fuse = new Fuse(data, {
            keys: [
                { name: "label", weight: 3 },
                { name: "code", weight: 2 },
                { name: "dataset_name", weight: 1 },
                { name: "categories_preview", weight: 0.5 },
                { name: "group_path", weight: 0.5 }
            ],
            threshold: 0.35,
            distance: 100,
            includeScore: true,
            minMatchCharLength: 2,
            useExtendedSearch: true,
            limit: 10
        });
        indexReady = true;
    }

    function isIndexReady() { return indexReady; }

    function fuzzySearch(query, limit = 8) {
        if (!fuse || !query || query.length < 2) return [];
        return fuse.search(query, { limit }).map(r => r.item);
    }

    function fullSearch(query, limit = 30) {
        // Try FTS5 first, fall back to Fuse if FTS5 returns nothing or errors
        if (DictDB.isReady()) {
            const ftsResults = DictDB.searchFTS(query, limit);
            if (ftsResults.length) return ftsResults;
        }
        // Fuse fallback — covers: DB not loaded, FTS5 empty, FTS5 errors
        if (!fuse) return [];

        // For multi-word queries, search each word individually and merge results.
        // This finds "Sex" and "Age" when the user types "age and sex".
        const words = query.split(/\s+/).filter(w => w.length >= 2 && w.toLowerCase() !== "and" && w.toLowerCase() !== "or");
        if (words.length <= 1) {
            return fuse.search(query, { limit }).map(r => r.item);
        }

        // Search each word, deduplicate by variable identity (code+label+dataset)
        const seen = new Set();
        const merged = [];
        for (const word of words) {
            for (const r of fuse.search(word, { limit })) {
                const key = `${r.item.code}|${r.item.label}|${r.item.dataset_name}`;
                if (!seen.has(key)) {
                    seen.add(key);
                    merged.push(r.item);
                }
            }
        }
        return merged.slice(0, limit);
    }

    return { loadIndex, isIndexReady, fuzzySearch, fullSearch };
})();
