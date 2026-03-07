# ABS Data Dictionary Explorer — User Manual

## What Is This?

A browser-based tool for searching and browsing the Australian Bureau of Statistics (ABS) TableBuilder data dictionary. It covers 131 datasets, 36,000 variables, and 317,000 categories — all searchable without an ABS account.

**URL:** [realmindsai.github.io/tablebuilder](https://realmindsai.github.io/tablebuilder)

---

## First Visit

On your first visit, the app downloads two files:

| File | Size | Purpose |
|------|------|---------|
| Search index | ~12 MB | Powers instant fuzzy typeahead |
| SQLite database | ~49 MB | Powers ranked full-text search and dataset browsing |

A progress bar shows download status. After the first load, your browser caches both files — subsequent visits are near-instant.

---

## Navigation

| Element | Action |
|---------|--------|
| **RMAI logo** (top left) | Opens realmindsai.com.au in a new tab |
| **Title text** ("ABS Data Dictionary Explorer") | Returns to the home/search view |
| **Back arrow buttons** | Navigate back from dataset or variable views |
| **Browser back/forward** | Full history support via hash routing |

---

## Searching

### Typeahead (instant, fuzzy)

Start typing in the search box. After 2 characters, a dropdown appears with up to 8 matches.

- **Typo-tolerant** — "remotness" finds "Remoteness Areas"
- **Searches across** variable labels, codes, dataset names, categories, and group paths
- **Keyboard navigation** — Arrow keys to move, Enter to select, Escape to close

### Full Results (ranked)

After a short pause (300ms), ranked results appear below the search box as cards showing:

- Variable label and code
- Dataset name
- Group path
- Category preview

Click any result card to see the full variable detail.

### Search Tips

| To find... | Try searching... |
|-----------|-----------------|
| A specific variable | Its label: "country of birth" |
| A variable code | The code directly: "SEXP" or "ANCP" |
| Variables in a topic | A keyword: "employment" or "income" |
| Categories within variables | A category value: "Major Cities" or "Buddhism" |

---

## Browse View

Below the search box, the home page lists all 131 datasets alphabetically. Click any dataset to explore it.

---

## Dataset View

Shows the full structure of a single dataset:

- **Header** — dataset name and summary
- **Geography tags** — available geographic levels (for Census datasets)
- **Variable groups** — collapsible sections mirroring the ABS TableBuilder tree

Click a group header to expand/collapse it. Each variable shows its code and category count. Click a variable to see its detail.

---

## Variable Detail View

Shows everything about a single variable:

- **Label and code** — the variable name and its ABS code
- **Dataset and group path** — where this variable lives
- **Categories** — every category value displayed in a grid
- **Cross-references** — if this variable code appears in other datasets, they're listed at the bottom. Click any cross-reference to jump to that dataset's version.

---

## Offline Use

After the first visit, the app works offline if your browser has cached the data files. No server or API calls are made — everything runs in your browser.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Loading stuck at 0% | Check your internet connection; the 49MB database needs to download |
| "Database load failed" | Try refreshing; if persistent, clear browser cache and reload |
| Search returns no results | Try shorter or broader terms; FTS5 matches whole words |
| Typeahead works but full results don't | The SQLite database may still be loading; wait for progress to finish |
| Page looks broken on mobile | Supported but optimised for desktop; try landscape orientation |

---

## Technical Details

- **No backend** — entirely client-side static files
- **Fuse.js** — fuzzy search library for typeahead
- **sql.js** — SQLite compiled to WebAssembly, runs FTS5 queries in your browser
- **Data source** — extracted from [ABS TableBuilder](https://tablebuilder.abs.gov.au) using the tablebuilder CLI tool

---

*Built by [Real Minds Artificial Intelligence](https://realmindsai.com.au)*
