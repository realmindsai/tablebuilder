# ABOUTME: Tests for tree extraction functions that parse ABS TableBuilder variable trees.
# ABOUTME: Covers indent-to-depth mapping, label parsing, geography/variable splitting, and cache functions.

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from tablebuilder.models import CategoryInfo, VariableInfo, VariableGroup, DatasetTree
from tablebuilder.tree_extractor import (
    _indent_to_depth,
    _parse_variable_label,
    _split_geography_and_variables,
    _parse_variable_tree,
    _save_tree_cache,
    _load_cached_trees,
    _save_progress,
    _load_progress,
)


class TestIndentToDepth:
    def test_uniform_indent_gives_zero_depth(self):
        """All nodes with the same indent value get depth 0."""
        nodes = [
            {"label": "A", "indent_px": 20},
            {"label": "B", "indent_px": 20},
            {"label": "C", "indent_px": 20},
        ]
        result = _indent_to_depth(nodes)
        assert all(n["depth"] == 0 for n in result)

    def test_three_indent_levels(self):
        """Evenly spaced indents [0, 20, 40] map to depths [0, 1, 2]."""
        nodes = [
            {"label": "Root", "indent_px": 0},
            {"label": "Child", "indent_px": 20},
            {"label": "Grandchild", "indent_px": 40},
        ]
        result = _indent_to_depth(nodes)
        assert result[0]["depth"] == 0
        assert result[1]["depth"] == 1
        assert result[2]["depth"] == 2

    def test_non_uniform_spacing(self):
        """Non-uniform pixel gaps [0, 15, 40] still map to ordinal depths [0, 1, 2]."""
        nodes = [
            {"label": "Root", "indent_px": 0},
            {"label": "Child", "indent_px": 15},
            {"label": "Grandchild", "indent_px": 40},
        ]
        result = _indent_to_depth(nodes)
        assert result[0]["depth"] == 0
        assert result[1]["depth"] == 1
        assert result[2]["depth"] == 2

    def test_empty_list(self):
        """Empty input returns empty output."""
        assert _indent_to_depth([]) == []


class TestParseVariableLabel:
    def test_standard_label(self):
        """'SEXP Sex' splits into code='SEXP' and name='Sex'."""
        code, name = _parse_variable_label("SEXP Sex")
        assert code == "SEXP"
        assert name == "Sex"

    def test_multi_word_name(self):
        """'AGE5P Age in Five Year Groups' keeps the full name after the code."""
        code, name = _parse_variable_label("AGE5P Age in Five Year Groups")
        assert code == "AGE5P"
        assert name == "Age in Five Year Groups"

    def test_no_code(self):
        """'Total' has no ALL-CAPS code prefix."""
        code, name = _parse_variable_label("Total")
        assert code == ""
        assert name == "Total"

    def test_lowercase_not_code(self):
        """'some text here' has no ALL-CAPS first word."""
        code, name = _parse_variable_label("some text here")
        assert code == ""
        assert name == "some text here"

    def test_code_too_long(self):
        """First word longer than 10 chars is not treated as a code."""
        code, name = _parse_variable_label("VERYLONGCODE Something")
        assert code == ""
        assert name == "VERYLONGCODE Something"


class TestSplitGeographyAndVariables:
    def test_geography_before_variables(self):
        """Geography nodes (leaf, no checkbox) come first, then variable nodes."""
        nodes = [
            {"label": "Dataset Root", "depth": 0, "is_leaf": False, "has_checkbox": False},
            {"label": "Australia", "depth": 1, "is_leaf": True, "has_checkbox": False},
            {"label": "State", "depth": 1, "is_leaf": True, "has_checkbox": False},
            {"label": "Demographics", "depth": 0, "is_leaf": False, "has_checkbox": False},
            {"label": "SEXP Sex", "depth": 1, "is_leaf": False, "has_checkbox": False},
            {"label": "Male", "depth": 2, "is_leaf": True, "has_checkbox": True},
            {"label": "Female", "depth": 2, "is_leaf": True, "has_checkbox": True},
        ]
        geos, var_nodes = _split_geography_and_variables(nodes)
        assert geos == ["Australia", "State"]
        # Variable nodes start from the "Demographics" group onward
        assert var_nodes[0]["label"] == "Demographics"

    def test_no_geography(self):
        """When the first checkbox appears immediately, there are no geography nodes."""
        nodes = [
            {"label": "Root", "depth": 0, "is_leaf": False, "has_checkbox": False},
            {"label": "SEXP Sex", "depth": 1, "is_leaf": False, "has_checkbox": False},
            {"label": "Male", "depth": 2, "is_leaf": True, "has_checkbox": True},
        ]
        geos, var_nodes = _split_geography_and_variables(nodes)
        assert geos == []
        assert var_nodes[0]["label"] == "Root"

    def test_all_geography(self):
        """When no node has a checkbox, everything is geography."""
        nodes = [
            {"label": "Root", "depth": 0, "is_leaf": False, "has_checkbox": False},
            {"label": "Australia", "depth": 1, "is_leaf": True, "has_checkbox": False},
            {"label": "State", "depth": 1, "is_leaf": True, "has_checkbox": False},
        ]
        geos, var_nodes = _split_geography_and_variables(nodes)
        assert geos == ["Australia", "State"]
        assert var_nodes == []


class TestParseVariableTree:
    def test_single_group_with_variables(self):
        """One group with two variables, each having categories."""
        nodes = [
            {"label": "Demographics", "depth": 0, "is_leaf": False, "has_checkbox": False},
            {"label": "SEXP Sex", "depth": 1, "is_leaf": False, "has_checkbox": False},
            {"label": "Male", "depth": 2, "is_leaf": True, "has_checkbox": True},
            {"label": "Female", "depth": 2, "is_leaf": True, "has_checkbox": True},
            {"label": "AGE5P Age in Five Year Groups", "depth": 1, "is_leaf": False, "has_checkbox": False},
            {"label": "0-4 years", "depth": 2, "is_leaf": True, "has_checkbox": True},
            {"label": "5-9 years", "depth": 2, "is_leaf": True, "has_checkbox": True},
        ]
        groups = _parse_variable_tree(nodes)
        assert len(groups) == 1
        assert groups[0].label == "Demographics"
        assert len(groups[0].variables) == 2

        sex_var = groups[0].variables[0]
        assert sex_var.code == "SEXP"
        assert sex_var.label == "Sex"
        assert len(sex_var.categories) == 2
        assert sex_var.categories[0].label == "Male"
        assert sex_var.categories[1].label == "Female"

        age_var = groups[0].variables[1]
        assert age_var.code == "AGE5P"
        assert age_var.label == "Age in Five Year Groups"
        assert len(age_var.categories) == 2

    def test_multiple_groups(self):
        """Two groups each with one variable."""
        nodes = [
            {"label": "Demographics", "depth": 0, "is_leaf": False, "has_checkbox": False},
            {"label": "SEXP Sex", "depth": 1, "is_leaf": False, "has_checkbox": False},
            {"label": "Male", "depth": 2, "is_leaf": True, "has_checkbox": True},
            {"label": "Education", "depth": 0, "is_leaf": False, "has_checkbox": False},
            {"label": "QALFP Qualification", "depth": 1, "is_leaf": False, "has_checkbox": False},
            {"label": "Bachelor", "depth": 2, "is_leaf": True, "has_checkbox": True},
        ]
        groups = _parse_variable_tree(nodes)
        assert len(groups) == 2
        assert groups[0].label == "Demographics"
        assert groups[1].label == "Education"
        assert len(groups[0].variables) == 1
        assert len(groups[1].variables) == 1

    def test_empty_group_skipped(self):
        """A group with no variables is skipped (only groups with variables are output)."""
        nodes = [
            {"label": "Empty Group", "depth": 0, "is_leaf": False, "has_checkbox": False},
            {"label": "Real Group", "depth": 0, "is_leaf": False, "has_checkbox": False},
            {"label": "SEXP Sex", "depth": 1, "is_leaf": False, "has_checkbox": False},
            {"label": "Male", "depth": 2, "is_leaf": True, "has_checkbox": True},
        ]
        groups = _parse_variable_tree(nodes)
        assert len(groups) == 1
        assert groups[0].label == "Real Group"
        assert len(groups[0].variables) == 1

    def test_variable_without_leaf_children_becomes_group(self):
        """A non-leaf node with no leaf children is classified as a group, not a variable."""
        nodes = [
            {"label": "Demographics", "depth": 0, "is_leaf": False, "has_checkbox": False},
            {"label": "SEXP Sex", "depth": 1, "is_leaf": False, "has_checkbox": False},
            {"label": "AGE5P Age", "depth": 1, "is_leaf": False, "has_checkbox": False},
            {"label": "0-4", "depth": 2, "is_leaf": True, "has_checkbox": True},
        ]
        groups = _parse_variable_tree(nodes)
        # SEXP has no leaf children -> becomes a group (skipped, empty)
        # AGE5P has leaf child "0-4" -> is a variable
        assert len(groups) >= 1
        # Find the group containing AGE5P
        age_var = None
        for g in groups:
            for v in g.variables:
                if v.code == "AGE5P":
                    age_var = v
        assert age_var is not None
        assert len(age_var.categories) == 1


class TestCacheFunctions:
    def test_save_and_load_tree_cache(self, tmp_path):
        """Round-trip: save a DatasetTree and load it back."""
        tree = DatasetTree(
            dataset_name="Census 2021",
            geographies=["Australia", "State"],
            groups=[
                VariableGroup(
                    label="Demographics",
                    variables=[
                        VariableInfo(
                            code="SEXP",
                            label="Sex",
                            categories=[CategoryInfo(label="Male"), CategoryInfo(label="Female")],
                        )
                    ],
                )
            ],
        )
        _save_tree_cache(tree, tmp_path)
        loaded = _load_cached_trees(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].dataset_name == "Census 2021"
        assert loaded[0].geographies == ["Australia", "State"]
        assert len(loaded[0].groups) == 1
        assert loaded[0].groups[0].label == "Demographics"
        assert loaded[0].groups[0].variables[0].code == "SEXP"
        assert len(loaded[0].groups[0].variables[0].categories) == 2

    def test_load_empty_cache(self, tmp_path):
        """An empty cache directory returns an empty list."""
        loaded = _load_cached_trees(tmp_path)
        assert loaded == []

    def test_save_and_load_progress(self, tmp_path):
        """Round-trip: save progress dict and load it back."""
        progress_path = tmp_path / "progress.json"
        progress = {
            "completed": ["Census 2021", "Labour Force"],
            "failed": {"CPI": "timeout error"},
            "total": 5,
        }
        _save_progress(progress, progress_path)
        loaded = _load_progress(progress_path)
        assert loaded["completed"] == ["Census 2021", "Labour Force"]
        assert loaded["failed"] == {"CPI": "timeout error"}
        assert loaded["total"] == 5

    def test_load_missing_progress(self, tmp_path):
        """Loading a non-existent progress file returns default dict."""
        progress_path = tmp_path / "nonexistent.json"
        loaded = _load_progress(progress_path)
        assert loaded == {"completed": [], "failed": {}, "total": 0}
