# ABOUTME: End-to-end integration tests for the full CLI flow.
# ABOUTME: Tests real browser automation against ABS TableBuilder.

import pytest
from click.testing import CliRunner

from tablebuilder.cli import cli


@pytest.mark.integration
class TestEndToEnd:
    def test_fetch_produces_csv(self, tmp_path, abs_config):
        """Full fetch command produces a CSV file."""
        output = tmp_path / "result.csv"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "fetch",
                "--dataset", "Census 2021",
                "--rows", "Sex",
                "--user-id", abs_config.user_id,
                "--password", abs_config.password,
                "-o", str(output),
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert output.exists()
        content = output.read_text()
        assert len(content) > 0

    def test_datasets_command(self, abs_config):
        """datasets command lists available datasets."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "datasets",
                "--user-id", abs_config.user_id,
                "--password", abs_config.password,
            ],
        )
        assert result.exit_code == 0
        assert "Census" in result.output
