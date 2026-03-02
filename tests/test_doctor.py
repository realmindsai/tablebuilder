# ABOUTME: Tests for the doctor CLI command and its formatting logic.
# ABOUTME: Validates health report output for fresh, populated, and misconfigured states.

from unittest.mock import patch

from click.testing import CliRunner

from tablebuilder.cli import cli
from tablebuilder.doctor import run_doctor
from tablebuilder.knowledge import KnowledgeBase


class TestRunDoctorFresh:
    """Tests for run_doctor with a fresh (empty) knowledge base."""

    def test_fresh_knowledge_shows_zero_runs(self, tmp_path):
        """A brand new knowledge base reports 0 runs."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        output = run_doctor(kb, credentials_ok=True)
        assert "0 runs" in output

    def test_fresh_knowledge_shows_header(self, tmp_path):
        """Output starts with the doctor header."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        output = run_doctor(kb, credentials_ok=True)
        assert "TableBuilder Doctor" in output
        assert "==================" in output

    def test_fresh_knowledge_shows_healthy(self, tmp_path):
        """With credentials present and no issues, status is Healthy."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        output = run_doctor(kb, credentials_ok=True)
        assert "Healthy" in output

    def test_fresh_knowledge_shows_no_timings(self, tmp_path):
        """A fresh KB with no timings shows 'No timing data yet'."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        output = run_doctor(kb, credentials_ok=True)
        assert "No timing data yet" in output

    def test_fresh_knowledge_shows_no_quirks(self, tmp_path):
        """A fresh KB has no dataset quirks."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        output = run_doctor(kb, credentials_ok=True)
        assert "None recorded" in output

    def test_fresh_knowledge_shows_selector_count(self, tmp_path):
        """Selector count comes from ALL_SELECTORS, not from KB."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        output = run_doctor(kb, credentials_ok=True)
        # ALL_SELECTORS has 19 entries
        assert "19 selectors registered" in output


class TestRunDoctorPopulated:
    """Tests for run_doctor with a populated knowledge base."""

    def test_populated_shows_run_count(self, tmp_path):
        """A KB with runs shows the correct run count."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        for _ in range(42):
            kb.record_run()
        output = run_doctor(kb, credentials_ok=True)
        assert "42 runs" in output

    def test_populated_shows_last_run(self, tmp_path):
        """A KB with runs shows the last run timestamp."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        kb.record_run()
        output = run_doctor(kb, credentials_ok=True)
        # last_run is an ISO datetime string; just verify something date-like appears
        assert "last:" in output

    def test_populated_shows_timings(self, tmp_path):
        """A KB with timing data shows formatted averages."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        kb.record_timing("login", 8.5)
        kb.record_timing("login", 8.5)
        output = run_doctor(kb, credentials_ok=True)
        assert "login" in output
        assert "8.5s avg" in output
        assert "2 samples" in output

    def test_populated_shows_quirks(self, tmp_path):
        """A KB with dataset quirks lists them."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        kb.record_dataset_quirk("Census 2021", "slow_load", "Takes 30s to open")
        output = run_doctor(kb, credentials_ok=True)
        assert "Census 2021" in output
        assert "slow_load" in output
        assert "Takes 30s to open" in output

    def test_populated_shows_selectors_using_fallback(self, tmp_path):
        """A KB with selector overrides reports them."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        kb.record_selector_success("LOGIN_USERNAME", 'input[name*="username"]')
        output = run_doctor(kb, credentials_ok=True)
        assert "1 using fallback selectors" in output

    def test_populated_no_fallbacks_shows_all_primary(self, tmp_path):
        """When selectors are registered but none has a fallback override, report 'all using primary'."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        output = run_doctor(kb, credentials_ok=True)
        assert "0 using fallback selectors" in output
        assert "all using primary" in output


class TestRunDoctorMissingCredentials:
    """Tests for run_doctor when credentials are not configured."""

    def test_missing_credentials_shows_not_found(self, tmp_path):
        """When credentials_ok=False, output shows NOT FOUND."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        output = run_doctor(kb, credentials_ok=False)
        assert "NOT FOUND" in output

    def test_missing_credentials_shows_needs_configuration(self, tmp_path):
        """When credentials are missing, status is 'Needs Configuration'."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        output = run_doctor(kb, credentials_ok=False)
        assert "Needs Configuration" in output

    def test_missing_credentials_shows_env_path(self, tmp_path):
        """When credentials are missing, output mentions the .env path."""
        kb = KnowledgeBase(path=tmp_path / "knowledge.json")
        output = run_doctor(kb, credentials_ok=False)
        assert "~/.tablebuilder/.env" in output
        assert "TABLEBUILDER_USER_ID" in output
        assert "TABLEBUILDER_PASSWORD" in output


class TestDoctorCliCommand:
    """Tests for the doctor CLI command invoked via CliRunner."""

    def test_doctor_appears_in_help(self):
        """The doctor command shows up in top-level --help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "doctor" in result.output

    def test_doctor_exits_zero(self):
        """doctor command exits cleanly."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_doctor_shows_header(self):
        """doctor command output contains the header."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"], catch_exceptions=False)
        assert "TableBuilder Doctor" in result.output

    @patch("tablebuilder.doctor.load_config")
    def test_doctor_with_config_error_shows_not_found(self, mock_config):
        """When load_config raises ConfigError, doctor shows NOT FOUND."""
        from tablebuilder.config import ConfigError

        mock_config.side_effect = ConfigError("missing")
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "NOT FOUND" in result.output
