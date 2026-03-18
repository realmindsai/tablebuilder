# ABOUTME: Tests for job event logging and screenshot capture.
# ABOUTME: Validates that the logger writes events and captures artifacts.

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tablebuilder.service.db import ServiceDB
from tablebuilder.service.job_logger import JobLogger


@pytest.fixture
def db(tmp_path):
    return ServiceDB(tmp_path / "test.db")


@pytest.fixture
def results_dir(tmp_path):
    return tmp_path / "results"


@pytest.fixture
def logger(db, results_dir):
    user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted="c")
    job_id = db.create_job(user_id=user_id, request_json='{}')
    return JobLogger(db=db, job_id=job_id, results_dir=results_dir)


class TestJobLoggerEvents:
    def test_log_progress(self, logger, db):
        logger.log_progress("Logging in...")
        events = db.get_events(logger.job_id)
        assert len(events) == 1
        assert events[0]["event_type"] == "progress"
        assert events[0]["message"] == "Logging in..."

    def test_log_progress_updates_job(self, logger, db):
        logger.log_progress("Building table...")
        job = db.get_job(logger.job_id)
        assert job["progress"] == "Building table..."

    def test_log_warning(self, logger, db):
        logger.log_warning("Session expired, retrying")
        events = db.get_events(logger.job_id)
        assert events[0]["event_type"] == "warning"

    def test_log_error(self, logger, db):
        logger.log_error("Login failed", detail="Traceback...")
        events = db.get_events(logger.job_id)
        assert events[0]["event_type"] == "error"
        assert events[0]["detail"] == "Traceback..."


class TestJobLoggerScreenshots:
    def test_capture_screenshot(self, logger, results_dir):
        page = MagicMock()
        logger.capture_screenshot(page, "after_login")
        expected_dir = results_dir / logger.job_id / "screenshots"
        assert expected_dir.exists()
        call_args = page.screenshot.call_args
        path = Path(call_args.kwargs["path"])
        assert "after_login" in path.name
        assert path.parent == expected_dir

    def test_screenshot_counter_increments(self, logger):
        page = MagicMock()
        logger.capture_screenshot(page, "step1")
        logger.capture_screenshot(page, "step2")
        call1 = page.screenshot.call_args_list[0]
        call2 = page.screenshot.call_args_list[1]
        path1 = Path(call1.kwargs["path"]).name
        path2 = Path(call2.kwargs["path"]).name
        assert path1.startswith("001_")
        assert path2.startswith("002_")

    def test_capture_screenshot_handles_error(self, logger, db):
        """If page.screenshot raises, log a warning but don't crash."""
        page = MagicMock()
        page.screenshot.side_effect = Exception("Browser crashed")
        logger.capture_screenshot(page, "failure")
        events = db.get_events(logger.job_id)
        assert any(e["event_type"] == "warning" for e in events)


class TestJobLoggerPageCapture:
    def test_save_page_html(self, logger, results_dir):
        page = MagicMock()
        page.content.return_value = "<html><body>Hello</body></html>"
        page.url = "https://tablebuilder.abs.gov.au/some/page"
        path = logger.save_page_state(page)
        assert Path(path).exists()
        assert "<html>" in Path(path).read_text()

    def test_save_page_state_handles_error(self, logger):
        """If page.content() raises, return empty string."""
        page = MagicMock()
        page.content.side_effect = Exception("Browser crashed")
        path = logger.save_page_state(page)
        assert path == ""
