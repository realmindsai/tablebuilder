# ABOUTME: SQLite database builder and search for the ABS data dictionary.
# ABOUTME: Loads JSON cache into normalized tables with FTS5 full-text search.

import json
import sqlite3
from pathlib import Path

from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.dictionary_db")

DEFAULT_DB_PATH = Path.home() / ".tablebuilder" / "dictionary.db"
DEFAULT_CACHE_DIR = Path.home() / ".tablebuilder" / "dict_cache"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    geographies_json TEXT DEFAULT '[]',
    summary TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id),
    label TEXT NOT NULL,
    path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS variables (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    code TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    variable_id INTEGER NOT NULL REFERENCES variables(id),
    label TEXT NOT NULL
);
"""


def _load_cache(cache_dir: Path) -> list[dict]:
    """Load all JSON files from the cache directory."""
    if not cache_dir.exists():
        return []
    trees = []
    for path in sorted(cache_dir.glob("*.json")):
        try:
            trees.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Skipping corrupt cache file %s: %s", path, exc)
    return trees


def build_db(cache_dir: Path, db_path: Path) -> None:
    """Build the SQLite dictionary database from cached JSON files.

    Drops and recreates all tables, then loads every dataset from the
    cache directory. Idempotent — safe to call repeatedly.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)

    # Drop existing tables for idempotent rebuild
    for table in ["categories", "variables", "groups", "datasets"]:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute("DROP TABLE IF EXISTS datasets_fts")
    conn.execute("DROP TABLE IF EXISTS variables_fts")

    conn.executescript(_SCHEMA_SQL)

    trees = _load_cache(cache_dir)
    logger.info("Loading %d datasets into %s", len(trees), db_path)

    for tree in trees:
        dataset_name = tree["dataset_name"]
        geos = json.dumps(tree.get("geographies", []))
        conn.execute(
            "INSERT INTO datasets (name, geographies_json) VALUES (?, ?)",
            (dataset_name, geos),
        )
        dataset_id = conn.execute(
            "SELECT id FROM datasets WHERE name = ?", (dataset_name,)
        ).fetchone()[0]

        for group in tree.get("groups", []):
            group_path = group["label"]
            conn.execute(
                "INSERT INTO groups (dataset_id, label, path) VALUES (?, ?, ?)",
                (dataset_id, group_path, group_path),
            )
            group_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            for var in group.get("variables", []):
                conn.execute(
                    "INSERT INTO variables (group_id, code, label) VALUES (?, ?, ?)",
                    (group_id, var.get("code", ""), var["label"]),
                )
                var_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                for cat in var.get("categories", []):
                    conn.execute(
                        "INSERT INTO categories (variable_id, label) VALUES (?, ?)",
                        (var_id, cat["label"]),
                    )

    conn.commit()
    conn.close()
    logger.info("Database built: %s", db_path)
