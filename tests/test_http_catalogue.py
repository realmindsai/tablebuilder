# ABOUTME: Tests for the HTTP catalogue module that navigates ABS TableBuilder databases.
# ABOUTME: Covers find_database, open_database, get_schema, and find_variable functions.

from unittest.mock import MagicMock, call

import pytest

from tablebuilder.http_session import BASE_URL


# ── Sample data ──────────────────────────────────────────────────────


SAMPLE_CATALOGUE_TREE = {
    "nodeList": [
        {
            "key": "root_key",
            "data": {"type": "FOLDER", "name": "Data"},
            "children": [
                {
                    "key": "folder1_key",
                    "data": {"type": "FOLDER", "name": "Census"},
                    "children": [
                        {
                            "key": "db2021_key",
                            "data": {
                                "type": "DATABASE",
                                "name": "2021 Census - counting persons",
                            },
                            "children": [],
                        },
                        {
                            "key": "db2016_key",
                            "data": {
                                "type": "DATABASE",
                                "name": "2016 Census - counting persons",
                            },
                            "children": [],
                        },
                    ],
                },
                {
                    "key": "folder2_key",
                    "data": {"type": "FOLDER", "name": "Labour"},
                    "children": [
                        {
                            "key": "db_labour_key",
                            "data": {
                                "type": "DATABASE",
                                "name": "Labour Force Survey",
                            },
                            "children": [],
                        },
                    ],
                },
            ],
        }
    ]
}


SAMPLE_SCHEMA_TREE = {
    "nodeList": [
        {
            "key": "schema_root",
            "data": {
                "type": "ROOT",
                "name": "Variables",
                "iconType": "FOLDER",
                "draggable": False,
            },
            "children": [
                {
                    "key": "group_demographics",
                    "data": {
                        "type": "GROUP",
                        "name": "Demographics",
                        "iconType": "FOLDER",
                        "draggable": False,
                    },
                    "children": [
                        {
                            "key": "var_sexp",
                            "data": {
                                "type": "VARIABLE",
                                "name": "SEXP Sex",
                                "iconType": "FIELD",
                                "draggable": True,
                            },
                            "children": [
                                {
                                    "key": "cat_male",
                                    "data": {
                                        "type": "CATEGORY",
                                        "name": "Male",
                                        "iconType": "LEAF",
                                        "draggable": False,
                                    },
                                    "children": [],
                                },
                                {
                                    "key": "cat_female",
                                    "data": {
                                        "type": "CATEGORY",
                                        "name": "Female",
                                        "iconType": "LEAF",
                                        "draggable": False,
                                    },
                                    "children": [],
                                },
                            ],
                        },
                        {
                            "key": "var_agep",
                            "data": {
                                "type": "VARIABLE",
                                "name": "AGEP Age",
                                "iconType": "FIELD",
                                "draggable": True,
                            },
                            "children": [
                                {
                                    "key": "cat_0_14",
                                    "data": {
                                        "type": "CATEGORY",
                                        "name": "0-14",
                                        "iconType": "LEAF",
                                        "draggable": False,
                                    },
                                    "children": [],
                                },
                            ],
                        },
                    ],
                },
                {
                    "key": "group_geography",
                    "data": {
                        "type": "GROUP",
                        "name": "Geography",
                        "iconType": "FOLDER",
                        "draggable": False,
                    },
                    "children": [
                        {
                            "key": "var_state",
                            "data": {
                                "type": "VARIABLE",
                                "name": "STATE State",
                                "iconType": "FIELD",
                                "draggable": True,
                            },
                            "children": [],
                        },
                    ],
                },
            ],
        }
    ]
}


TABLEVIEW_HTML = (
    "<html><body>"
    '<input type="hidden" name="javax.faces.ViewState" '
    'id="vs" value="tableview_viewstate" />'
    "<div>Table View</div>"
    "</body></html>"
)


# ── find_database tests ──────────────────────────────────────────────


class TestFindDatabase:
    """Tests for find_database() tree walker."""

    def test_finds_database_by_substring(self):
        """Finds a DATABASE node by a case-sensitive substring match."""
        from tablebuilder.http_catalogue import find_database

        result = find_database(SAMPLE_CATALOGUE_TREE, "2021 Census")
        assert result is not None
        path, node = result
        assert node["data"]["name"] == "2021 Census - counting persons"
        assert "db2021_key" in path

    def test_finds_database_case_insensitive(self):
        """Finds a DATABASE node regardless of case."""
        from tablebuilder.http_catalogue import find_database

        result = find_database(SAMPLE_CATALOGUE_TREE, "labour force")
        assert result is not None
        path, node = result
        assert node["data"]["name"] == "Labour Force Survey"

    def test_returns_none_for_missing_database(self):
        """Returns None when no DATABASE matches the fragment."""
        from tablebuilder.http_catalogue import find_database

        result = find_database(SAMPLE_CATALOGUE_TREE, "nonexistent database xyz")
        assert result is None

    def test_does_not_match_folder_nodes(self):
        """Does not match FOLDER nodes, only DATABASE nodes."""
        from tablebuilder.http_catalogue import find_database

        # "Census" matches a FOLDER name but not a DATABASE name exactly
        result = find_database(SAMPLE_CATALOGUE_TREE, "Census")
        assert result is not None
        # Should match the DATABASE node that contains "Census", not the folder
        _, node = result
        assert node["data"]["type"] == "DATABASE"

    def test_returns_path_of_keys(self):
        """Returned path contains keys from root to the matched node."""
        from tablebuilder.http_catalogue import find_database

        result = find_database(SAMPLE_CATALOGUE_TREE, "2016 Census")
        assert result is not None
        path, node = result
        assert path == ["root_key", "folder1_key", "db2016_key"]

    def test_handles_empty_tree(self):
        """Returns None for an empty catalogue tree."""
        from tablebuilder.http_catalogue import find_database

        result = find_database({"nodeList": []}, "anything")
        assert result is None


# ── open_database tests ──────────────────────────────────────────────


class TestOpenDatabase:
    """Tests for open_database() which opens a database via REST + AJAX."""

    def test_sends_rest_post_with_path(self):
        """Sends a REST POST with the currentNode path."""
        from tablebuilder.http_catalogue import open_database

        session = MagicMock()
        session.rest_post.return_value = {}
        session.richfaces_ajax.return_value = MagicMock(text="<xml/>")
        get_resp = MagicMock()
        get_resp.text = TABLEVIEW_HTML
        session._session.get.return_value = get_resp

        path = ["root_key", "folder1_key", "db2021_key"]
        open_database(session, path)

        session.rest_post.assert_called_once_with(
            "/rest/catalogue/databases/tree",
            {"currentNode": path},
        )

    def test_fires_richfaces_ajax(self):
        """Fires a RichFaces AJAX doubleClickDatabase call."""
        from tablebuilder.http_catalogue import open_database

        session = MagicMock()
        session.rest_post.return_value = {}
        session.richfaces_ajax.return_value = MagicMock(text="<xml/>")
        get_resp = MagicMock()
        get_resp.text = TABLEVIEW_HTML
        session._session.get.return_value = get_resp

        path = ["root_key", "folder1_key", "db2021_key"]
        open_database(session, path)

        catalogue_url = f"{BASE_URL}/jsf/dataCatalogueExplorer.xhtml"
        session.richfaces_ajax.assert_called_once_with(
            catalogue_url,
            form_id="j_id_3f",
            component_id="j_id_3i",
            extra_params={"doubleClickDatabase": "doubleClickDatabase"},
        )

    def test_gets_tableview_and_updates_viewstate(self):
        """GETs the tableView page and updates session viewstate."""
        from tablebuilder.http_catalogue import open_database

        session = MagicMock()
        session.rest_post.return_value = {}
        session.richfaces_ajax.return_value = MagicMock(text="<xml/>")
        get_resp = MagicMock()
        get_resp.text = TABLEVIEW_HTML
        session._session.get.return_value = get_resp

        path = ["root_key", "folder1_key", "db2021_key"]
        open_database(session, path)

        tableview_url = f"{BASE_URL}/jsf/tableView/tableView.xhtml"
        session._session.get.assert_called_once_with(tableview_url)
        assert session._viewstate == "tableview_viewstate"

    def test_call_order(self):
        """Calls happen in order: rest_post, richfaces_ajax, GET tableView."""
        from tablebuilder.http_catalogue import open_database

        session = MagicMock()
        call_order = []

        session.rest_post.side_effect = lambda *a, **kw: call_order.append("rest_post")
        session.richfaces_ajax.side_effect = (
            lambda *a, **kw: call_order.append("richfaces_ajax") or MagicMock(text="")
        )
        get_resp = MagicMock()
        get_resp.text = TABLEVIEW_HTML
        session._session.get.side_effect = (
            lambda *a, **kw: call_order.append("get") or get_resp
        )

        open_database(session, ["k1", "k2", "k3"])

        assert call_order == ["rest_post", "richfaces_ajax", "get"]


# ── get_schema tests ─────────────────────────────────────────────────


class TestGetSchema:
    """Tests for get_schema() which fetches and parses the table schema tree."""

    def test_extracts_field_variables(self):
        """Extracts all FIELD/draggable variables from the schema tree."""
        from tablebuilder.http_catalogue import get_schema

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE

        schema = get_schema(session)

        assert "SEXP Sex" in schema
        assert "AGEP Age" in schema
        assert "STATE State" in schema
        assert len(schema) == 3

    def test_variable_has_key(self):
        """Each variable entry has the correct key from the tree."""
        from tablebuilder.http_catalogue import get_schema

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE

        schema = get_schema(session)

        assert schema["SEXP Sex"]["key"] == "var_sexp"
        assert schema["AGEP Age"]["key"] == "var_agep"

    def test_variable_has_group_path(self):
        """Each variable tracks its parent group hierarchy."""
        from tablebuilder.http_catalogue import get_schema

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE

        schema = get_schema(session)

        assert "Demographics" in schema["SEXP Sex"]["group"]
        assert "Geography" in schema["STATE State"]["group"]

    def test_variable_has_child_count(self):
        """Each variable reports how many children (categories) it has."""
        from tablebuilder.http_catalogue import get_schema

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE

        schema = get_schema(session)

        assert schema["SEXP Sex"]["child_count"] == 2
        assert schema["STATE State"]["child_count"] == 0

    def test_variable_has_levels(self):
        """Each variable lists the names of its category children."""
        from tablebuilder.http_catalogue import get_schema

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE

        schema = get_schema(session)

        assert schema["SEXP Sex"]["levels"] == ["Male", "Female"]
        assert schema["AGEP Age"]["levels"] == ["0-14"]
        assert schema["STATE State"]["levels"] == []

    def test_does_not_include_non_field_nodes(self):
        """Non-FIELD, non-draggable nodes (groups, categories) are excluded."""
        from tablebuilder.http_catalogue import get_schema

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE

        schema = get_schema(session)

        assert "Demographics" not in schema
        assert "Geography" not in schema
        assert "Male" not in schema

    def test_calls_correct_rest_endpoint(self):
        """get_schema calls the correct REST endpoint."""
        from tablebuilder.http_catalogue import get_schema

        session = MagicMock()
        session.rest_get.return_value = {"nodeList": []}

        get_schema(session)

        session.rest_get.assert_called_once_with(
            "/rest/catalogue/tableSchema/tree"
        )

    def test_handles_empty_schema(self):
        """Returns empty dict for a schema tree with no variables."""
        from tablebuilder.http_catalogue import get_schema

        session = MagicMock()
        session.rest_get.return_value = {"nodeList": []}

        schema = get_schema(session)
        assert schema == {}


# ── find_variable tests ──────────────────────────────────────────────


class TestFindVariable:
    """Tests for find_variable() which searches schema by name/code/substring."""

    def _sample_schema(self):
        """Build a schema dict matching what get_schema would return."""
        return {
            "SEXP Sex": {
                "key": "var_sexp",
                "group": "Demographics",
                "child_count": 2,
                "levels": ["Male", "Female"],
            },
            "AGEP Age": {
                "key": "var_agep",
                "group": "Demographics",
                "child_count": 1,
                "levels": ["0-14"],
            },
            "STATE State": {
                "key": "var_state",
                "group": "Geography",
                "child_count": 0,
                "levels": [],
            },
        }

    def test_exact_match(self):
        """Finds a variable by exact name match."""
        from tablebuilder.http_catalogue import find_variable

        result = find_variable(self._sample_schema(), "SEXP Sex")
        assert result is not None
        assert result["key"] == "var_sexp"

    def test_code_prefix_match(self):
        """Finds a variable by its code prefix (e.g., 'SEXP')."""
        from tablebuilder.http_catalogue import find_variable

        result = find_variable(self._sample_schema(), "SEXP")
        assert result is not None
        assert result["key"] == "var_sexp"

    def test_label_word_match(self):
        """Finds a variable by the label word (e.g., 'Sex')."""
        from tablebuilder.http_catalogue import find_variable

        result = find_variable(self._sample_schema(), "Sex")
        assert result is not None
        assert result["key"] == "var_sexp"

    def test_case_insensitive_substring(self):
        """Finds a variable by case-insensitive substring."""
        from tablebuilder.http_catalogue import find_variable

        result = find_variable(self._sample_schema(), "age")
        assert result is not None
        assert result["key"] == "var_agep"

    def test_returns_none_for_no_match(self):
        """Returns None when no variable matches."""
        from tablebuilder.http_catalogue import find_variable

        result = find_variable(self._sample_schema(), "ZZZNOTFOUND")
        assert result is None

    def test_exact_match_preferred_over_substring(self):
        """Exact match is preferred over substring match."""
        from tablebuilder.http_catalogue import find_variable

        schema = {
            "STATE State": {
                "key": "var_state",
                "group": "Geography",
                "child_count": 0,
                "levels": [],
            },
            "GCCSA Greater Capital City Statistical Areas": {
                "key": "var_gccsa",
                "group": "Geography",
                "child_count": 10,
                "levels": [],
            },
        }
        result = find_variable(schema, "STATE State")
        assert result is not None
        assert result["key"] == "var_state"

    def test_empty_schema(self):
        """Returns None for an empty schema."""
        from tablebuilder.http_catalogue import find_variable

        result = find_variable({}, "anything")
        assert result is None
