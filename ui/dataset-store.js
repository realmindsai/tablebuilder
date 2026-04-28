// ui/dataset-store.js — client-side cache for dataset metadata
// Exposes window.DatasetStore.loadMetadata(datasetId) → Promise<metadata>
// Failures are NOT cached so callers can retry without a page reload.

window.DatasetStore = (() => {
  const cache = new Map();

  function loadMetadata(datasetId) {
    if (cache.has(datasetId)) return cache.get(datasetId);
    const p = fetch(`/api/datasets/${datasetId}/metadata`)
      .then(r => {
        if (!r.ok) {
          cache.delete(datasetId);
          throw new Error(`metadata fetch failed: ${r.status}`);
        }
        return r.json();
      })
      .catch(e => { cache.delete(datasetId); throw e; });
    cache.set(datasetId, p);
    return p;
  }

  return { loadMetadata };
})();
