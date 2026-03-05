# ABOUTME: Data classes for TableBuilder requests and configuration.
# ABOUTME: TableRequest defines what data to fetch; Axis defines row/col/wafer placement.

from dataclasses import dataclass, field
from enum import Enum


class Axis(Enum):
    ROW = "row"
    COL = "col"
    WAFER = "wafer"


@dataclass
class TableRequest:
    """Describes a table to fetch from ABS TableBuilder."""

    dataset: str
    rows: list[str] = field(default_factory=list)
    cols: list[str] = field(default_factory=list)
    wafers: list[str] = field(default_factory=list)
    geography: str | None = None
    geo_filter: str | None = None

    def __post_init__(self):
        if not self.dataset or not self.dataset.strip():
            raise ValueError("dataset name cannot be empty")
        if self.geo_filter and not self.geography:
            raise ValueError("geo_filter requires geography to be set")
        if not self.rows and not self.geography:
            raise ValueError("rows must contain at least one variable, or geography must be set")

    def all_variables(self) -> list[str]:
        """Return all variables across all axes in order."""
        return self.rows + self.cols + self.wafers

    def variable_axes(self) -> dict[str, Axis]:
        """Map each variable name to its target axis."""
        result: dict[str, Axis] = {}
        for var in self.rows:
            result[var] = Axis.ROW
        for var in self.cols:
            result[var] = Axis.COL
        for var in self.wafers:
            result[var] = Axis.WAFER
        return result


@dataclass
class CategoryInfo:
    """A single leaf category in a variable tree."""

    label: str


@dataclass
class VariableInfo:
    """A variable with its code and categories."""

    code: str
    label: str
    categories: list[CategoryInfo] = field(default_factory=list)


@dataclass
class VariableGroup:
    """A group of related variables."""

    label: str
    variables: list[VariableInfo] = field(default_factory=list)


@dataclass
class DatasetTree:
    """The complete variable tree for one dataset."""

    dataset_name: str
    geographies: list[str] = field(default_factory=list)
    groups: list[VariableGroup] = field(default_factory=list)
