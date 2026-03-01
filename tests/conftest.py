# ABOUTME: Shared pytest fixtures for tablebuilder tests.
# ABOUTME: Provides abs_config fixture for integration tests needing real credentials.

import pytest

from tablebuilder.config import Config, load_config, ConfigError
from tablebuilder.browser import TableBuilderSession


@pytest.fixture
def abs_config():
    """Load real ABS credentials for integration tests.

    Skips the test if no credentials are configured.
    """
    try:
        return load_config()
    except ConfigError:
        pytest.skip("No ABS credentials configured for integration tests")


@pytest.fixture
def abs_page(abs_config):
    """Provide a logged-in TableBuilder page for integration tests."""
    session = TableBuilderSession(abs_config, headless=True)
    with session as page:
        yield page
