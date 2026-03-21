# ABOUTME: Tests for HTTP table operations — category selection, axis assignment, and data retrieval/download.
# ABOUTME: Covers build_node_state, build_expand_payload, get_category_keys, select_all_categories, add_to_axis, retrieve_data, select_csv_format, download_table.

import io
import os
import tempfile
import zipfile
from unittest.mock import MagicMock, call, patch

import pytest

from tablebuilder.http_session import BASE_URL


# ── Sample data ──────────────────────────────────────────────────────


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
                                    },
                                    "children": [],
                                },
                                {
                                    "key": "cat_female",
                                    "data": {
                                        "type": "CATEGORY",
                                        "name": "Female",
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


# Schema dict as returned by get_schema()
SAMPLE_SCHEMA = {
    "SEXP Sex": {
        "key": "var_sexp",
        "group": "Variables/Demographics",
        "child_count": 2,
        "levels": ["Male", "Female"],
    },
    "AGEP Age": {
        "key": "var_agep",
        "group": "Variables/Demographics",
        "child_count": 1,
        "levels": ["0-14"],
    },
    "STATE State": {
        "key": "var_state",
        "group": "Variables/Geography",
        "child_count": 0,
        "levels": [],
    },
}


# Response from expanding a variable node (returned by rest_post)
EXPAND_RESPONSE = {
    "nodeList": [
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
                    "key": "MQ",
                    "data": {"type": "CATEGORY", "name": "Male"},
                    "children": [],
                },
                {
                    "key": "Mg",
                    "data": {"type": "CATEGORY", "name": "Female"},
                    "children": [],
                },
            ],
        }
    ]
}


TABLEVIEW_URL = f"{BASE_URL}/jsf/tableView/tableView.xhtml"


# ── build_node_state tests ───────────────────────────────────────────


class TestBuildNodeState:
    """Tests for build_node_state() which builds checkbox selection payloads."""

    def test_single_category(self):
        """Builds nodeState for selecting a single category."""
        from tablebuilder.http_table import build_node_state

        result = build_node_state("group_key", "field_key", ["cat_1"])
        expected = {
            "nodeState": {
                "set": {
                    "group_key": {
                        "children": {
                            "field_key": {
                                "children": {
                                    "cat_1": {"value": True}
                                }
                            }
                        }
                    }
                }
            }
        }
        assert result == expected

    def test_multiple_categories(self):
        """Builds nodeState for selecting multiple categories."""
        from tablebuilder.http_table import build_node_state

        result = build_node_state("grp", "fld", ["MQ", "Mg", "Mw"])
        children = result["nodeState"]["set"]["grp"]["children"]["fld"]["children"]
        assert children == {
            "MQ": {"value": True},
            "Mg": {"value": True},
            "Mw": {"value": True},
        }

    def test_preserves_key_values(self):
        """Keys are passed through exactly as provided."""
        from tablebuilder.http_table import build_node_state

        result = build_node_state("group_demographics", "var_sexp", ["MQ"])
        top_level = result["nodeState"]["set"]
        assert "group_demographics" in top_level
        assert "var_sexp" in top_level["group_demographics"]["children"]


# ── build_expand_payload tests ───────────────────────────────────────


class TestBuildExpandPayload:
    """Tests for build_expand_payload() which builds variable expansion payloads."""

    def test_structure(self):
        """Builds correct expandedNodes and returnNode structure."""
        from tablebuilder.http_table import build_expand_payload

        result = build_expand_payload("group_key", "field_key")
        expected = {
            "expandedNodes": {
                "set": {
                    "group_key": {
                        "children": {
                            "field_key": {"value": True}
                        }
                    }
                }
            },
            "returnNode": {
                "node": ["group_key", "field_key"],
                "data": True,
                "state": True,
                "expanded": True,
            },
        }
        assert result == expected

    def test_return_node_path(self):
        """returnNode.node contains the group and field keys in order."""
        from tablebuilder.http_table import build_expand_payload

        result = build_expand_payload("grp_abc", "var_xyz")
        assert result["returnNode"]["node"] == ["grp_abc", "var_xyz"]

    def test_expanded_nodes_set(self):
        """expandedNodes.set nests field value under group key."""
        from tablebuilder.http_table import build_expand_payload

        result = build_expand_payload("g1", "f1")
        assert result["expandedNodes"]["set"]["g1"]["children"]["f1"] == {"value": True}


# ── get_category_keys tests ──────────────────────────────────────────


class TestGetCategoryKeys:
    """Tests for get_category_keys() which discovers category children by expanding a variable."""

    def test_returns_group_field_and_category_keys(self):
        """Returns the group key, field key, and list of category keys."""
        from tablebuilder.http_table import get_category_keys

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE
        session.rest_post.return_value = EXPAND_RESPONSE

        var_info = SAMPLE_SCHEMA["SEXP Sex"]
        group_key, field_key, cat_keys = get_category_keys(session, SAMPLE_SCHEMA, var_info)

        assert group_key == "group_demographics"
        assert field_key == "var_sexp"
        assert cat_keys == ["MQ", "Mg"]

    def test_calls_rest_get_for_schema_tree(self):
        """Fetches the schema tree via rest_get to find the group key."""
        from tablebuilder.http_table import get_category_keys

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE
        session.rest_post.return_value = EXPAND_RESPONSE

        var_info = SAMPLE_SCHEMA["SEXP Sex"]
        get_category_keys(session, SAMPLE_SCHEMA, var_info)

        session.rest_get.assert_called_once_with("/rest/catalogue/tableSchema/tree")

    def test_calls_rest_post_with_expand_payload(self):
        """Sends the expand payload to rest_post to get category children."""
        from tablebuilder.http_table import build_expand_payload, get_category_keys

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE
        session.rest_post.return_value = EXPAND_RESPONSE

        var_info = SAMPLE_SCHEMA["SEXP Sex"]
        get_category_keys(session, SAMPLE_SCHEMA, var_info)

        expected_payload = build_expand_payload("group_demographics", "var_sexp")
        session.rest_post.assert_called_once_with(
            "/rest/catalogue/tableSchema/tree",
            expected_payload,
        )

    def test_raises_on_missing_group(self):
        """Raises ValueError when the variable's group key cannot be found in the tree."""
        from tablebuilder.http_table import get_category_keys

        session = MagicMock()
        # Return a tree that doesn't contain the variable
        session.rest_get.return_value = {"nodeList": []}

        var_info = {"key": "nonexistent_var", "group": "Variables/Missing"}
        with pytest.raises(ValueError, match="group key"):
            get_category_keys(session, SAMPLE_SCHEMA, var_info)

    def test_handles_variable_in_different_group(self):
        """Finds the correct group key for a variable in the Geography group."""
        from tablebuilder.http_table import get_category_keys

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE
        # Expand response with geography categories
        geo_expand = {
            "nodeList": [
                {
                    "key": "var_state",
                    "data": {"type": "VARIABLE", "name": "STATE State"},
                    "children": [
                        {
                            "key": "NSW",
                            "data": {"type": "CATEGORY", "name": "New South Wales"},
                            "children": [],
                        },
                        {
                            "key": "VIC",
                            "data": {"type": "CATEGORY", "name": "Victoria"},
                            "children": [],
                        },
                    ],
                }
            ]
        }
        session.rest_post.return_value = geo_expand

        var_info = SAMPLE_SCHEMA["STATE State"]
        group_key, field_key, cat_keys = get_category_keys(session, SAMPLE_SCHEMA, var_info)

        assert group_key == "group_geography"
        assert field_key == "var_state"
        assert cat_keys == ["NSW", "VIC"]


# ── select_all_categories tests ──────────────────────────────────────


class TestSelectAllCategories:
    """Tests for select_all_categories() which checks all category checkboxes."""

    def test_posts_node_state_for_each_category(self):
        """Sends a REST POST with nodeState for each discovered category."""
        from tablebuilder.http_table import select_all_categories

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE
        session.rest_post.return_value = EXPAND_RESPONSE
        session.richfaces_ajax.return_value = MagicMock()

        var_info = SAMPLE_SCHEMA["SEXP Sex"]
        select_all_categories(session, SAMPLE_SCHEMA, var_info)

        # First call is the expand, then one per category
        rest_post_calls = session.rest_post.call_args_list
        # Call 0: expand payload
        # Call 1: nodeState for MQ
        # Call 2: nodeState for Mg
        assert len(rest_post_calls) == 3

    def test_fires_richfaces_ajax_after_each_category(self):
        """Fires a RichFaces AJAX call after each category checkbox selection."""
        from tablebuilder.http_table import select_all_categories

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE
        session.rest_post.return_value = EXPAND_RESPONSE
        session.richfaces_ajax.return_value = MagicMock()

        var_info = SAMPLE_SCHEMA["SEXP Sex"]
        select_all_categories(session, SAMPLE_SCHEMA, var_info)

        # One AJAX call per category (MQ and Mg)
        assert session.richfaces_ajax.call_count == 2

    def test_richfaces_ajax_uses_correct_form_and_component(self):
        """RichFaces AJAX calls use treeForm and treeForm:j_id_6m."""
        from tablebuilder.http_table import select_all_categories

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE
        session.rest_post.return_value = EXPAND_RESPONSE
        session.richfaces_ajax.return_value = MagicMock()

        var_info = SAMPLE_SCHEMA["SEXP Sex"]
        select_all_categories(session, SAMPLE_SCHEMA, var_info)

        for ajax_call in session.richfaces_ajax.call_args_list:
            assert ajax_call[0][0] == TABLEVIEW_URL
            assert ajax_call[1]["form_id"] == "treeForm" or ajax_call[0][1] == "treeForm"
            assert ajax_call[1]["component_id"] == "treeForm:j_id_6m" or ajax_call[0][2] == "treeForm:j_id_6m"

    def test_node_state_payloads_are_correct(self):
        """Each nodeState POST contains the correct group, field, and single category key."""
        from tablebuilder.http_table import build_node_state, select_all_categories

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE
        session.rest_post.return_value = EXPAND_RESPONSE
        session.richfaces_ajax.return_value = MagicMock()

        var_info = SAMPLE_SCHEMA["SEXP Sex"]
        select_all_categories(session, SAMPLE_SCHEMA, var_info)

        rest_post_calls = session.rest_post.call_args_list
        # Call 1: nodeState for MQ
        expected_mq = build_node_state("group_demographics", "var_sexp", ["MQ"])
        assert rest_post_calls[1] == call(
            "/rest/catalogue/tableSchema/tree",
            expected_mq,
        )
        # Call 2: nodeState for Mg
        expected_mg = build_node_state("group_demographics", "var_sexp", ["Mg"])
        assert rest_post_calls[2] == call(
            "/rest/catalogue/tableSchema/tree",
            expected_mg,
        )

    def test_call_order_alternates_rest_and_ajax(self):
        """REST POST and AJAX calls alternate: rest, ajax, rest, ajax..."""
        from tablebuilder.http_table import select_all_categories

        session = MagicMock()
        session.rest_get.return_value = SAMPLE_SCHEMA_TREE
        session.rest_post.return_value = EXPAND_RESPONSE
        session.richfaces_ajax.return_value = MagicMock()

        call_order = []
        original_rest_post = session.rest_post
        original_richfaces_ajax = session.richfaces_ajax

        def track_rest_post(*args, **kwargs):
            call_order.append("rest_post")
            return EXPAND_RESPONSE

        def track_richfaces_ajax(*args, **kwargs):
            call_order.append("richfaces_ajax")
            return MagicMock()

        session.rest_post.side_effect = track_rest_post
        session.richfaces_ajax.side_effect = track_richfaces_ajax

        var_info = SAMPLE_SCHEMA["SEXP Sex"]
        select_all_categories(session, SAMPLE_SCHEMA, var_info)

        # expand, then (nodeState + ajax) per category
        assert call_order == [
            "rest_post",       # expand
            "rest_post",       # nodeState MQ
            "richfaces_ajax",  # AJAX after MQ
            "rest_post",       # nodeState Mg
            "richfaces_ajax",  # AJAX after Mg
        ]


# ── add_to_axis tests ────────────────────────────────────────────────


class TestAddToAxis:
    """Tests for add_to_axis() which assigns selected variables to a table axis."""

    def test_add_to_row(self):
        """Posts buttonForm with addR=Row for row axis."""
        from tablebuilder.http_table import add_to_axis

        session = MagicMock()
        session.jsf_post.return_value = MagicMock()

        add_to_axis(session, "row")

        session.jsf_post.assert_called_once_with(
            TABLEVIEW_URL,
            {
                "buttonForm_SUBMIT": "1",
                "buttonForm:addR": "Row",
            },
        )

    def test_add_to_col(self):
        """Posts buttonForm with addC=Column for column axis."""
        from tablebuilder.http_table import add_to_axis

        session = MagicMock()
        session.jsf_post.return_value = MagicMock()

        add_to_axis(session, "col")

        session.jsf_post.assert_called_once_with(
            TABLEVIEW_URL,
            {
                "buttonForm_SUBMIT": "1",
                "buttonForm:addC": "Column",
            },
        )

    def test_add_to_wafer(self):
        """Posts buttonForm with addL=Wafer for wafer axis."""
        from tablebuilder.http_table import add_to_axis

        session = MagicMock()
        session.jsf_post.return_value = MagicMock()

        add_to_axis(session, "wafer")

        session.jsf_post.assert_called_once_with(
            TABLEVIEW_URL,
            {
                "buttonForm_SUBMIT": "1",
                "buttonForm:addL": "Wafer",
            },
        )

    def test_raises_on_invalid_axis(self):
        """Raises ValueError for an unrecognized axis name."""
        from tablebuilder.http_table import add_to_axis

        session = MagicMock()

        with pytest.raises(ValueError, match="axis"):
            add_to_axis(session, "diagonal")

    def test_posts_to_tableview_url(self):
        """All axis operations POST to the tableView URL."""
        from tablebuilder.http_table import add_to_axis

        session = MagicMock()
        session.jsf_post.return_value = MagicMock()

        for axis in ("row", "col", "wafer"):
            session.reset_mock()
            add_to_axis(session, axis)
            url_arg = session.jsf_post.call_args[0][0]
            assert url_arg == TABLEVIEW_URL


# ── retrieve_data tests ─────────────────────────────────────────────


class TestRetrieveData:
    """Tests for retrieve_data() which fires the retrieve/cross-tabulation AJAX call."""

    def test_calls_richfaces_ajax_with_pageform(self):
        """Fires richfaces_ajax on pageForm with component pageForm:retB."""
        from tablebuilder.http_table import retrieve_data

        session = MagicMock()
        session.richfaces_ajax.return_value = MagicMock()

        retrieve_data(session)

        session.richfaces_ajax.assert_called_once()
        call_kwargs = session.richfaces_ajax.call_args
        assert call_kwargs[0][0] == TABLEVIEW_URL
        assert call_kwargs[1]["form_id"] == "pageForm"
        assert call_kwargs[1]["component_id"] == "pageForm:retB"

    def test_includes_dnd_fields(self):
        """Extra params include empty drag-and-drop fields."""
        from tablebuilder.http_table import retrieve_data

        session = MagicMock()
        session.richfaces_ajax.return_value = MagicMock()

        retrieve_data(session)

        extra = session.richfaces_ajax.call_args[1]["extra_params"]
        assert extra["dndItemType"] == ""
        assert extra["dndItemArg"] == ""
        assert extra["dndTargetType"] == ""
        assert extra["dndTargetArg"] == ""

    def test_includes_partial_event_click(self):
        """Extra params include javax.faces.partial.event=click."""
        from tablebuilder.http_table import retrieve_data

        session = MagicMock()
        session.richfaces_ajax.return_value = MagicMock()

        retrieve_data(session)

        extra = session.richfaces_ajax.call_args[1]["extra_params"]
        assert extra["javax.faces.partial.event"] == "click"


# ── select_csv_format tests ─────────────────────────────────────────


class TestSelectCsvFormat:
    """Tests for select_csv_format() which selects CSV from the download format dropdown."""

    def test_calls_jsf_post_with_csv_selection(self):
        """Posts format selection with downloadType=CSV."""
        from tablebuilder.http_table import select_csv_format

        session = MagicMock()
        session.jsf_post.return_value = MagicMock()

        select_csv_format(session)

        session.jsf_post.assert_called_once()
        url_arg = session.jsf_post.call_args[0][0]
        data_arg = session.jsf_post.call_args[0][1]

        assert url_arg == TABLEVIEW_URL
        assert data_arg["downloadControl:downloadType"] == "CSV"
        assert data_arg["downloadControl_SUBMIT"] == "1"

    def test_includes_behavior_event_fields(self):
        """Posts include JSF behavior event and source fields for the dropdown change."""
        from tablebuilder.http_table import select_csv_format

        session = MagicMock()
        session.jsf_post.return_value = MagicMock()

        select_csv_format(session)

        data_arg = session.jsf_post.call_args[0][1]
        assert data_arg["javax.faces.behavior.event"] == "valueChange"
        assert data_arg["javax.faces.source"] == "downloadControl:downloadType"
        assert data_arg["javax.faces.partial.ajax"] == "true"


# ── download_table tests ────────────────────────────────────────────


def _make_zip_bytes(csv_content: str, filename: str = "table.csv") -> bytes:
    """Helper to create an in-memory ZIP containing a single CSV file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, csv_content)
    return buf.getvalue()


class TestDownloadTable:
    """Tests for download_table() which downloads the result CSV via direct or queue flow."""

    def test_direct_download_saves_csv_from_zip(self):
        """Direct download: saves extracted CSV when response is a ZIP."""
        from tablebuilder.http_table import download_table

        csv_data = "col1,col2\n1,2\n3,4\n"
        zip_bytes = _make_zip_bytes(csv_data)

        # Mock the direct download response as octet-stream
        direct_response = MagicMock()
        direct_response.headers = {"Content-Type": "application/octet-stream"}
        direct_response.content = zip_bytes

        session = MagicMock()
        session.jsf_post.return_value = direct_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "out.csv")
            download_table(session, output_path)

            assert os.path.exists(output_path)
            with open(output_path) as f:
                assert f.read() == csv_data

    def test_direct_download_saves_raw_csv(self):
        """Direct download: saves raw CSV when response is not a ZIP."""
        from tablebuilder.http_table import download_table

        csv_data = b"col1,col2\n1,2\n3,4\n"

        direct_response = MagicMock()
        direct_response.headers = {"Content-Type": "application/octet-stream"}
        direct_response.content = csv_data

        session = MagicMock()
        session.jsf_post.return_value = direct_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "out.csv")
            download_table(session, output_path)

            assert os.path.exists(output_path)
            with open(output_path) as f:
                assert f.read() == csv_data.decode()

    def test_queue_flow_when_direct_download_returns_html(self):
        """Falls back to queue flow when direct download returns HTML (not octet-stream)."""
        from tablebuilder.http_table import download_table

        csv_data = "col1,col2\n1,2\n"
        zip_bytes = _make_zip_bytes(csv_data)

        # Direct download returns HTML (no octet-stream)
        html_response = MagicMock()
        html_response.headers = {"Content-Type": "text/html; charset=UTF-8"}
        html_response.content = b"<html>table view page</html>"

        session = MagicMock()
        session.jsf_post.return_value = html_response

        # Queue flow: GET openTable.xhtml
        open_table_response = MagicMock()
        open_table_response.text = "<html>saved tables</html>"

        # Queue flow: GET manageTables/tree returns list of jobs
        manage_tables_response = [
            {"jobId": "job_older", "label": "old table"},
            {"jobId": "job_latest", "label": "latest table"},
        ]

        # Queue flow: GET downloadTable returns ZIP
        download_response = MagicMock()
        download_response.content = zip_bytes

        # Wire up the session mocks
        session._session = MagicMock()

        def mock_get(url, **kwargs):
            if "openTable.xhtml" in url:
                return open_table_response
            elif "downloadTable" in url:
                return download_response
            return MagicMock()

        session._session.get.side_effect = mock_get
        session.rest_get.return_value = manage_tables_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "out.csv")
            download_table(session, output_path)

            assert os.path.exists(output_path)
            with open(output_path) as f:
                assert f.read() == csv_data

    def test_queue_flow_uses_latest_job_id(self):
        """Queue flow picks the last job ID from the manageTables/tree response."""
        from tablebuilder.http_table import download_table

        csv_data = "a,b\n1,2\n"
        zip_bytes = _make_zip_bytes(csv_data)

        # Direct download returns HTML
        html_response = MagicMock()
        html_response.headers = {"Content-Type": "text/html"}
        html_response.content = b"<html></html>"

        session = MagicMock()
        session.jsf_post.return_value = html_response

        manage_tables = [
            {"jobId": "first_job", "label": "Table 1"},
            {"jobId": "second_job", "label": "Table 2"},
        ]
        session.rest_get.return_value = manage_tables

        download_response = MagicMock()
        download_response.content = zip_bytes

        session._session = MagicMock()

        def mock_get(url, **kwargs):
            if "downloadTable" in url:
                assert "jobId=second_job" in url
                return download_response
            return MagicMock()

        session._session.get.side_effect = mock_get

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "out.csv")
            download_table(session, output_path)

    def test_download_posts_go_button(self):
        """Direct download tries submitting downloadControl:downloadGoButton."""
        from tablebuilder.http_table import download_table

        csv_data = b"x,y\n1,2\n"

        direct_response = MagicMock()
        direct_response.headers = {"Content-Type": "application/octet-stream"}
        direct_response.content = csv_data

        session = MagicMock()
        session.jsf_post.return_value = direct_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "out.csv")
            download_table(session, output_path)

        call_data = session.jsf_post.call_args[0][1]
        assert "downloadControl:downloadGoButton" in call_data
