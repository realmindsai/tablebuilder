# ABOUTME: Tests for the structured logging configuration module.
# ABOUTME: Verifies log directory creation, named loggers, file output, and verbosity levels.

import logging

import pytest

from tablebuilder.logging_config import LOG_DIR, get_logger, setup_logging


class TestSetupLoggingCreatesLogDirectory:
    """setup_logging() should create the log directory if it doesn't exist."""

    def test_setup_logging_creates_log_directory(self, tmp_path, monkeypatch):
        log_dir = tmp_path / ".tablebuilder" / "logs"
        monkeypatch.setattr("tablebuilder.logging_config.LOG_DIR", log_dir)

        setup_logging()

        assert log_dir.exists()
        assert log_dir.is_dir()


class TestGetLoggerReturnsNamedLogger:
    """get_logger() should return a logger with the requested name."""

    def test_get_logger_returns_named_logger(self):
        logger = get_logger("test.module")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"


class TestFileHandlerWritesToLog:
    """After setup_logging(), messages should appear in the daily log file."""

    def test_file_handler_writes_to_log(self, tmp_path, monkeypatch):
        log_dir = tmp_path / ".tablebuilder" / "logs"
        monkeypatch.setattr("tablebuilder.logging_config.LOG_DIR", log_dir)

        logger = setup_logging()
        logger.debug("test message from file handler test")

        log_files = list(log_dir.glob("tablebuilder_*.log"))
        assert len(log_files) >= 1

        contents = log_files[0].read_text()
        assert "test message from file handler test" in contents


class TestVerboseChangesConsoleLevel:
    """verbose flag should control the console handler's log level."""

    def test_verbose_false_sets_console_to_warning(self, tmp_path, monkeypatch):
        log_dir = tmp_path / ".tablebuilder" / "logs"
        monkeypatch.setattr("tablebuilder.logging_config.LOG_DIR", log_dir)

        logger = setup_logging(verbose=False)

        console_handlers = [
            h for h in logger.handlers if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].level == logging.WARNING

    def test_verbose_true_sets_console_to_debug(self, tmp_path, monkeypatch):
        log_dir = tmp_path / ".tablebuilder" / "logs"
        monkeypatch.setattr("tablebuilder.logging_config.LOG_DIR", log_dir)

        logger = setup_logging(verbose=True)

        console_handlers = [
            h for h in logger.handlers if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].level == logging.DEBUG
