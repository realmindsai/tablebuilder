# ABOUTME: Pure-HTTP session client for ABS TableBuilder using requests.
# ABOUTME: Handles login, ViewState tracking, JSF form posts, and RichFaces AJAX calls.

from __future__ import annotations

import re
import time

import requests

from tablebuilder.browser import LoginError
from tablebuilder.config import Config
from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.http_session")

BASE_URL = "https://tablebuilder.abs.gov.au/webapi"

# Regex patterns for extracting JSF ViewState tokens
_VIEWSTATE_HTML_RE = re.compile(
    r'<input[^>]*name="javax\.faces\.ViewState"[^>]*value="([^"]*)"',
    re.DOTALL,
)
_VIEWSTATE_XML_RE = re.compile(
    r'<update\s+id="javax\.faces\.ViewState">\s*<!\[CDATA\[(.+?)\]\]>',
    re.DOTALL,
)


def extract_viewstate(text: str) -> str | None:
    """Extract the JSF ViewState token from HTML or XML partial-response text.

    Checks for:
    - HTML hidden input: <input ... name="javax.faces.ViewState" ... value="TOKEN" />
    - XML partial update: <update id="javax.faces.ViewState"><![CDATA[TOKEN]]></update>

    Returns the token string, or None if not found.
    """
    match = _VIEWSTATE_HTML_RE.search(text)
    if match:
        return match.group(1)

    match = _VIEWSTATE_XML_RE.search(text)
    if match:
        return match.group(1)

    return None


class TableBuilderHTTPSession:
    """Pure-HTTP session for ABS TableBuilder.

    Drop-in concept replacement for the Playwright-based TableBuilderSession.
    Uses requests to call REST API and JSF endpoints directly, avoiding the
    overhead of full browser automation.
    """

    def __init__(self, config: Config, knowledge=None):
        self.config = config
        self.knowledge = knowledge
        self._session = requests.Session()
        self._viewstate: str | None = None
        self._catalogue_html: str = ""

    @property
    def viewstate(self) -> str | None:
        """The current JSF ViewState token."""
        return self._viewstate

    @property
    def catalogue_html(self) -> str:
        """The HTML content of the data catalogue page after login."""
        return self._catalogue_html

    def login(self) -> None:
        """Authenticate with ABS TableBuilder via HTTP form submission.

        Performs:
        1. GET the login page to obtain the initial ViewState
        2. POST the login form with credentials
        3. Handle terms page redirect if needed
        4. Verify landing on dataCatalogueExplorer.xhtml

        Raises LoginError if authentication fails.
        """
        login_start = time.time()
        logger.info("HTTP login started for user %s", self.config.user_id)

        # GET login page to get initial ViewState
        login_url = f"{BASE_URL}/jsf/login.xhtml"
        resp = self._session.get(login_url)
        initial_viewstate = extract_viewstate(resp.text)

        if initial_viewstate is None:
            raise LoginError("Cannot extract ViewState from login page.")

        # POST login form
        login_data = {
            "loginForm:username2": self.config.user_id,
            "loginForm:password2": self.config.password,
            "loginForm_SUBMIT": "1",
            "javax.faces.ViewState": initial_viewstate,
            "r": "",
            "loginForm:_idcl": "loginForm:login2",
        }
        login_headers = {
            "Referer": login_url,
            "Origin": "https://tablebuilder.abs.gov.au",
        }

        resp = self._session.post(
            login_url,
            data=login_data,
            headers=login_headers,
            allow_redirects=True,
        )

        # Check if we're still on the login page (bad credentials)
        if "login.xhtml" in resp.url:
            raise LoginError(
                "Login failed — still on login page. Check your User ID and password."
            )

        # Handle terms page redirect
        if "terms.xhtml" in resp.url:
            logger.info("Terms page encountered, accepting conditions")
            terms_viewstate = extract_viewstate(resp.text)
            terms_data = {
                "termsForm:termsButton": "Accept",
                "javax.faces.ViewState": terms_viewstate or "",
            }
            resp = self._session.post(
                resp.url,
                data=terms_data,
                headers={"Referer": resp.url},
                allow_redirects=True,
            )

        # Verify we reached the data catalogue
        if "dataCatalogueExplorer.xhtml" not in resp.url:
            raise LoginError(
                f"Login did not reach data catalogue. Current URL: {resp.url}"
            )

        # Store ViewState and catalogue HTML
        self._viewstate = extract_viewstate(resp.text)
        self._catalogue_html = resp.text

        login_duration = time.time() - login_start
        logger.info("HTTP login succeeded in %.1f seconds", login_duration)

        if self.knowledge is not None:
            self.knowledge.record_timing("login", login_duration)

    def jsf_post(self, url: str, data: dict) -> requests.Response:
        """POST a JSF form, injecting the current ViewState.

        Injects javax.faces.ViewState into data, sends the POST with
        allow_redirects=True, then extracts and updates the ViewState
        from the response.

        Returns the response object.
        """
        data["javax.faces.ViewState"] = self._viewstate
        resp = self._session.post(url, data=data, allow_redirects=True)

        new_vs = extract_viewstate(resp.text)
        if new_vs:
            self._viewstate = new_vs

        return resp

    def richfaces_ajax(
        self,
        url: str,
        form_id: str,
        component_id: str,
        extra_params: dict | None = None,
    ) -> requests.Response:
        """Send a RichFaces AJAX POST request.

        Builds the standard RichFaces AJAX payload with form submit flag,
        ViewState, and component ID. Sends with partial/ajax headers.

        Returns the response object.
        """
        data = {
            f"{form_id}_SUBMIT": "1",
            "javax.faces.ViewState": self._viewstate,
            "org.richfaces.ajax.component": component_id,
        }

        if extra_params:
            data.update(extra_params)

        headers = {
            "Faces-Request": "partial/ajax",
            "X-Requested-With": "XMLHttpRequest",
        }

        resp = self._session.post(url, data=data, headers=headers)

        new_vs = extract_viewstate(resp.text)
        if new_vs:
            self._viewstate = new_vs

        return resp

    def rest_get(self, path: str) -> dict:
        """GET a REST endpoint and return parsed JSON.

        Args:
            path: URL path relative to BASE_URL (e.g. "/rest/some/endpoint").

        Returns:
            Parsed JSON response as a dict.
        """
        url = f"{BASE_URL}{path}"
        resp = self._session.get(url)
        return resp.json()

    def rest_post(self, path: str, payload: dict) -> dict | None:
        """POST JSON to a REST endpoint and return parsed JSON or None.

        Args:
            path: URL path relative to BASE_URL.
            payload: JSON-serializable dict to send as request body.

        Returns:
            Parsed JSON response as a dict, or None if no JSON body.
        """
        url = f"{BASE_URL}{path}"
        resp = self._session.post(url, json=payload)
        try:
            return resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            return None

    def __enter__(self) -> TableBuilderHTTPSession:
        """Log in and return this session instance."""
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Close the underlying requests session."""
        self._session.close()
        return False
