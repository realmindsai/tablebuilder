# ABOUTME: Shared pytest fixtures for tablebuilder tests.
# ABOUTME: Provides abs_config fixture for integration tests needing real credentials.

import pytest

from tablebuilder.config import Config, load_config, ConfigError


@pytest.fixture
def abs_config():
    """Load real ABS credentials for integration tests.

    Skips the test if no credentials are configured.
    """
    try:
        return load_config()
    except ConfigError:
        pytest.skip("No ABS credentials configured for integration tests")
