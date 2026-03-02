# ABOUTME: Tests for the KnowledgeBase persistence and accumulation.
# ABOUTME: Uses tmp_path to isolate each test's knowledge file.

import json

from tablebuilder.knowledge import KnowledgeBase


class TestCreatesFileIfMissing:
    """Verify KnowledgeBase creates the JSON file on save when it doesn't exist."""

    def test_creates_file_if_missing(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        assert not kb_path.exists()

        kb = KnowledgeBase(path=kb_path)
        kb.save()

        assert kb_path.exists()
        data = json.loads(kb_path.read_text())
        assert data["version"] == 1
        assert data["run_count"] == 0


class TestRecordSelectorSuccessPersists:
    """Verify that recording a selector success persists across reloads."""

    def test_record_selector_success_persists(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        kb = KnowledgeBase(path=kb_path)
        kb.record_selector_success("search_button", "#search-btn")
        kb.save()

        kb2 = KnowledgeBase(path=kb_path)
        assert kb2.get_preferred_selector("search_button") == "#search-btn"
        assert kb2.selectors["search_button"]["success_count"] == 1
        assert kb2.selectors["search_button"]["last_success"] is not None


class TestRecordSelectorFailureAppends:
    """Verify that recording multiple failures appends to the list with deduplication."""

    def test_record_selector_failure_appends(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        kb = KnowledgeBase(path=kb_path)

        kb.record_selector_failure("search_button", "#old-btn")
        kb.record_selector_failure("search_button", ".search-fallback")
        kb.record_selector_failure("search_button", "#old-btn")  # duplicate

        failed = kb.selectors["search_button"]["failed_selectors"]
        assert "#old-btn" in failed
        assert ".search-fallback" in failed
        assert len(failed) == 2  # deduped


class TestGetPreferredSelectorReturnsNoneForUnknown:
    """Verify that get_preferred_selector returns None for an unknown name."""

    def test_get_preferred_selector_returns_none_for_unknown(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        kb = KnowledgeBase(path=kb_path)
        assert kb.get_preferred_selector("nonexistent_element") is None


class TestRecordTimingComputesRunningAverage:
    """Verify that recording timings computes a running average correctly."""

    def test_record_timing_computes_running_average(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        kb = KnowledgeBase(path=kb_path)

        kb.record_timing("page_load", 10.0)
        assert kb.get_expected_timing("page_load") == 10.0

        kb.record_timing("page_load", 20.0)
        assert kb.get_expected_timing("page_load") == 15.0

        # Unknown operation returns None
        assert kb.get_expected_timing("unknown_op") is None


class TestSaveLoadRoundtrip:
    """Verify full save/load roundtrip preserves all data."""

    def test_save_load_roundtrip(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        kb = KnowledgeBase(path=kb_path)

        # Populate everything
        kb.record_selector_success("btn_a", "#a-primary")
        kb.record_selector_failure("btn_a", "#a-old")
        kb.record_timing("download", 5.5)
        kb.record_dataset_quirk("census_2021", "slow_load", "Takes 30s to render")
        kb.record_run()
        kb.save()

        # Reload from the same path
        kb2 = KnowledgeBase(path=kb_path)

        assert kb2.get_preferred_selector("btn_a") == "#a-primary"
        assert "#a-old" in kb2.selectors["btn_a"]["failed_selectors"]
        assert kb2.get_expected_timing("download") == 5.5
        assert len(kb2.get_dataset_quirks("census_2021")) == 1
        assert kb2.get_dataset_quirks("census_2021")[0]["quirk_type"] == "slow_load"
        assert kb2.run_count == 1
        assert kb2.last_run is not None


class TestSummaryReturnsCorrectStats:
    """Verify summary() returns correct aggregate statistics."""

    def test_summary_returns_correct_stats(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        kb = KnowledgeBase(path=kb_path)

        kb.record_run()
        kb.record_run()
        kb.record_selector_success("btn_a", "#a-primary")
        kb.record_selector_success("btn_b", "#b-fallback")
        kb.record_dataset_quirk("census", "slow", "Takes a while")

        summary = kb.summary()
        assert summary["run_count"] == 2
        assert summary["last_run"] is not None
        assert summary["selector_count"] == 2
        assert summary["quirk_count"] == 1
        # selectors_using_fallback: we can't tell without knowing the primary,
        # so it counts selectors that have a working_selector set
        assert isinstance(summary["selectors_using_fallback"], int)


class TestCorruptJsonRecoversGracefully:
    """Verify that a corrupt JSON file is handled gracefully by starting fresh."""

    def test_corrupt_json_recovers_gracefully(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        kb_path.parent.mkdir(parents=True, exist_ok=True)
        kb_path.write_text("{this is not valid json!!!")

        kb = KnowledgeBase(path=kb_path)

        # Should start fresh, not raise
        assert kb.run_count == 0
        assert kb.selectors == {}
        assert kb.timings == {}
        assert kb.dataset_quirks == []
