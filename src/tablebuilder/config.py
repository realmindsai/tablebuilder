# ABOUTME: Credential loading for ABS TableBuilder authentication.
# ABOUTME: Reads from ~/.tablebuilder/.env, env vars, or CLI flags (in that precedence order).

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_ENV_PATH = Path.home() / ".tablebuilder" / ".env"


class ConfigError(Exception):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class Config:
    """ABS TableBuilder credentials."""

    user_id: str
    password: str


def load_config(
    env_path: Path = DEFAULT_ENV_PATH,
    user_id: str | None = None,
    password: str | None = None,
) -> Config:
    """Load credentials with precedence: explicit args > env vars > .env file."""
    file_values = dotenv_values(env_path) if env_path.exists() else {}

    resolved_user_id = (
        user_id
        or os.environ.get("TABLEBUILDER_USER_ID")
        or file_values.get("TABLEBUILDER_USER_ID")
    )
    resolved_password = (
        password
        or os.environ.get("TABLEBUILDER_PASSWORD")
        or file_values.get("TABLEBUILDER_PASSWORD")
    )

    if not resolved_user_id:
        raise ConfigError(
            "TABLEBUILDER_USER_ID not found. "
            "Set it in ~/.tablebuilder/.env, as an env var, or pass --user-id."
        )
    if not resolved_password:
        raise ConfigError(
            "TABLEBUILDER_PASSWORD not found. "
            "Set it in ~/.tablebuilder/.env, as an env var, or pass --password."
        )

    return Config(user_id=resolved_user_id, password=resolved_password)
