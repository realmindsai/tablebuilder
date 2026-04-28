// src/dict-builder/assembler.ts
import { promises as fs } from 'fs';
import Database from 'better-sqlite3';
import { readAllSuccessCaches } from './cache.js';
import type { ExtractedDataset } from './types.js';

// Inlined schema — single source of truth. The category_count column is the
// only addition over what shipped in the legacy DB.
const SCHEMA_SQL = `
CREATE TABLE datasets (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE geographies (
  id INTEGER PRIMARY KEY,
  dataset_id INTEGER NOT NULL REFERENCES datasets(id),
  label TEXT NOT NULL
);
CREATE TABLE groups (
  id INTEGER PRIMARY KEY,
  dataset_id INTEGER NOT NULL REFERENCES datasets(id),
  label TEXT NOT NULL,
  path TEXT NOT NULL
);
CREATE TABLE variables (
  id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES groups(id),
  code TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL,
  category_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE categories (
  id INTEGER PRIMARY KEY,
  variable_id INTEGER NOT NULL REFERENCES variables(id),
  label TEXT NOT NULL
);
CREATE INDEX idx_geographies_dataset ON geographies(dataset_id);
CREATE INDEX idx_groups_dataset ON groups(dataset_id);
CREATE INDEX idx_variables_group ON variables(group_id);
CREATE INDEX idx_categories_variable ON categories(variable_id);
`;

const FTS_SQL = `
CREATE VIRTUAL TABLE datasets_fts USING fts5(name, summary);
CREATE VIRTUAL TABLE variables_fts USING fts5(
  dataset_name, group_path, code, label, categories_text, summary
);
INSERT INTO datasets_fts (rowid, name, summary)
  SELECT id, name, summary FROM datasets;
INSERT INTO variables_fts (rowid, dataset_name, group_path, code, label, categories_text, summary)
  SELECT v.id,
         d.name,
         g.path,
         v.code,
         v.label,
         COALESCE((SELECT GROUP_CONCAT(c.label, ' ') FROM categories c WHERE c.variable_id = v.id), ''),
         ''
  FROM variables v
  JOIN groups g ON g.id = v.group_id
  JOIN datasets d ON d.id = g.dataset_id;
`;

function sortedDatasets(caches: ExtractedDataset[]): ExtractedDataset[] {
  // Sort datasets by name; sort groups within each dataset by path; sort
  // variables within each group by code; preserve categories order from
  // cache (it reflects ABS site display order).
  return [...caches]
    .sort((a, b) => a.dataset_name.localeCompare(b.dataset_name))
    .map(d => ({
      ...d,
      groups: [...d.groups]
        .sort((a, b) => a.path.localeCompare(b.path))
        .map(g => ({
          ...g,
          variables: [...g.variables].sort((a, b) => a.code.localeCompare(b.code)),
        })),
    }));
}

export async function build(cacheDir: string, dbPath: string): Promise<void> {
  const tmpPath = `${dbPath}.tmp`;
  // Clean slate — never start from a partially-populated tmp file
  await fs.rm(tmpPath, { force: true });

  const datasets = sortedDatasets(await readAllSuccessCaches(cacheDir));

  const db = new Database(tmpPath);
  try {
    db.pragma('journal_mode = WAL');
    db.exec(SCHEMA_SQL);

    const insertDataset = db.prepare(
      'INSERT INTO datasets (name, summary) VALUES (?, ?)',
    );
    const insertGeography = db.prepare(
      'INSERT INTO geographies (dataset_id, label) VALUES (?, ?)',
    );
    const insertGroup = db.prepare(
      'INSERT INTO groups (dataset_id, label, path) VALUES (?, ?, ?)',
    );
    const insertVariable = db.prepare(
      'INSERT INTO variables (group_id, code, label, category_count) VALUES (?, ?, ?, ?)',
    );
    const insertCategory = db.prepare(
      'INSERT INTO categories (variable_id, label) VALUES (?, ?)',
    );

    for (const d of datasets) {
      const tx = db.transaction(() => {
        const datasetId = insertDataset.run(
          d.dataset_name,
          '',
        ).lastInsertRowid as number;

        for (const geo of d.geographies) {
          insertGeography.run(datasetId, geo);
        }

        for (const g of d.groups) {
          const groupId = insertGroup.run(datasetId, g.label, g.path).lastInsertRowid as number;
          for (const v of g.variables) {
            const varId = insertVariable.run(groupId, v.code, v.label, v.category_count).lastInsertRowid as number;
            for (const cat of v.categories) {
              insertCategory.run(varId, cat);
            }
          }
        }
      });
      tx();
    }

    // FTS: rebuild from scratch using base tables
    db.exec(FTS_SQL);
  } finally {
    db.close();
  }

  await fs.rename(tmpPath, dbPath);
}
