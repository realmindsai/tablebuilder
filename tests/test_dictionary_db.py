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
