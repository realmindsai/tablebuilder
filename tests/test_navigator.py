# ABOUTME: Tests for dataset and variable navigation in TableBuilder.
# ABOUTME: Unit tests for fuzzy matching; integration tests for real UI navigation.

import pytest

from tablebuilder.navigator import fuzzy_match_dataset, NavigationError, SessionExpiredError


class TestFuzzyMatch:
    def test_exact_match(self):
        """Exact name matches perfectly."""
        datasets = ["Census 2021 Basic", "Labour Force", "CPI"]
        assert fuzzy_match_dataset("Census 2021 Basic", datasets) == "Census 2021 Basic"

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        datasets = ["Census 2021 Basic", "Labour Force"]
        assert fuzzy_match_dataset("census 2021 basic", datasets) == "Census 2021 Basic"

    def test_partial_match(self):
        """Substring match works."""
        datasets = [
            "Census 2021, Basic TableBuilder",
            "Census 2021, Pro TableBuilder",
        ]
        assert "Basic" in fuzzy_match_dataset("Census 2021 Basic", datasets)

    def test_no_match_raises(self):
        """No matching dataset raises NavigationError."""
        datasets = ["Labour Force", "CPI"]
        with pytest.raises(NavigationError, match="No dataset matching"):
            fuzzy_match_dataset("Census 2021", datasets)

    def test_no_match_suggests_alternatives(self):
        """Error message includes available dataset names."""
        datasets = ["Labour Force Survey", "CPI Quarterly"]
        with pytest.raises(NavigationError) as exc_info:
            fuzzy_match_dataset("Census", datasets)
        assert "Labour Force Survey" in str(exc_info.value)


class TestSessionExpiredError:
    def test_is_navigation_error_subclass(self):
        """SessionExpiredError is a subclass of NavigationError."""
        err = SessionExpiredError("session died")
        assert isinstance(err, NavigationError)

    def test_message(self):
        """SessionExpiredError carries its message."""
        err = SessionExpiredError("session died")
        assert str(err) == "session died"


@pytest.mark.integration
class TestNavigatorIntegration:
    def test_list_datasets(self, abs_page):
        """Can list available datasets from the home page."""
        from tablebuilder.navigator import list_datasets

        datasets = list_datasets(abs_page)
        assert len(datasets) > 0
        # Census datasets should be available
        assert any("Census" in d for d in datasets)

    def test_open_dataset(self, abs_page):
        """Can open a dataset and reach the Table View."""
        from tablebuilder.navigator import open_dataset

        open_dataset(abs_page, "Census 2021")
        # Should be in Table View now — look for variable panel
        abs_page.wait_for_selector("text=Add to Row", timeout=15000)
