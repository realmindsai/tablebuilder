# ABOUTME: Tests for the Click CLI interface.
# ABOUTME: Validates flag parsing, required arguments, and help output.

from click.testing import CliRunner

from tablebuilder.cli import cli


class TestCliHelp:
    def test_main_help_shows_commands(self):
        """Top-level --help lists fetch, datasets, dictionary."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "fetch" in result.output
        assert "datasets" in result.output
        assert "dictionary" in result.output

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


class TestCliDictionary:
    def test_dictionary_help_shows_flags(self):
        """dictionary --help lists --dataset, --output, --exclude-census, --resume."""
        runner = CliRunner()
        result = runner.invoke(cli, ["dictionary", "--help"])
        assert result.exit_code == 0
        assert "--dataset" in result.output
        assert "--output" in result.output
        assert "--exclude-census" in result.output
        assert "--resume" in result.output
        assert "--clear-cache" in result.output

    def test_dictionary_help_shows_headed(self):
        """dictionary --help lists --headed for debugging."""
        runner = CliRunner()
        result = runner.invoke(cli, ["dictionary", "--help"])
        assert result.exit_code == 0
        assert "--headed" in result.output


class TestCliSearch:
    def test_search_help_shows_query(self):
        """search --help shows the QUERY argument."""
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "QUERY" in result.output or "query" in result.output

    def test_search_help_shows_limit(self):
        """search --help shows --limit option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "--limit" in result.output


class TestCliDictionaryRebuildDb:
    def test_dictionary_help_shows_rebuild_db(self):
        """dictionary --help lists --rebuild-db."""
        runner = CliRunner()
        result = runner.invoke(cli, ["dictionary", "--help"])
        assert result.exit_code == 0
        assert "--rebuild-db" in result.output


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
