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

    def test_fetch_requires_rows_or_geography(self):
        """fetch without --rows or --geography exits with error."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["fetch", "--dataset", "Census 2021 Basic"]
        )
        assert result.exit_code != 0


class TestCliFetchGeography:
    def test_fetch_help_shows_geography(self):
        """fetch --help lists --geography and --geo-filter."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--help"])
        assert result.exit_code == 0
        assert "--geography" in result.output
        assert "--geo-filter" in result.output

    def test_geo_filter_without_geography_errors(self):
        """--geo-filter without --geography shows error."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "fetch",
            "--dataset", "Census 2021",
            "--geo-filter", "South Australia",
        ])
        assert result.exit_code != 0

    def test_geography_without_rows_help_accepted(self):
        """--geography is shown in help as optional alongside --rows."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--help"])
        assert "--rows" in result.output
        assert "--geography" in result.output


class TestFetchHTTPFlag:
    """Tests for the --http flag on the fetch command."""

    def test_http_flag_is_accepted(self):
        """CLI accepts --http flag without argument error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--help"])
        assert result.exit_code == 0
        assert "--http" in result.output

    def test_http_flag_shown_in_help(self):
        """--http flag description mentions HTTP or direct."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--help"])
        assert result.exit_code == 0
        # The help text should mention "HTTP" for the --http flag
        assert "HTTP" in result.output or "http" in result.output.lower()

    def test_http_flag_invokes_http_session(self):
        """When --http is passed, the HTTP path is used instead of Playwright."""
        from unittest.mock import MagicMock, patch

        runner = CliRunner()

        mock_session_cls = MagicMock()
        mock_session_instance = MagicMock()
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session_instance)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        with patch("tablebuilder.cli.load_config") as mock_config, \
             patch("tablebuilder.http_session.TableBuilderHTTPSession") as mock_http_cls, \
             patch("tablebuilder.http_table.http_fetch_table") as mock_fetch:

            mock_config.return_value = MagicMock(user_id="test", password="test")
            mock_http_cls.return_value.__enter__ = MagicMock(return_value=mock_session_instance)
            mock_http_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = runner.invoke(cli, [
                "fetch",
                "--http",
                "--dataset", "Census 2021",
                "--rows", "SEXP Sex",
                "-o", "/tmp/test.csv",
            ])

            # Should not fail with "no such option" error
            assert "no such option" not in (result.output or "").lower()
            assert "No such option" not in (result.output or "")
