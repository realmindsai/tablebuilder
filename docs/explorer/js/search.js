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
        if (DictDB.isReady()) {
            return DictDB.searchFTS(query, limit);
        }
        // Fallback to Fuse if DB not loaded yet
        if (fuse) {
            return fuse.search(query, { limit }).map(r => r.item);
        }
        return [];
    }

    return { loadIndex, isIndexReady, fuzzySearch, fullSearch };
})();
