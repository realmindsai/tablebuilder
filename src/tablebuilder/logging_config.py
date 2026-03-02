# ABOUTME: Structured logging configuration for the tablebuilder CLI.
# ABOUTME: Provides setup_logging() to configure Python logging with file and console handlers.

import logging
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path.home() / ".tablebuilder" / "logs"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure the root logger with file and console handlers.

    Args:
        verbose: When True, console handler logs at DEBUG level.
                 When False, console handler logs at WARNING level.

    Returns:
        The configured root logger.
    """
    logger = logging.getLogger()

    # Clear any existing handlers to avoid duplicates on repeated calls
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(LOG_FORMAT)

    # File handler: DEBUG level, writes to daily log file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"tablebuilder_{today}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler: WARNING by default, DEBUG if verbose
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.

    Args:
        name: Dotted logger name (e.g. "tablebuilder.browser").

    Returns:
        A logging.Logger instance with the given name.
    """
    return logging.getLogger(name)
