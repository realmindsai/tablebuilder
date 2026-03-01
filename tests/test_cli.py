# ABOUTME: Tests for the Click CLI interface.
# ABOUTME: Validates flag parsing, required arguments, and help output.

from click.testing import CliRunner

from tablebuilder.cli import cli


class TestCliHelp:
    def test_main_help_shows_commands(self):
        """Top-level --help lists fetch, datasets, variables."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "fetch" in result.output
        assert "datasets" in result.output
        assert "variables" in result.output

    def test_fetch_help_shows_flags(self):
        """fetch --help lists --dataset, --rows, --cols, --wafers, --output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--help"])
        assert result.exit_code == 0
        assert "--dataset" in result.output
        assert "--rows" in result.output
        assert "--cols" in result.output
        assert "--wafers" in result.output
        assert "--output" in result.output


class TestCliFetch:
    def test_fetch_requires_dataset(self):
        """fetch without --dataset exits with error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--rows", "Age"])
        assert result.exit_code != 0

    def test_fetch_requires_rows(self):
        """fetch without --rows exits with error."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["fetch", "--dataset", "Census 2021 Basic"]
        )
        assert result.exit_code != 0
