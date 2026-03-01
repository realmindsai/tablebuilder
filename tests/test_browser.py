# ABOUTME: Tests for Playwright browser session management.
# ABOUTME: Unit tests for session lifecycle; integration tests for real login.

import pytest

from tablebuilder.browser import TableBuilderSession, LoginError
from tablebuilder.config import Config


TABLEBUILDER_URL = "https://tablebuilder.abs.gov.au/webapi/jsf/login.xhtml"


class TestTableBuilderSession:
    def test_session_is_context_manager(self):
        """TableBuilderSession can be used as a context manager."""
        config = Config(user_id="fake", password="fake")
        session = TableBuilderSession(config, headless=True)
        assert hasattr(session, "__enter__")
        assert hasattr(session, "__exit__")

    def test_session_stores_config(self):
        """Session stores the config and headless flag."""
        config = Config(user_id="12345", password="pw")
        session = TableBuilderSession(config, headless=False)
        assert session.config == config
        assert session.headless is False

    def test_session_default_headless(self):
        """Session defaults to headless=True."""
        config = Config(user_id="12345", password="pw")
        session = TableBuilderSession(config)
        assert session.headless is True


@pytest.mark.integration
class TestTableBuilderSessionIntegration:
    def test_login_with_bad_credentials_raises(self):
        """Login with invalid credentials raises LoginError."""
        config = Config(user_id="00000", password="wrongpassword")
        session = TableBuilderSession(config, headless=True)
        with pytest.raises(LoginError):
            with session as page:
                pass  # login happens in __enter__

    def test_login_reaches_home_page(self, abs_config):
        """Login with valid credentials reaches the datasets page."""
        session = TableBuilderSession(abs_config, headless=True)
        with session as page:
            # After login we should see the datasets panel
            assert page.url != TABLEBUILDER_URL
            # The page should have dataset-related content
            page.wait_for_selector("text=Datasets", timeout=15000)
