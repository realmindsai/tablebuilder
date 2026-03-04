# ABOUTME: Tests for the SQLite dictionary database builder and search.
# ABOUTME: Covers schema creation, data loading, summary generation, and FTS5 search.

import json
import sqlite3
import pytest
from pathlib import Path

from tablebuilder.dictionary_db import build_db, _generate_dataset_summary, _generate_variable_summary


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
