# ABOUTME: Integration tests for the HTTP client against real ABS TableBuilder.
# ABOUTME: Requires ABS credentials; run on totoro with: uv run pytest tests/test_http_integration.py -v -m integration

import os
from pathlib import Path

import pytest

from tablebuilder.config import load_config, ConfigError
from tablebuilder.http_session import TableBuilderHTTPSession
from tablebuilder.http_catalogue import find_database, open_database, get_schema, find_variable
from tablebuilder.http_table import http_fetch_table
from tablebuilder.models import TableRequest


def _has_credentials():
    try:
        load_config()
        return True
    except ConfigError:
        return False


skip_no_creds = pytest.mark.skipif(
    not _has_credentials(),
    reason="No ABS credentials configured",
)


@pytest.mark.integration
@skip_no_creds
class TestHTTPLogin:
    def test_login_succeeds(self):
        """HTTP login reaches the catalogue page and sets ViewState."""
        config = load_config()
        with TableBuilderHTTPSession(config) as session:
            assert session.viewstate is not None
            assert len(session.viewstate) > 10
            assert "dataCatalogueExplorer" in session.catalogue_html


@pytest.mark.integration
@skip_no_creds
class TestHTTPCatalogue:
    def test_get_catalogue_returns_databases(self):
        """Catalogue tree contains database nodes."""
        config = load_config()
        with TableBuilderHTTPSession(config) as session:
            tree = session.rest_get("/rest/catalogue/databases/tree")
            assert "nodeList" in tree
            assert len(tree["nodeList"]) > 0

    def test_find_2021_census(self):
        """Can find the 2021 Census PersonsEN database."""
        config = load_config()
        with TableBuilderHTTPSession(config) as session:
            tree = session.rest_get("/rest/catalogue/databases/tree")
            result = find_database(tree, "counting persons, place of enumeration")
            assert result is not None
            path, node = result
            assert "2021" in node["data"]["name"].lower() or "counting persons" in node["data"]["name"].lower()

    def test_open_database_and_get_schema(self):
        """Can open a database and retrieve the variable schema."""
        config = load_config()
        with TableBuilderHTTPSession(config) as session:
            tree = session.rest_get("/rest/catalogue/databases/tree")
            result = find_database(tree, "counting persons, place of enumeration")
            assert result is not None
            path, node = result
            open_database(session, path)
            schema = get_schema(session)
            assert len(schema) > 0
            # Should have SEXP Sex
            sex_var = find_variable(schema, "SEXP Sex")
            assert sex_var is not None
            assert sex_var["child_count"] >= 2


@pytest.mark.integration
@skip_no_creds
class TestHTTPFetchTable:
    def test_fetch_sex_by_row(self, tmp_path):
        """Full pipeline: fetch SEXP Sex as rows and download CSV."""
        config = load_config()
        output = str(tmp_path / "sex_test.csv")
        request = TableRequest(
            dataset="2021 Census - counting persons, place of enumeration",
            rows=["SEXP Sex"],
        )
        with TableBuilderHTTPSession(config) as session:
            http_fetch_table(session, request, output)

        assert Path(output).exists()
        content = Path(output).read_text()
        assert len(content) > 50
        # Should contain census data
        assert "," in content  # CSV format
