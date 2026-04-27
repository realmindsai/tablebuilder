// src/dict-builder/types.ts

export interface ExtractedVariable {
  code: string;             // e.g. "STRD" or "SA1MAIN_2021"
  label: string;            // e.g. "State/Territory" (no count, no code)
  category_count: number;   // parsed from "(N)" in the raw label
  categories: string[];     // empty when category_count > 100
}

export interface ExtractedGroup {
  label: string;            // local group label, e.g. "LGA (2021 Boundaries)"
  path: string;             // " > "-joined ancestors, e.g. "Geographical Areas (Usual Residence) > LGA (2021 Boundaries)"
  variables: ExtractedVariable[];
}

export interface ExtractedDataset {
  dataset_name: string;
  geographies: string[];    // classification-release leaves (no checkbox)
  groups: ExtractedGroup[];
  scraped_at: string;       // ISO 8601 UTC timestamp
  tree_node_count: number;  // raw .treeNodeElement count, for diagnostics
}

export interface ScrapeError {
  dataset_name: string;
  error: string;
  stack?: string;
  failed_at: string;
  attempt: number;
}

export interface RunSummary {
  total: number;
  succeeded: number;
  failed: number;
  failed_datasets: string[];
  started_at: string;
  finished_at: string;
}
