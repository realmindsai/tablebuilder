# ABOUTME: Tests for the data dictionary markdown formatter.
# ABOUTME: Validates formatting of DatasetTree objects into markdown documentation.

from datetime import date
from unittest.mock import patch

import pytest

from tablebuilder.dict_formatter import (
    _format_cross_reference,
    _slugify,
    format_data_dictionary,
    format_dataset,
)
from tablebuilder.models import CategoryInfo, DatasetTree, VariableGroup, VariableInfo


def _make_categories(labels: list[str]) -> list[CategoryInfo]:
    """Helper to build a list of CategoryInfo from label strings."""
    return [CategoryInfo(label=lbl) for lbl in labels]


def _make_variable(
    code: str, label: str, categories: list[str] | None = None
) -> VariableInfo:
    """Helper to build a VariableInfo with optional category labels."""
    cats = _make_categories(categories) if categories else []
    return VariableInfo(code=code, label=label, categories=cats)


class TestFormatDataset:
    def test_single_dataset_with_geographies_and_variables(self):
        """Standard case: dataset with geographies, groups, and variables."""
        tree = DatasetTree(
            dataset_name="cultural diversity",
            geographies=["Australia", "Main Statistical Area Structure"],
            groups=[
                VariableGroup(
                    label="Demographics",
                    variables=[
                        _make_variable("SEXP", "Sex", ["Male", "Female"]),
                        _make_variable("AGEP", "Age", ["0-4", "5-9", "10-14"]),
                    ],
                ),
            ],
        )
        result = format_dataset(tree)

        assert "## cultural diversity" in result
        assert "### Available Geographies" in result
        assert "- Australia" in result
        assert "- Main Statistical Area Structure" in result
        assert "### Variables" in result
        assert "#### Demographics" in result
        assert "- **SEXP** Sex" in result
        assert "- **AGEP** Age" in result
        assert "Categories: Male, Female" in result
        assert "Categories: 0-4, 5-9, 10-14" in result

    def test_categories_truncated_after_eight(self):
        """Categories longer than 8 items are truncated with a total count."""
        labels = [f"Cat{i}" for i in range(1, 16)]  # 15 categories
        tree = DatasetTree(
            dataset_name="test dataset",
            groups=[
                VariableGroup(
                    label="Group",
                    variables=[_make_variable("VAR1", "Variable One", labels)],
                ),
            ],
        )
        result = format_dataset(tree)

        # First 8 should be present
        for i in range(1, 9):
            assert f"Cat{i}" in result
        # 9th and beyond should NOT be listed individually
        assert "Cat9" not in result
        # Truncation marker with total
        assert "... (15 total)" in result

    def test_short_categories_not_truncated(self):
        """Categories with 8 or fewer items are shown in full."""
        labels = ["A", "B", "C", "D", "E"]
        tree = DatasetTree(
            dataset_name="test dataset",
            groups=[
                VariableGroup(
                    label="Group",
                    variables=[_make_variable("V1", "Var", labels)],
                ),
            ],
        )
        result = format_dataset(tree)

        assert "Categories: A, B, C, D, E" in result
        assert "total)" not in result

    def test_variable_with_no_code(self):
        """Variable with empty code shows just the label."""
        tree = DatasetTree(
            dataset_name="test dataset",
            groups=[
                VariableGroup(
                    label="Group",
                    variables=[_make_variable("", "Unnamed Variable")],
                ),
            ],
        )
        result = format_dataset(tree)

        assert "- Unnamed Variable" in result
        # Should not have bold empty code or double spaces
        assert "- ** **" not in result
        assert "- ****" not in result

    def test_variable_with_no_categories(self):
        """Variable with no categories omits the Categories line entirely."""
        tree = DatasetTree(
            dataset_name="test dataset",
            groups=[
                VariableGroup(
                    label="Group",
                    variables=[_make_variable("CODE", "Some Variable")],
                ),
            ],
        )
        result = format_dataset(tree)

        assert "- **CODE** Some Variable" in result
        assert "Categories:" not in result

    def test_no_geographies(self):
        """Dataset with no geographies shows (none listed) placeholder."""
        tree = DatasetTree(
            dataset_name="test dataset",
            geographies=[],
            groups=[
                VariableGroup(
                    label="Group",
                    variables=[_make_variable("V1", "Var")],
                ),
            ],
        )
        result = format_dataset(tree)

        assert "### Available Geographies" in result
        assert "- (none listed)" in result

    def test_empty_group(self):
        """Group with no variables still shows its header."""
        tree = DatasetTree(
            dataset_name="test dataset",
            groups=[
                VariableGroup(label="Empty Group", variables=[]),
                VariableGroup(
                    label="Has Variables",
                    variables=[_make_variable("V1", "Var")],
                ),
            ],
        )
        result = format_dataset(tree)

        assert "#### Empty Group" in result
        assert "#### Has Variables" in result


class TestFormatCrossReference:
    def test_cross_reference_sorted_by_frequency(self):
        """Variables appearing in more datasets sort first."""
        tree_a = DatasetTree(
            dataset_name="Dataset A",
            groups=[
                VariableGroup(
                    label="G",
                    variables=[
                        _make_variable("SEXP", "Sex"),
                        _make_variable("AGEP", "Age"),
                        _make_variable("RARE", "Rare Variable"),
                    ],
                ),
            ],
        )
        tree_b = DatasetTree(
            dataset_name="Dataset B",
            groups=[
                VariableGroup(
                    label="G",
                    variables=[
                        _make_variable("SEXP", "Sex"),
                        _make_variable("AGEP", "Age"),
                    ],
                ),
            ],
        )
        tree_c = DatasetTree(
            dataset_name="Dataset C",
            groups=[
                VariableGroup(
                    label="G",
                    variables=[_make_variable("SEXP", "Sex")],
                ),
            ],
        )
        result = _format_cross_reference([tree_a, tree_b, tree_c])

        # SEXP in 3 datasets should come before AGEP in 2, then RARE in 1
        sexp_pos = result.index("SEXP")
        agep_pos = result.index("AGEP")
        rare_pos = result.index("RARE")
        assert sexp_pos < agep_pos < rare_pos

        assert "3 datasets" in result
        assert "2 datasets" in result
        assert "1 datasets" in result

    def test_cross_reference_alphabetical_within_tier(self):
        """Variables with the same frequency are sorted alphabetically by code."""
        tree = DatasetTree(
            dataset_name="Dataset",
            groups=[
                VariableGroup(
                    label="G",
                    variables=[
                        _make_variable("ZEBRA", "Zebra Var"),
                        _make_variable("APPLE", "Apple Var"),
                        _make_variable("MANGO", "Mango Var"),
                    ],
                ),
            ],
        )
        result = _format_cross_reference([tree])

        apple_pos = result.index("APPLE")
        mango_pos = result.index("MANGO")
        zebra_pos = result.index("ZEBRA")
        assert apple_pos < mango_pos < zebra_pos

    def test_single_dataset(self):
        """Cross-reference works correctly with a single dataset."""
        tree = DatasetTree(
            dataset_name="Only Dataset",
            groups=[
                VariableGroup(
                    label="G",
                    variables=[_make_variable("VAR1", "First")],
                ),
            ],
        )
        result = _format_cross_reference([tree])

        assert "VAR1" in result
        assert "First" in result
        assert "1 datasets" in result
        assert "## Variable Cross-Reference" in result
        assert "| Variable | Description | Datasets |" in result


class TestFormatDataDictionary:
    @patch("tablebuilder.dict_formatter.date")
    def test_full_document_has_toc_and_sections(self, mock_date):
        """Full document contains title, date, TOC, sections, and cross-ref."""
        mock_date.today.return_value = date(2026, 3, 4)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        tree_a = DatasetTree(
            dataset_name="dataset alpha",
            geographies=["Australia"],
            groups=[
                VariableGroup(
                    label="Group A",
                    variables=[_make_variable("V1", "Var One")],
                ),
            ],
        )
        tree_b = DatasetTree(
            dataset_name="dataset beta",
            geographies=["States"],
            groups=[
                VariableGroup(
                    label="Group B",
                    variables=[_make_variable("V2", "Var Two")],
                ),
            ],
        )
        result = format_data_dictionary([tree_a, tree_b])

        # Title and date
        assert "# ABS TableBuilder Data Dictionary" in result
        assert "2026-03-04" in result
        # TOC
        assert "## Table of Contents" in result
        assert "1. [dataset alpha](#dataset-alpha)" in result
        assert "2. [dataset beta](#dataset-beta)" in result
        # Sections present
        assert "## dataset alpha" in result
        assert "## dataset beta" in result
        # Cross-reference present
        assert "## Variable Cross-Reference" in result

    @patch("tablebuilder.dict_formatter.date")
    def test_title_customization(self, mock_date):
        """Custom title replaces the default."""
        mock_date.today.return_value = date(2026, 3, 4)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        tree = DatasetTree(
            dataset_name="test",
            groups=[
                VariableGroup(
                    label="G",
                    variables=[_make_variable("V1", "V")],
                ),
            ],
        )
        result = format_data_dictionary([tree], title="My Custom Title")

        assert "# My Custom Title" in result
        assert "ABS TableBuilder Data Dictionary" not in result

    @patch("tablebuilder.dict_formatter.date")
    def test_sections_separated_by_dividers(self, mock_date):
        """Horizontal rules (---) separate each dataset section."""
        mock_date.today.return_value = date(2026, 3, 4)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        tree_a = DatasetTree(
            dataset_name="first",
            groups=[
                VariableGroup(
                    label="G",
                    variables=[_make_variable("V1", "V")],
                ),
            ],
        )
        tree_b = DatasetTree(
            dataset_name="second",
            groups=[
                VariableGroup(
                    label="G",
                    variables=[_make_variable("V2", "V")],
                ),
            ],
        )
        result = format_data_dictionary([tree_a, tree_b])

        # There should be dividers between sections
        assert result.count("---") >= 3  # after TOC, between sections, before cross-ref


class TestSlugify:
    def test_simple_name(self):
        """Simple space-separated name becomes hyphenated lowercase."""
        assert _slugify("my dataset") == "my-dataset"

    def test_special_characters(self):
        """Special characters like commas are removed."""
        result = _slugify("Census 2021 - Employment, Income")
        assert result == "census-2021---employment-income"

    def test_multiple_spaces(self):
        """Multiple spaces become multiple hyphens (matching anchor behavior)."""
        result = _slugify("foo  bar")
        assert result == "foo--bar"
