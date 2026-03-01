# ABOUTME: Tests for table construction (adding variables to rows/cols/wafers).
# ABOUTME: Primarily integration tests that drive the real TableBuilder UI.

import pytest

from tablebuilder.table_builder import add_variable, build_table, TableBuildError
from tablebuilder.models import Axis, TableRequest


class TestTableBuildError:
    def test_error_is_exception(self):
        """TableBuildError is a proper exception."""
        err = TableBuildError("test")
        assert str(err) == "test"
        assert isinstance(err, Exception)


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
