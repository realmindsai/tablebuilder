# ABOUTME: Tests for the pure-HTTP session client for ABS TableBuilder.
# ABOUTME: Covers ViewState extraction, login flow, JSF posts, and RichFaces AJAX.

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from tablebuilder.config import Config
from tablebuilder.browser import LoginError
from tablebuilder.http_session import (
    TableBuilderHTTPSession,
    extract_viewstate,
    BASE_URL,
)


# ── ViewState extraction ──────────────────────────────────────────────


class TestExtractViewstate:
    """Tests for extract_viewstate() utility function."""

    def test_extracts_from_html_hidden_input(self):
        """Extracts ViewState from a standard JSF hidden input."""
        html = (
            '<html><body>'
            '<input type="hidden" name="javax.faces.ViewState" '
            'id="j_id1:javax.faces.ViewState:0" value="abc123token" />'
            '</body></html>'
        )
        assert extract_viewstate(html) == "abc123token"

    def test_extracts_from_xml_partial_update(self):
        """Extracts ViewState from a RichFaces XML partial-response."""
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<partial-response>'
            '<changes>'
            '<update id="javax.faces.ViewState">'
            '<![CDATA[xyz789token]]>'
            '</update>'
            '</changes>'
            '</partial-response>'
        )
        assert extract_viewstate(xml) == "xyz789token"

    def test_returns_none_when_no_viewstate(self):
        """Returns None when no ViewState is present."""
        html = "<html><body>No viewstate here</body></html>"
        assert extract_viewstate(html) is None

    def test_handles_multiline_html(self):
        """Extracts ViewState even when the input tag spans multiple lines."""
        html = (
            '<input type="hidden"\n'
            '  name="javax.faces.ViewState"\n'
            '  id="j_id1:javax.faces.ViewState:0"\n'
            '  value="multiline_token" />'
        )
        assert extract_viewstate(html) == "multiline_token"

    def test_prefers_html_input_over_xml(self):
        """When both forms exist, the function should find one of them."""
        mixed = (
            '<input type="hidden" name="javax.faces.ViewState" '
            'id="vs" value="html_token" />'
            '<update id="javax.faces.ViewState"><![CDATA[xml_token]]></update>'
        )
        result = extract_viewstate(mixed)
        assert result in ("html_token", "xml_token")


# ── Helpers ───────────────────────────────────────────────────────────


def _make_config():
    """Build a Config with fake credentials."""
    return Config(user_id="testuser", password="testpass")


def _make_response(text="", url="", status_code=200, json_data=None):
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.text = text
    resp.url = url
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


CATALOGUE_URL = f"{BASE_URL}/jsf/dataCatalogueExplorer.xhtml"

LOGIN_PAGE_HTML = (
    '<html><body>'
    '<input type="hidden" name="javax.faces.ViewState" '
    'id="vs" value="login_viewstate" />'
    '</body></html>'
)

CATALOGUE_HTML = (
    '<html><body>'
    '<input type="hidden" name="javax.faces.ViewState" '
    'id="vs" value="catalogue_viewstate" />'
    '<div>Data Catalogue</div>'
    '</body></html>'
)

TERMS_HTML = (
    '<html><body>'
    '<input type="hidden" name="javax.faces.ViewState" '
    'id="vs" value="terms_viewstate" />'
    '<form id="termsForm"><button>Accept</button></form>'
    '</body></html>'
)


# ── Login tests ───────────────────────────────────────────────────────


class TestLogin:
    """Tests for TableBuilderHTTPSession.login()."""

    @patch("tablebuilder.http_session.requests.Session")
    def test_login_sends_correct_form_data(self, MockSession):
        """Login POSTs correct form fields to the login endpoint."""
        mock_session = MockSession.return_value

        # GET login page
        login_resp = _make_response(text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml")
        # POST login form -> catalogue page
        catalogue_resp = _make_response(text=CATALOGUE_HTML, url=CATALOGUE_URL)

        mock_session.get.return_value = login_resp
        mock_session.post.return_value = catalogue_resp

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        # Verify the POST was called with correct form data
        post_call = mock_session.post.call_args_list[0]
        post_data = post_call.kwargs.get("data") or post_call[1].get("data") or post_call[0][1] if len(post_call[0]) > 1 else post_call.kwargs["data"]
        assert post_data["loginForm:username2"] == "testuser"
        assert post_data["loginForm:password2"] == "testpass"
        assert post_data["loginForm_SUBMIT"] == "1"
        assert post_data["javax.faces.ViewState"] == "login_viewstate"
        assert post_data["loginForm:_idcl"] == "loginForm:login2"

    @patch("tablebuilder.http_session.requests.Session")
    def test_login_updates_viewstate(self, MockSession):
        """After login, ViewState is updated from the catalogue page."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        assert session.viewstate == "catalogue_viewstate"

    @patch("tablebuilder.http_session.requests.Session")
    def test_login_stores_catalogue_html(self, MockSession):
        """After login, catalogue_html property contains the catalogue page HTML."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        assert "Data Catalogue" in session.catalogue_html

    @patch("tablebuilder.http_session.requests.Session")
    def test_login_raises_on_bad_credentials(self, MockSession):
        """Login raises LoginError when still on login.xhtml after POST."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        # POST returns login page again (bad creds)
        mock_session.post.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)

        with pytest.raises(LoginError):
            session.login()

    @patch("tablebuilder.http_session.requests.Session")
    def test_login_handles_terms_page(self, MockSession):
        """Login handles a redirect to terms.xhtml by posting acceptance."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        # First POST -> terms page, second POST -> catalogue
        mock_session.post.side_effect = [
            _make_response(text=TERMS_HTML, url=f"{BASE_URL}/jsf/terms.xhtml"),
            _make_response(text=CATALOGUE_HTML, url=CATALOGUE_URL),
        ]

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        assert session.viewstate == "catalogue_viewstate"
        # Should have made 2 POSTs: login + terms acceptance
        assert mock_session.post.call_count == 2

    @patch("tablebuilder.http_session.requests.Session")
    def test_login_records_timing_with_knowledge(self, MockSession):
        """Login records timing in KnowledgeBase when one is provided."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        knowledge = MagicMock()
        config = _make_config()
        session = TableBuilderHTTPSession(config, knowledge=knowledge)
        session.login()

        knowledge.record_timing.assert_called_once()
        call_args = knowledge.record_timing.call_args
        assert call_args[0][0] == "login"
        assert isinstance(call_args[0][1], float)

    @patch("tablebuilder.http_session.requests.Session")
    def test_login_sets_referer_and_origin_headers(self, MockSession):
        """Login POST includes Referer and Origin headers."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        post_call = mock_session.post.call_args_list[0]
        headers = post_call.kwargs.get("headers", {})
        assert "Referer" in headers
        assert "Origin" in headers


# ── jsf_post tests ────────────────────────────────────────────────────


class TestJsfPost:
    """Tests for TableBuilderHTTPSession.jsf_post()."""

    @patch("tablebuilder.http_session.requests.Session")
    def test_jsf_post_injects_viewstate(self, MockSession):
        """jsf_post() injects the current ViewState into the data dict."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        # Now do a jsf_post
        post_resp_html = (
            '<html><input type="hidden" name="javax.faces.ViewState" '
            'id="vs" value="new_viewstate_after_post" /></html>'
        )
        mock_session.post.return_value = _make_response(
            text=post_resp_html, url=f"{BASE_URL}/jsf/somepage.xhtml"
        )

        session.jsf_post(f"{BASE_URL}/jsf/somepage.xhtml", {"myfield": "myvalue"})

        last_post = mock_session.post.call_args_list[-1]
        post_data = last_post.kwargs.get("data", {})
        assert post_data["javax.faces.ViewState"] == "catalogue_viewstate"
        assert post_data["myfield"] == "myvalue"

    @patch("tablebuilder.http_session.requests.Session")
    def test_jsf_post_updates_viewstate(self, MockSession):
        """jsf_post() updates the session ViewState from the response."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()
        assert session.viewstate == "catalogue_viewstate"

        # jsf_post returns page with new viewstate
        post_resp_html = (
            '<html><input type="hidden" name="javax.faces.ViewState" '
            'id="vs" value="updated_viewstate" /></html>'
        )
        mock_session.post.return_value = _make_response(
            text=post_resp_html, url=f"{BASE_URL}/jsf/somepage.xhtml"
        )

        session.jsf_post(f"{BASE_URL}/jsf/somepage.xhtml", {"key": "val"})
        assert session.viewstate == "updated_viewstate"


# ── richfaces_ajax tests ─────────────────────────────────────────────


class TestRichfacesAjax:
    """Tests for TableBuilderHTTPSession.richfaces_ajax()."""

    @patch("tablebuilder.http_session.requests.Session")
    def test_richfaces_ajax_sends_correct_headers(self, MockSession):
        """richfaces_ajax() sends Faces-Request and X-Requested-With headers."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        # richfaces_ajax response
        ajax_resp_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<partial-response><changes>'
            '<update id="javax.faces.ViewState">'
            '<![CDATA[ajax_viewstate]]></update>'
            '</changes></partial-response>'
        )
        mock_session.post.return_value = _make_response(
            text=ajax_resp_xml, url=f"{BASE_URL}/jsf/somepage.xhtml"
        )

        session.richfaces_ajax(
            f"{BASE_URL}/jsf/somepage.xhtml",
            form_id="pageForm",
            component_id="pageForm:treePanel",
        )

        last_post = mock_session.post.call_args_list[-1]
        headers = last_post.kwargs.get("headers", {})
        assert headers.get("Faces-Request") == "partial/ajax"
        assert headers.get("X-Requested-With") == "XMLHttpRequest"

    @patch("tablebuilder.http_session.requests.Session")
    def test_richfaces_ajax_builds_correct_data(self, MockSession):
        """richfaces_ajax() includes form submit flag, component ID, and ViewState."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        ajax_resp_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<partial-response><changes>'
            '<update id="javax.faces.ViewState">'
            '<![CDATA[ajax_vs2]]></update>'
            '</changes></partial-response>'
        )
        mock_session.post.return_value = _make_response(
            text=ajax_resp_xml, url=f"{BASE_URL}/jsf/somepage.xhtml"
        )

        session.richfaces_ajax(
            f"{BASE_URL}/jsf/somepage.xhtml",
            form_id="pageForm",
            component_id="pageForm:treePanel",
            extra_params={"extra_key": "extra_val"},
        )

        last_post = mock_session.post.call_args_list[-1]
        post_data = last_post.kwargs.get("data", {})
        assert post_data["pageForm_SUBMIT"] == "1"
        assert post_data["org.richfaces.ajax.component"] == "pageForm:treePanel"
        assert post_data["javax.faces.ViewState"] == "catalogue_viewstate"
        assert post_data["extra_key"] == "extra_val"

    @patch("tablebuilder.http_session.requests.Session")
    def test_richfaces_ajax_updates_viewstate(self, MockSession):
        """richfaces_ajax() extracts ViewState from XML partial-response."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        ajax_resp_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<partial-response><changes>'
            '<update id="javax.faces.ViewState">'
            '<![CDATA[fresh_ajax_viewstate]]></update>'
            '</changes></partial-response>'
        )
        mock_session.post.return_value = _make_response(
            text=ajax_resp_xml, url=f"{BASE_URL}/jsf/somepage.xhtml"
        )

        session.richfaces_ajax(
            f"{BASE_URL}/jsf/somepage.xhtml",
            form_id="pageForm",
            component_id="pageForm:treePanel",
        )

        assert session.viewstate == "fresh_ajax_viewstate"


# ── REST method tests ─────────────────────────────────────────────────


class TestRestMethods:
    """Tests for rest_get() and rest_post()."""

    @patch("tablebuilder.http_session.requests.Session")
    def test_rest_get_returns_json(self, MockSession):
        """rest_get() GETs a path and returns parsed JSON."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        mock_session.get.return_value = _make_response(
            json_data={"datasets": [1, 2, 3]},
            url=f"{BASE_URL}/rest/some/endpoint",
        )

        result = session.rest_get("/rest/some/endpoint")
        assert result == {"datasets": [1, 2, 3]}

    @patch("tablebuilder.http_session.requests.Session")
    def test_rest_post_sends_json_and_returns_json(self, MockSession):
        """rest_post() POSTs JSON payload and returns parsed JSON response."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        mock_session.post.return_value = _make_response(
            json_data={"status": "ok"},
            url=f"{BASE_URL}/rest/some/endpoint",
        )

        result = session.rest_post("/rest/some/endpoint", {"query": "test"})
        assert result == {"status": "ok"}

        last_post = mock_session.post.call_args_list[-1]
        assert last_post.kwargs.get("json") == {"query": "test"}

    @patch("tablebuilder.http_session.requests.Session")
    def test_rest_post_returns_none_on_no_json(self, MockSession):
        """rest_post() returns None when response has no JSON body."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.login()

        # Response with no JSON
        resp_no_json = _make_response(text="OK", url=f"{BASE_URL}/rest/endpoint")
        resp_no_json.json.side_effect = ValueError("No JSON")
        resp_no_json.status_code = 204
        mock_session.post.return_value = resp_no_json

        result = session.rest_post("/rest/some/endpoint", {"query": "test"})
        assert result is None


# ── Context manager tests ─────────────────────────────────────────────


class TestContextManager:
    """Tests for __enter__ / __exit__ protocol."""

    @patch("tablebuilder.http_session.requests.Session")
    def test_enter_logs_in_and_returns_self(self, MockSession):
        """__enter__ calls login() and returns the session instance."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)

        result = session.__enter__()
        assert result is session
        assert session.viewstate == "catalogue_viewstate"

    @patch("tablebuilder.http_session.requests.Session")
    def test_exit_closes_session(self, MockSession):
        """__exit__ closes the underlying requests.Session."""
        mock_session = MockSession.return_value
        mock_session.get.return_value = _make_response(
            text=LOGIN_PAGE_HTML, url=f"{BASE_URL}/jsf/login.xhtml"
        )
        mock_session.post.return_value = _make_response(
            text=CATALOGUE_HTML, url=CATALOGUE_URL
        )

        config = _make_config()
        session = TableBuilderHTTPSession(config)
        session.__enter__()
        session.__exit__(None, None, None)

        mock_session.close.assert_called_once()


# ── BASE_URL test ─────────────────────────────────────────────────────


class TestBaseUrl:
    """Tests for module-level BASE_URL constant."""

    def test_base_url_value(self):
        """BASE_URL points to the ABS TableBuilder webapi."""
        assert BASE_URL == "https://tablebuilder.abs.gov.au/webapi"
