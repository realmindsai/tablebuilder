# ABOUTME: Tests for TableBuilder data models.
# ABOUTME: Validates TableRequest construction and validation rules.

import pytest

from tablebuilder.models import Axis, TableRequest


class TestTableRequest:
    def test_valid_request_with_rows_only(self):
        """A request with dataset and rows is valid."""
        req = TableRequest(
            dataset="Census 2021 Basic",
            rows=["Age", "Sex"],
        )
        assert req.dataset == "Census 2021 Basic"
        assert req.rows == ["Age", "Sex"]
        assert req.cols == []
        assert req.wafers == []

    def test_valid_request_with_all_axes(self):
        """A request can have rows, cols, and wafers."""
        req = TableRequest(
            dataset="Census 2021 Basic",
            rows=["Age"],
            cols=["Sex"],
            wafers=["State"],
        )
        assert req.rows == ["Age"]
        assert req.cols == ["Sex"]
        assert req.wafers == ["State"]

    def test_rejects_empty_dataset(self):
        """Dataset name cannot be empty."""
        with pytest.raises(ValueError, match="dataset"):
            TableRequest(dataset="", rows=["Age"])

    def test_rejects_empty_rows_without_geography(self):
        """Empty rows without geography raises ValueError."""
        with pytest.raises(ValueError, match="rows.*geography"):
            TableRequest(dataset="Census 2021 Basic", rows=[])

    def test_rejects_no_rows_without_geography(self):
        """Missing rows without geography raises ValueError."""
        with pytest.raises(ValueError, match="rows.*geography"):
            TableRequest(dataset="Census 2021 Basic")

    def test_all_variables_returns_flat_list(self):
        """all_variables() returns every variable across all axes."""
        req = TableRequest(
            dataset="Census 2021 Basic",
            rows=["Age", "Sex"],
            cols=["State"],
            wafers=["Year"],
        )
        assert req.all_variables() == ["Age", "Sex", "State", "Year"]

    def test_variable_axes_returns_mapping(self):
        """variable_axes() maps each variable to its axis."""
        req = TableRequest(
            dataset="Census 2021 Basic",
            rows=["Age"],
            cols=["Sex"],
        )
        axes = req.variable_axes()
        assert axes == {"Age": Axis.ROW, "Sex": Axis.COL}


class TestTableRequestGeography:
    def test_geography_only_valid(self):
        """A request with dataset and geography (no rows) is valid."""
        req = TableRequest(
            dataset="Census 2021",
            geography="Remoteness Areas",
        )
        assert req.geography == "Remoteness Areas"
        assert req.geo_filter is None

    def test_geo_filter_without_geography_raises(self):
        """geo_filter without geography raises ValueError."""
        with pytest.raises(ValueError, match="geo_filter"):
            TableRequest(
                dataset="Census 2021",
                rows=["Age"],
                geo_filter="South Australia",
            )

    def test_no_rows_no_geography_raises(self):
        """Neither rows nor geography raises ValueError."""
        with pytest.raises(ValueError, match="rows.*geography"):
            TableRequest(
                dataset="Census 2021",
                rows=[],
            )


class TestAxis:
    def test_axis_values(self):
        """Axis enum has ROW, COL, WAFER."""
        assert Axis.ROW.value == "row"
        assert Axis.COL.value == "col"
        assert Axis.WAFER.value == "wafer"
