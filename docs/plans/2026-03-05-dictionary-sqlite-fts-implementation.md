# Dictionary SQLite + FTS5 Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a searchable SQLite database from the JSON cache of ABS TableBuilder dataset dictionaries, with FTS5 full-text search and generated summaries, queryable via CLI and sqlite3.

**Architecture:** Load cached JSON files into normalized SQLite tables (datasets, groups, variables, categories). Generate natural-language summaries for datasets and variables. Index summaries + labels in FTS5 virtual tables. Expose via `dictionary_db.py` module and `tablebuilder search` CLI command.

**Tech Stack:** Python 3.12, sqlite3 (stdlib), Click CLI, pytest. No external dependencies.

---

### Task 1: Database Schema and build_db() Core

**Files:**
- Create: `src/tablebuilder/dictionary_db.py`
- Test: `tests/test_dictionary_db.py`

**Step 1: Write failing tests for build_db()**

Create `tests/test_dictionary_db.py`:

```python
# ABOUTME: Tests for the SQLite dictionary database builder and search.
# ABOUTME: Covers schema creation, data loading, summary generation, and FTS5 search.

import json
import sqlite3
import pytest
from pathlib import Path

from tablebuilder.dictionary_db import build_db


@pytest.fixture
def sample_cache(tmp_path):
    """Create a minimal JSON cache directory with two datasets."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    dataset1 = {
        "dataset_name": "Test Survey, 2021",
        "geographies": ["Australia", "State"],
        "groups": [
            {
                "label": "Demographics",
                "variables": [
                    {
                        "code": "SEXP",
                        "label": "Sex",
                        "categories": [
                            {"label": "Male"},
                            {"label": "Female"},
                        ],
                    },
                    {
                        "code": "AGEP",
                        "label": "Age",
                        "categories": [
                            {"label": "0-14 years"},
                            {"label": "15-24 years"},
                            {"label": "25-54 years"},
                            {"label": "55+ years"},
                        ],
                    },
                ],
            },
            {
                "label": "Employment",
                "variables": [
                    {
                        "code": "INDP",
                        "label": "Industry of Employment",
                        "categories": [
                            {"label": "Agriculture"},
                            {"label": "Mining"},
                            {"label": "Manufacturing"},
                        ],
                    },
                ],
            },
        ],
    }

    dataset2 = {
        "dataset_name": "Business Data (BLADE), 2020",
        "geographies": [],
        "groups": [
            {
                "label": "Business > Characteristics",
                "variables": [
                    {
                        "code": "",
                        "label": "Age of Business",
                        "categories": [
                            {"label": "0 Years"},
                            {"label": "1-5 Years"},
                            {"label": "6+ Years"},
                        ],
                    },
                    {
                        "code": "",
                        "label": "Employee Headcount",
                        "categories": [
                            {"label": "0 employees"},
                            {"label": "1-4 employees"},
                            {"label": "5-19 employees"},
                            {"label": "20+ employees"},
                        ],
                    },
                ],
            },
            {
                "label": "Business > Financial",
                "variables": [
                    {
                        "code": "",
                        "label": "Total Sales Revenue",
                        "categories": [
                            {"label": "Total Sales and Services Income"},
                        ],
                    },
                ],
            },
        ],
    }

    (cache_dir / "Test_Survey,_2021.json").write_text(json.dumps(dataset1))
    (cache_dir / "Business_Data_(BLADE),_2020.json").write_text(json.dumps(dataset2))
    return cache_dir


class TestBuildDb:
    def test_creates_database_file(self, sample_cache, tmp_path):
        """build_db creates a SQLite file at the given path."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        assert db_path.exists()

    def test_datasets_table(self, sample_cache, tmp_path):
        """All datasets from cache are loaded into the datasets table."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT name FROM datasets ORDER BY name").fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "Business Data (BLADE), 2020"
        assert rows[1][0] == "Test Survey, 2021"
        conn.close()

    def test_groups_table(self, sample_cache, tmp_path):
        """Groups are linked to their datasets."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT g.path FROM groups g "
            "JOIN datasets d ON g.dataset_id = d.id "
            "WHERE d.name = 'Test Survey, 2021' ORDER BY g.path"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "Demographics"
        assert rows[1][0] == "Employment"
        conn.close()

    def test_variables_table(self, sample_cache, tmp_path):
        """Variables are linked to their groups with code and label."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT v.code, v.label FROM variables v "
            "JOIN groups g ON v.group_id = g.id "
            "JOIN datasets d ON g.dataset_id = d.id "
            "WHERE d.name = 'Test Survey, 2021' ORDER BY v.code"
        ).fetchall()
        assert len(rows) == 3
        codes = [r[0] for r in rows]
        assert "SEXP" in codes
        assert "AGEP" in codes
        assert "INDP" in codes
        conn.close()

    def test_categories_table(self, sample_cache, tmp_path):
        """Categories are linked to their variables."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT c.label FROM categories c "
            "JOIN variables v ON c.variable_id = v.id "
            "WHERE v.code = 'SEXP' ORDER BY c.label"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "Female"
        assert rows[1][0] == "Male"
        conn.close()

    def test_idempotent_rebuild(self, sample_cache, tmp_path):
        """Calling build_db twice produces the same result."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()
        assert rows[0] == 2
        conn.close()

    def test_empty_cache(self, tmp_path):
        """Empty cache dir produces a valid but empty database."""
        cache_dir = tmp_path / "empty_cache"
        cache_dir.mkdir()
        db_path = tmp_path / "test.db"
        build_db(cache_dir, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()
        assert rows[0] == 0
        conn.close()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dictionary_db.py -v`
Expected: ImportError — `dictionary_db` module does not exist yet.

**Step 3: Implement build_db()**

Create `src/tablebuilder/dictionary_db.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dictionary_db.py -v`
Expected: All 7 tests PASS.

**Step 5: Commit**

```bash
git add src/tablebuilder/dictionary_db.py tests/test_dictionary_db.py
git commit -m "feat: add dictionary_db with SQLite schema and build_db()"
```

---

### Task 2: Summary Generation

**Files:**
- Modify: `src/tablebuilder/dictionary_db.py`
- Test: `tests/test_dictionary_db.py`

**Step 1: Write failing tests for summaries**

Add to `tests/test_dictionary_db.py`:

```python
from tablebuilder.dictionary_db import build_db, _generate_dataset_summary, _generate_variable_summary


class TestSummaryGeneration:
    def test_dataset_summary_includes_name(self):
        """Dataset summary contains the dataset name."""
        tree = {
            "dataset_name": "Test Survey, 2021",
            "geographies": ["Australia", "State"],
            "groups": [
                {
                    "label": "Demographics",
                    "variables": [
                        {"code": "SEXP", "label": "Sex", "categories": [{"label": "Male"}, {"label": "Female"}]},
                    ],
                }
            ],
        }
        summary = _generate_dataset_summary(tree)
        assert "Test Survey, 2021" in summary

    def test_dataset_summary_includes_geographies(self):
        """Dataset summary mentions geography types when present."""
        tree = {
            "dataset_name": "Test Survey, 2021",
            "geographies": ["Australia", "State"],
            "groups": [],
        }
        summary = _generate_dataset_summary(tree)
        assert "Australia" in summary
        assert "State" in summary

    def test_dataset_summary_includes_group_names(self):
        """Dataset summary mentions top-level group names."""
        tree = {
            "dataset_name": "Test Survey, 2021",
            "geographies": [],
            "groups": [
                {"label": "Demographics", "variables": [{"code": "SEXP", "label": "Sex", "categories": []}]},
                {"label": "Employment", "variables": [{"code": "INDP", "label": "Industry", "categories": []}]},
            ],
        }
        summary = _generate_dataset_summary(tree)
        assert "Demographics" in summary
        assert "Employment" in summary

    def test_dataset_summary_includes_counts(self):
        """Dataset summary includes variable and group counts."""
        tree = {
            "dataset_name": "Test Survey, 2021",
            "geographies": [],
            "groups": [
                {
                    "label": "Demographics",
                    "variables": [
                        {"code": "SEXP", "label": "Sex", "categories": [{"label": "Male"}, {"label": "Female"}]},
                        {"code": "AGEP", "label": "Age", "categories": [{"label": "0-14"}, {"label": "15+"}]},
                    ],
                }
            ],
        }
        summary = _generate_dataset_summary(tree)
        assert "2 variables" in summary

    def test_variable_summary_includes_label(self):
        """Variable summary contains the variable label."""
        summary = _generate_variable_summary(
            code="SEXP", label="Sex", categories=["Male", "Female"],
            group_path="Demographics", dataset_name="Test Survey, 2021",
        )
        assert "Sex" in summary

    def test_variable_summary_includes_categories(self):
        """Variable summary lists category labels."""
        summary = _generate_variable_summary(
            code="SEXP", label="Sex", categories=["Male", "Female"],
            group_path="Demographics", dataset_name="Test Survey, 2021",
        )
        assert "Male" in summary
        assert "Female" in summary

    def test_variable_summary_truncates_long_categories(self):
        """Variable summary truncates after 10 categories."""
        cats = [f"Category {i}" for i in range(20)]
        summary = _generate_variable_summary(
            code="TEST", label="Test Var", categories=cats,
            group_path="Group", dataset_name="Dataset",
        )
        assert "20 total" in summary
        assert "Category 0" in summary
        # Should not list all 20
        assert "Category 19" not in summary
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dictionary_db.py::TestSummaryGeneration -v`
Expected: ImportError — functions don't exist yet.

**Step 3: Implement summary functions**

Add to `src/tablebuilder/dictionary_db.py`:

```python
def _generate_dataset_summary(tree: dict) -> str:
    """Generate a natural-language summary for a dataset."""
    name = tree["dataset_name"]
    geos = tree.get("geographies", [])
    groups = tree.get("groups", [])

    # Collect top-level group names (before ' > ' separator)
    top_groups = sorted(set(
        g["label"].split(" > ")[0] for g in groups if g.get("variables")
    ))
    total_vars = sum(len(g.get("variables", [])) for g in groups)

    parts = [f"{name}."]

    if top_groups:
        parts.append(f"Covers: {', '.join(top_groups)}.")

    parts.append(f"{total_vars} variables across {len(groups)} groups.")

    if geos:
        parts.append(f"Geographies: {', '.join(geos)}.")

    # Collect all variable codes for searchability
    codes = [
        v["code"] for g in groups for v in g.get("variables", []) if v.get("code")
    ]
    if codes:
        parts.append(f"Variable codes: {', '.join(codes[:20])}.")

    return " ".join(parts)


def _generate_variable_summary(
    code: str, label: str, categories: list[str],
    group_path: str, dataset_name: str,
) -> str:
    """Generate a natural-language summary for a variable."""
    parts = []
    if code:
        parts.append(f"{code} {label}")
    else:
        parts.append(label)

    parts.append(f"in {group_path} group of {dataset_name}.")

    if categories:
        if len(categories) <= 10:
            parts.append(f"Categories: {', '.join(categories)}.")
        else:
            shown = ', '.join(categories[:10])
            parts.append(f"Categories: {shown} ({len(categories)} total).")

    return " ".join(parts)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dictionary_db.py::TestSummaryGeneration -v`
Expected: All 7 tests PASS.

**Step 5: Commit**

```bash
git add src/tablebuilder/dictionary_db.py tests/test_dictionary_db.py
git commit -m "feat: add dataset and variable summary generation"
```

---

### Task 3: FTS5 Index

**Files:**
- Modify: `src/tablebuilder/dictionary_db.py`
- Test: `tests/test_dictionary_db.py`

**Step 1: Write failing tests for FTS5**

Add to `tests/test_dictionary_db.py`:

```python
class TestFts5Index:
    def test_datasets_fts_exists(self, sample_cache, tmp_path):
        """The datasets_fts virtual table is created and populated."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT name, summary FROM datasets_fts ORDER BY name"
        ).fetchall()
        assert len(rows) == 2
        assert rows[1][0] == "Test Survey, 2021"
        assert len(rows[1][1]) > 0  # summary is populated
        conn.close()

    def test_variables_fts_exists(self, sample_cache, tmp_path):
        """The variables_fts virtual table is created and populated."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT COUNT(*) FROM variables_fts").fetchone()
        # 3 vars in dataset1 + 3 vars in dataset2 = 6
        assert rows[0] == 6
        conn.close()

    def test_variables_fts_has_categories_text(self, sample_cache, tmp_path):
        """Variable FTS rows include concatenated category labels."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT categories_text FROM variables_fts WHERE label = 'Sex'"
        ).fetchall()
        assert len(rows) == 1
        assert "Male" in rows[0][0]
        assert "Female" in rows[0][0]
        conn.close()

    def test_fts_keyword_search(self, sample_cache, tmp_path):
        """FTS5 MATCH finds variables by keyword."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT dataset_name, label FROM variables_fts "
            "WHERE variables_fts MATCH 'Mining' ORDER BY rank"
        ).fetchall()
        assert len(rows) >= 1
        assert any("Industry" in r[1] for r in rows)
        conn.close()

    def test_fts_dataset_search(self, sample_cache, tmp_path):
        """FTS5 MATCH on datasets_fts finds datasets by summary content."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT name FROM datasets_fts "
            "WHERE datasets_fts MATCH 'Demographics' ORDER BY rank"
        ).fetchall()
        assert len(rows) >= 1
        assert any("Test Survey" in r[0] for r in rows)
        conn.close()

    def test_fts_search_revenue(self, sample_cache, tmp_path):
        """FTS5 finds business revenue variables."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT dataset_name, label FROM variables_fts "
            "WHERE variables_fts MATCH 'Revenue' ORDER BY rank"
        ).fetchall()
        assert len(rows) >= 1
        assert any("BLADE" in r[0] for r in rows)
        conn.close()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dictionary_db.py::TestFts5Index -v`
Expected: FAIL — FTS tables don't exist.

**Step 3: Add FTS5 creation and population to build_db()**

Update `build_db()` in `src/tablebuilder/dictionary_db.py` to create FTS5 tables and populate them after loading core tables. Add after `conn.commit()`:

```python
    # Create FTS5 virtual tables
    conn.execute("""
        CREATE VIRTUAL TABLE datasets_fts USING fts5(
            name, summary, content='', content_rowid=''
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE variables_fts USING fts5(
            dataset_name, group_path, code, label, categories_text, summary,
            content='', content_rowid=''
        )
    """)

    # Populate dataset FTS
    for tree in trees:
        summary = _generate_dataset_summary(tree)
        conn.execute(
            "UPDATE datasets SET summary = ? WHERE name = ?",
            (summary, tree["dataset_name"]),
        )
        conn.execute(
            "INSERT INTO datasets_fts (name, summary) VALUES (?, ?)",
            (tree["dataset_name"], summary),
        )

    # Populate variable FTS
    rows = conn.execute("""
        SELECT v.id, d.name, g.path, v.code, v.label
        FROM variables v
        JOIN groups g ON v.group_id = g.id
        JOIN datasets d ON g.dataset_id = d.id
    """).fetchall()

    for var_id, ds_name, grp_path, code, label in rows:
        cats = conn.execute(
            "SELECT label FROM categories WHERE variable_id = ?", (var_id,)
        ).fetchall()
        cat_labels = [c[0] for c in cats]
        cat_text = ", ".join(cat_labels)
        summary = _generate_variable_summary(
            code=code, label=label, categories=cat_labels,
            group_path=grp_path, dataset_name=ds_name,
        )
        conn.execute(
            "INSERT INTO variables_fts "
            "(dataset_name, group_path, code, label, categories_text, summary) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ds_name, grp_path, code, label, cat_text, summary),
        )

    conn.commit()
    conn.close()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dictionary_db.py -v`
Expected: All tests PASS (both old and new).

**Step 5: Commit**

```bash
git add src/tablebuilder/dictionary_db.py tests/test_dictionary_db.py
git commit -m "feat: add FTS5 full-text search index with summaries"
```

---

### Task 4: Search Function

**Files:**
- Modify: `src/tablebuilder/dictionary_db.py`
- Test: `tests/test_dictionary_db.py`

**Step 1: Write failing tests for search()**

Add to `tests/test_dictionary_db.py`:

```python
from tablebuilder.dictionary_db import build_db, search, get_dataset, get_variables_by_code


class TestSearch:
    def test_search_returns_results(self, sample_cache, tmp_path):
        """search() returns a list of dicts with expected keys."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        results = search(db_path, "Sex Male Female")
        assert len(results) >= 1
        r = results[0]
        assert "dataset_name" in r
        assert "group_path" in r
        assert "label" in r

    def test_search_limit(self, sample_cache, tmp_path):
        """search() respects the limit parameter."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        results = search(db_path, "categories", limit=2)
        assert len(results) <= 2

    def test_search_no_results(self, sample_cache, tmp_path):
        """search() returns empty list for unmatched query."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        results = search(db_path, "xyznonexistent")
        assert results == []

    def test_search_by_category_content(self, sample_cache, tmp_path):
        """search() finds variables by their category labels."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        results = search(db_path, "Agriculture")
        assert len(results) >= 1
        assert any("Industry" in r["label"] for r in results)


class TestGetDataset:
    def test_get_existing_dataset(self, sample_cache, tmp_path):
        """get_dataset returns full details for an existing dataset."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        result = get_dataset(db_path, "Test Survey, 2021")
        assert result is not None
        assert result["name"] == "Test Survey, 2021"
        assert "groups" in result
        assert len(result["groups"]) == 2

    def test_get_missing_dataset(self, sample_cache, tmp_path):
        """get_dataset returns None for a non-existent dataset."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        result = get_dataset(db_path, "Nonexistent")
        assert result is None


class TestGetVariablesByCode:
    def test_find_by_code(self, sample_cache, tmp_path):
        """get_variables_by_code finds variables by their code."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        results = get_variables_by_code(db_path, "SEXP")
        assert len(results) == 1
        assert results[0]["label"] == "Sex"
        assert results[0]["dataset_name"] == "Test Survey, 2021"

    def test_find_missing_code(self, sample_cache, tmp_path):
        """get_variables_by_code returns empty list for unknown code."""
        db_path = tmp_path / "test.db"
        build_db(sample_cache, db_path)
        results = get_variables_by_code(db_path, "ZZZZZ")
        assert results == []
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dictionary_db.py::TestSearch tests/test_dictionary_db.py::TestGetDataset tests/test_dictionary_db.py::TestGetVariablesByCode -v`
Expected: ImportError — functions don't exist yet.

**Step 3: Implement search(), get_dataset(), get_variables_by_code()**

Add to `src/tablebuilder/dictionary_db.py`:

```python
def search(db_path: Path, query: str, limit: int = 20) -> list[dict]:
    """Search the dictionary database using FTS5 full-text search.

    Returns a ranked list of matching variables with dataset context.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT dataset_name, group_path, code, label, categories_text, summary "
            "FROM variables_fts "
            "WHERE variables_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_dataset(db_path: Path, name: str) -> dict | None:
    """Get full details for a dataset by exact name.

    Returns a dict with name, geographies, summary, and nested groups
    containing variables and categories.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ds = conn.execute(
            "SELECT id, name, geographies_json, summary FROM datasets WHERE name = ?",
            (name,),
        ).fetchone()
        if ds is None:
            return None

        result = {
            "name": ds["name"],
            "geographies": json.loads(ds["geographies_json"]),
            "summary": ds["summary"],
            "groups": [],
        }

        groups = conn.execute(
            "SELECT id, path FROM groups WHERE dataset_id = ? ORDER BY path",
            (ds["id"],),
        ).fetchall()

        for grp in groups:
            group_data = {"path": grp["path"], "variables": []}
            variables = conn.execute(
                "SELECT id, code, label FROM variables WHERE group_id = ? ORDER BY label",
                (grp["id"],),
            ).fetchall()
            for var in variables:
                cats = conn.execute(
                    "SELECT label FROM categories WHERE variable_id = ? ORDER BY label",
                    (var["id"],),
                ).fetchall()
                group_data["variables"].append({
                    "code": var["code"],
                    "label": var["label"],
                    "categories": [c["label"] for c in cats],
                })
            result["groups"].append(group_data)

        return result
    finally:
        conn.close()


def get_variables_by_code(db_path: Path, code: str) -> list[dict]:
    """Look up variables by their code across all datasets.

    Returns a list of dicts with code, label, dataset_name, group_path,
    and categories.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT v.id, v.code, v.label, d.name as dataset_name, g.path as group_path "
            "FROM variables v "
            "JOIN groups g ON v.group_id = g.id "
            "JOIN datasets d ON g.dataset_id = d.id "
            "WHERE v.code = ? ORDER BY d.name",
            (code,),
        ).fetchall()

        results = []
        for row in rows:
            cats = conn.execute(
                "SELECT label FROM categories WHERE variable_id = ? ORDER BY label",
                (row["id"],),
            ).fetchall()
            results.append({
                "code": row["code"],
                "label": row["label"],
                "dataset_name": row["dataset_name"],
                "group_path": row["group_path"],
                "categories": [c["label"] for c in cats],
            })
        return results
    finally:
        conn.close()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dictionary_db.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/tablebuilder/dictionary_db.py tests/test_dictionary_db.py
git commit -m "feat: add search(), get_dataset(), get_variables_by_code()"
```

---

### Task 5: CLI search Command and --rebuild-db Flag

**Files:**
- Modify: `src/tablebuilder/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write failing tests**

Add to `tests/test_cli.py`:

```python
class TestCliSearch:
    def test_search_help_shows_query(self):
        """search --help shows the QUERY argument."""
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "QUERY" in result.output or "query" in result.output

    def test_search_help_shows_limit(self):
        """search --help shows --limit option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "--limit" in result.output


class TestCliDictionaryRebuildDb:
    def test_dictionary_help_shows_rebuild_db(self):
        """dictionary --help lists --rebuild-db."""
        runner = CliRunner()
        result = runner.invoke(cli, ["dictionary", "--help"])
        assert result.exit_code == 0
        assert "--rebuild-db" in result.output
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestCliSearch tests/test_cli.py::TestCliDictionaryRebuildDb -v`
Expected: FAIL — search command and --rebuild-db don't exist.

**Step 3: Add search command and --rebuild-db flag to CLI**

Add to `src/tablebuilder/cli.py` (after the `dictionary` command):

```python
@cli.command()
@click.argument("query")
@click.option("--limit", default=20, help="Maximum results (default: 20).")
@click.option("--datasets", is_flag=True, help="Search datasets instead of variables.")
def search(query, limit, datasets):
    """Search the data dictionary for variables or datasets."""
    from tablebuilder.dictionary_db import search as db_search, DEFAULT_DB_PATH

    if not DEFAULT_DB_PATH.exists():
        click.echo(
            "No dictionary database found. Run 'tablebuilder dictionary --rebuild-db' first.",
            err=True,
        )
        sys.exit(1)

    results = db_search(DEFAULT_DB_PATH, query, limit=limit)
    if not results:
        click.echo("No results found.")
        return

    for r in results:
        code_str = f" ({r['code']})" if r.get('code') else ""
        click.echo(f"  {r['dataset_name']} > {r['group_path']}")
        click.echo(f"    {r['label']}{code_str}")
        cats = r.get('categories_text', '')
        if cats:
            truncated = cats[:120] + "..." if len(cats) > 120 else cats
            click.echo(f"    Categories: {truncated}")
        click.echo()
```

Add `--rebuild-db` flag to the `dictionary` command. Add after the `@click.option("--clear-cache", ...)` decorator:

```python
@click.option("--rebuild-db", is_flag=True, help="Rebuild the SQLite search database from cache.")
```

Update the `dictionary` function signature to include `rebuild_db` and add this block at the top of the function body (after `clear_cache` handling):

```python
    if rebuild_db:
        from tablebuilder.dictionary_db import build_db as db_build, DEFAULT_DB_PATH, DEFAULT_CACHE_DIR as DB_CACHE_DIR
        db_build(DB_CACHE_DIR, DEFAULT_DB_PATH)
        click.echo(f"Database rebuilt at {DEFAULT_DB_PATH}")
        if not dataset and not output:
            return  # Just rebuild, don't extract
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/tablebuilder/cli.py tests/test_cli.py
git commit -m "feat: add 'search' CLI command and --rebuild-db flag"
```

---

### Task 6: Build Real Database and Verify

**Files:**
- No new files — integration verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS.

**Step 2: Build the real database from cached JSON**

Run: `uv run tablebuilder dictionary --rebuild-db`
Expected: "Database rebuilt at /Users/dewoller/.tablebuilder/dictionary.db"

**Step 3: Verify with test searches**

Run:
```bash
uv run tablebuilder search "business income revenue"
uv run tablebuilder search "employment industry Melbourne"
uv run tablebuilder search "small business employees"
```

Expected: Relevant results from BLADE, Labour Force Survey, and other datasets.

**Step 4: Check database size**

Run: `ls -lh ~/.tablebuilder/dictionary.db`
Expected: ~5-15 MB.

**Step 5: Commit any final adjustments**

```bash
git add -A
git commit -m "chore: verify dictionary SQLite database build"
```

---

### Task 7: Update CLAUDE.md and Memory

**Files:**
- Modify: `CLAUDE.md`
- Modify: memory files

**Step 1: Add search instructions to CLAUDE.md**

Add a section to `CLAUDE.md` documenting the dictionary database:

```markdown
## Data Dictionary Search

SQLite database at `~/.tablebuilder/dictionary.db` contains 96 ABS TableBuilder datasets
with FTS5 full-text search. To search for relevant variables:

```bash
# CLI search
uv run tablebuilder search "business income revenue"

# Direct SQLite (for Claude Code sessions)
sqlite3 ~/.tablebuilder/dictionary.db "SELECT dataset_name, label, categories_text FROM variables_fts WHERE variables_fts MATCH 'business employment' ORDER BY rank LIMIT 10;"

# Rebuild after new extractions
uv run tablebuilder dictionary --rebuild-db
```
```

**Step 2: Update memory**

Update memory file with dictionary database details.

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add data dictionary search instructions to CLAUDE.md"
```
