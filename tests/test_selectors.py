# ABOUTME: Tests for the selector registry.
# ABOUTME: Validates all selector entries have required fields and no duplicates.

from tablebuilder.models import Axis
from tablebuilder.selectors import ALL_SELECTORS, AXIS_BUTTONS, SelectorEntry


class TestSelectorEntryFields:
    """Verify every selector in the registry has required fields populated."""

    def test_all_selectors_have_required_fields(self):
        """Each SelectorEntry must have non-empty name, primary, and at least one fallback."""
        assert len(ALL_SELECTORS) > 0, "ALL_SELECTORS should not be empty"
        for entry in ALL_SELECTORS:
            assert isinstance(entry, SelectorEntry), (
                f"Expected SelectorEntry, got {type(entry)}"
            )
            assert entry.name, f"Selector entry has empty name: {entry}"
            assert entry.primary, (
                f"Selector '{entry.name}' has empty primary selector"
            )
            assert len(entry.fallbacks) >= 1, (
                f"Selector '{entry.name}' must have at least one fallback"
            )
            for fb in entry.fallbacks:
                assert fb, (
                    f"Selector '{entry.name}' has an empty fallback string"
                )


class TestAxisButtonsMapping:
    """Verify the AXIS_BUTTONS dict covers all Axis values."""

    def test_axis_buttons_maps_all_axes(self):
        """AXIS_BUTTONS must have entries for ROW, COL, and WAFER."""
        assert Axis.ROW in AXIS_BUTTONS
        assert Axis.COL in AXIS_BUTTONS
        assert Axis.WAFER in AXIS_BUTTONS
        # Each mapped value should be a SelectorEntry
        for axis, entry in AXIS_BUTTONS.items():
            assert isinstance(entry, SelectorEntry), (
                f"AXIS_BUTTONS[{axis}] should be a SelectorEntry, got {type(entry)}"
            )


class TestNoDuplicateNames:
    """Verify no two selectors share the same name."""

    def test_no_duplicate_selector_names(self):
        """All entries in ALL_SELECTORS must have unique names."""
        names = [entry.name for entry in ALL_SELECTORS]
        duplicates = [n for n in names if names.count(n) > 1]
        assert len(duplicates) == 0, (
            f"Duplicate selector names found: {set(duplicates)}"
        )
