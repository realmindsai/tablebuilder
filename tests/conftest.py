# ABOUTME: Shared pytest fixtures for tablebuilder tests.
# ABOUTME: Provides abs_config fixture for integration tests needing real credentials.

import pytest

from tablebuilder.config import Config, load_config, ConfigError
from tablebuilder.browser import TableBuilderSession
from tablebuilder.navigator import open_dataset
from tablebuilder.table_builder import build_table
from tablebuilder.models import TableRequest


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


@pytest.fixture
def abs_page_with_dataset(abs_page):
    """Provide a page with a Census dataset already open."""
    open_dataset(abs_page, "Census 2021")
    yield abs_page


@pytest.fixture
def abs_page_with_table(abs_page_with_dataset):
    """Provide a page with a simple table already built."""
    request = TableRequest(
        dataset="Census 2021 Basic",
        rows=["Sex"],
    )
    build_table(abs_page_with_dataset, request)
    yield abs_page_with_dataset
