# ABOUTME: Tests for table construction (adding variables to rows/cols/wafers).
# ABOUTME: Includes unit tests for geography selection and integration tests for the real UI.

import pytest
from unittest.mock import MagicMock, patch

from tablebuilder.table_builder import add_variable, build_table, select_geography, TableBuildError
from tablebuilder.models import Axis, TableRequest


class TestTableBuildError:
    def test_error_is_exception(self):
        """TableBuildError is a proper exception."""
        err = TableBuildError("test")
        assert str(err) == "test"
        assert isinstance(err, Exception)


class TestSelectGeographyErrors:
    def test_missing_group_raises(self):
        """TableBuildError when no 'Geographical Areas' group in tree."""
        page = MagicMock()
        page.query_selector_all.return_value = []
        page.wait_for_timeout = MagicMock()

        with pytest.raises(TableBuildError, match="No geography group found"):
            select_geography(page, "Remoteness Areas")

    def test_missing_level_raises(self):
        """TableBuildError when geography level not found under group."""
        page = MagicMock()
        page.wait_for_timeout = MagicMock()

        # First call: _find_geography_group queries labels
        geo_label = MagicMock()
        geo_label.text_content.return_value = "Geographical Areas (Usual Residence)"
        geo_node = MagicMock()
        geo_label.evaluate_handle.return_value = geo_node
        geo_node.as_element.return_value = geo_node
        expander = MagicMock()
        expander.get_attribute.return_value = 'treeNodeExpander collapsed'
        geo_node.query_selector.return_value = expander

        other_label = MagicMock()
        other_label.text_content.return_value = "Age and Sex"

        # page.query_selector_all is called multiple times:
        # 1st for _find_geography_group, 2nd for _find_geography_level
        page.query_selector_all.side_effect = [
            [geo_label, other_label],  # _find_geography_group
            [geo_label, other_label],  # _find_geography_level (no matching level)
        ]

        with pytest.raises(TableBuildError, match="Geography level"):
            select_geography(page, "Nonexistent Level")

    def test_missing_filter_raises(self):
        """TableBuildError when geo_filter state not found."""
        page = MagicMock()
        page.wait_for_timeout = MagicMock()

        # _find_geography_group
        geo_label = MagicMock()
        geo_label.text_content.return_value = "Geographical Areas (Usual Residence)"
        geo_node = MagicMock()
        geo_label.evaluate_handle.return_value = geo_node
        geo_node.as_element.return_value = geo_node
        geo_expander = MagicMock()
        geo_expander.get_attribute.return_value = 'treeNodeExpander collapsed'
        geo_node.query_selector.return_value = geo_expander

        # _find_geography_level - a matching level
        level_label = MagicMock()
        level_label.text_content.return_value = "Remoteness Areas (UR)"

        # _find_and_check_states - no matching state nodes
        page.query_selector_all.side_effect = [
            [geo_label, level_label],  # _find_geography_group
            [geo_label, level_label],  # _find_geography_level
            [],  # _find_and_check_states - no tree nodes
        ]

        with pytest.raises(TableBuildError, match="state.*not found"):
            select_geography(page, "Remoteness Areas", geo_filter="Nonexistent State")


@pytest.mark.integration
class TestAddVariableIntegration:
    def test_add_variable_to_row(self, abs_page_with_dataset):
        """Can add a variable to rows."""
        add_variable(abs_page_with_dataset, "Age", Axis.ROW)
        # Verify the variable appears in the row area
        assert abs_page_with_dataset.query_selector("text=Age")

    def test_add_variable_to_column(self, abs_page_with_dataset):
        """Can add a variable to columns."""
        add_variable(abs_page_with_dataset, "Sex", Axis.COL)
        assert abs_page_with_dataset.query_selector("text=Sex")


@pytest.mark.integration
class TestBuildTableIntegration:
    def test_build_simple_table(self, abs_page_with_dataset):
        """Can build a table with rows and columns."""
        request = TableRequest(
            dataset="Census 2021 Basic",
            rows=["Age"],
            cols=["Sex"],
        )
        build_table(abs_page_with_dataset, request)
