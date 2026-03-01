# ABOUTME: Tests for credential loading from .env files and environment variables.
# ABOUTME: Validates precedence: CLI flags > env vars > .env file.

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tablebuilder.config import Config, load_config, ConfigError


class TestLoadConfig:
    def test_loads_from_env_file(self, tmp_path):
        """Reads credentials from a .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "TABLEBUILDER_USER_ID=12345\nTABLEBUILDER_PASSWORD=secret\n"
        )
        config = load_config(env_path=env_file)
        assert config.user_id == "12345"
        assert config.password == "secret"

    def test_falls_back_to_env_vars(self, tmp_path):
        """Uses environment variables when no .env file exists."""
        missing = tmp_path / "nonexistent" / ".env"
        with patch.dict(
            os.environ,
            {
                "TABLEBUILDER_USER_ID": "99999",
                "TABLEBUILDER_PASSWORD": "envpass",
            },
        ):
            config = load_config(env_path=missing)
            assert config.user_id == "99999"
            assert config.password == "envpass"

    def test_error_on_missing_user_id(self, tmp_path):
        """Raises ConfigError when user ID is not found anywhere."""
        env_file = tmp_path / ".env"
        env_file.write_text("TABLEBUILDER_PASSWORD=secret\n")
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError, match="TABLEBUILDER_USER_ID"):
                load_config(env_path=env_file)

    def test_error_on_missing_password(self, tmp_path):
        """Raises ConfigError when password is not found anywhere."""
        env_file = tmp_path / ".env"
        env_file.write_text("TABLEBUILDER_USER_ID=12345\n")
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError, match="TABLEBUILDER_PASSWORD"):
                load_config(env_path=env_file)

    def test_cli_overrides_take_precedence(self, tmp_path):
        """Explicit user_id/password args override .env and env vars."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "TABLEBUILDER_USER_ID=file_id\nTABLEBUILDER_PASSWORD=file_pw\n"
        )
        config = load_config(
            env_path=env_file, user_id="cli_id", password="cli_pw"
        )
        assert config.user_id == "cli_id"
        assert config.password == "cli_pw"

    def test_default_env_path(self):
        """Default .env path is ~/.tablebuilder/.env."""
        from tablebuilder.config import DEFAULT_ENV_PATH

        assert DEFAULT_ENV_PATH == Path.home() / ".tablebuilder" / ".env"
