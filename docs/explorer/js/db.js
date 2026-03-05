// ABOUTME: SQLite database loader using sql.js (WASM).
// ABOUTME: Loads dictionary.db with progress tracking, exposes query API.

const DictDB = (() => {
    let db = null;
    let ready = false;

    async function load(onProgress) {
        const sqlPromise = initSqlJs({
            locateFile: file => `vendor/${file}`
        });

        const dbData = await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open("GET", "data/dictionary.db", true);
            xhr.responseType = "arraybuffer";
            xhr.onprogress = (e) => {
                if (e.lengthComputable && onProgress) {
                    onProgress(e.loaded / e.total);
                }
            };
            xhr.onload = () => {
                if (xhr.status === 200) resolve(new Uint8Array(xhr.response));
                else reject(new Error(`Failed to load DB: ${xhr.status}`));
            };
            xhr.onerror = () => reject(new Error("Network error loading DB"));
            xhr.send();
        });

        const SQL = await sqlPromise;
        db = new SQL.Database(dbData);
        ready = true;
    }

    function isReady() { return ready; }

    function query(sql, params) {
        if (!db) throw new Error("Database not loaded");
        const stmt = db.prepare(sql);
        if (params) stmt.bind(params);
        const results = [];
        while (stmt.step()) {
            results.push(stmt.getAsObject());
        }
        stmt.free();
        return results;
    }

    function searchFTS(queryText, limit = 30) {
        if (!db) return [];
        try {
            return query(
                `SELECT dataset_name, group_path, code, label, categories_text
                 FROM variables_fts
                 WHERE variables_fts MATCH ?
                 ORDER BY rank LIMIT ?`,
                [queryText, limit]
            );
        } catch (e) {
            // FTS5 syntax error (unbalanced quotes, etc) — fall back to prefix
            const escaped = queryText.replace(/['"]/g, "");
            if (!escaped) return [];
            try {
                return query(
                    `SELECT dataset_name, group_path, code, label, categories_text
                     FROM variables_fts
                     WHERE variables_fts MATCH ?
                     ORDER BY rank LIMIT ?`,
                    [`"${escaped}"*`, limit]
                );
            } catch (_) {
                return [];
            }
        }
    }

    function getDataset(name) {
        if (!db) return null;
        const ds = query(
            "SELECT id, name, geographies_json, summary FROM datasets WHERE name = ?",
            [name]
        );
        if (!ds.length) return null;

        const d = ds[0];
        const groups = query(
            "SELECT id, path FROM groups WHERE dataset_id = ? ORDER BY path",
            [d.id]
        );

        const result = {
            name: d.name,
            geographies: JSON.parse(d.geographies_json || "[]"),
            summary: d.summary,
            groups: []
        };

        for (const grp of groups) {
            const vars = query(
                "SELECT id, code, label FROM variables WHERE group_id = ? ORDER BY label",
                [grp.id]
            );
            const groupData = { path: grp.path, variables: [] };
            for (const v of vars) {
                const cats = query(
                    "SELECT label FROM categories WHERE variable_id = ? ORDER BY label",
                    [v.id]
                );
                groupData.variables.push({
                    id: v.id,
                    code: v.code,
                    label: v.label,
                    categories: cats.map(c => c.label)
                });
            }
            result.groups.push(groupData);
        }
        return result;
    }

    function getVariablesByCode(code) {
        if (!db) return [];
        return query(
            `SELECT v.id, v.code, v.label, d.name as dataset_name, g.path as group_path
             FROM variables v
             JOIN groups g ON v.group_id = g.id
             JOIN datasets d ON g.dataset_id = d.id
             WHERE v.code = ? ORDER BY d.name`,
            [code]
        );
    }

    return { load, isReady, query, searchFTS, getDataset, getVariablesByCode };
})();
