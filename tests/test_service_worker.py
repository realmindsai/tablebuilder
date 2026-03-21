# ABOUTME: Tests for the background job worker thread.
# ABOUTME: Validates job lifecycle, error handling, and screenshot capture.

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tablebuilder.service.db import ServiceDB
from tablebuilder.service.worker import Worker


@pytest.fixture
def db(tmp_path):
    return ServiceDB(tmp_path / "test.db")


@pytest.fixture
def results_dir(tmp_path):
    return tmp_path / "results"


@pytest.fixture
def encryption_key():
    from tablebuilder.service.auth import generate_encryption_key
    return generate_encryption_key()


def _create_test_job(db, encryption_key):
    """Helper to create a user and job for testing."""
    from tablebuilder.service.auth import encrypt_credentials
    creds = encrypt_credentials(encryption_key, "testuser", "testpass")
    user_id = db.create_user(api_key_hash="h", abs_credentials_encrypted=creds)
    request = {"dataset": "Test", "rows": ["VAR1"], "cols": [], "wafers": []}
    job_id = db.create_job(user_id=user_id, request_json=json.dumps(request))
    return job_id


class TestWorkerJobLifecycle:
    @patch("tablebuilder.service.worker.TableBuilderSession")
    @patch("tablebuilder.service.worker.open_dataset")
    @patch("tablebuilder.service.worker.build_table")
    @patch("tablebuilder.service.worker.queue_and_download")
    def test_successful_job(
        self, mock_download, mock_build, mock_open, mock_session,
        db, results_dir, encryption_key
    ):
        """A successful job moves from queued -> running -> completed."""
        mock_page = MagicMock()
        mock_session_instance = MagicMock()
        mock_session_instance.__enter__ = MagicMock(return_value=mock_page)
        mock_session_instance.__exit__ = MagicMock(return_value=False)
        mock_session.return_value = mock_session_instance

        job_id = _create_test_job(db, encryption_key)

        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        worker.process_one_job()

        job = db.get_job(job_id)
        assert job["status"] == "completed"
        events = db.get_events(job_id)
        assert any("Logging in" in e["message"] for e in events)
        assert any("Download complete" in e["message"] for e in events)

    @patch("tablebuilder.service.worker.TableBuilderSession")
    def test_failed_job_captures_error(
        self, mock_session, db, results_dir, encryption_key
    ):
        """A failed job records error message, detail, and marks as failed."""
        mock_session.side_effect = Exception("Browser exploded")

        job_id = _create_test_job(db, encryption_key)

        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        worker.process_one_job()

        job = db.get_job(job_id)
        assert job["status"] == "failed"
        assert "Browser exploded" in job["error_message"]

    @patch("tablebuilder.service.worker.TableBuilderSession")
    @patch("tablebuilder.service.worker.open_dataset")
    def test_session_expired_marks_failed(
        self, mock_open, mock_session, db, results_dir, encryption_key
    ):
        """SessionExpiredError during pipeline marks job as failed with event log."""
        from tablebuilder.navigator import SessionExpiredError

        mock_page = MagicMock()
        mock_session_instance = MagicMock()
        mock_session_instance.__enter__ = MagicMock(return_value=mock_page)
        mock_session_instance.__exit__ = MagicMock(return_value=False)
        mock_session.return_value = mock_session_instance
        mock_open.side_effect = SessionExpiredError("Session expired")

        job_id = _create_test_job(db, encryption_key)

        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        worker.process_one_job()

        job = db.get_job(job_id)
        assert job["status"] == "failed"
        assert "Session expired" in job["error_message"]
        events = db.get_events(job_id)
        assert any("Session expired" in e["message"] or "relogin" in e["message"].lower() for e in events)

    def test_no_jobs_returns_false(self, db, results_dir, encryption_key):
        """process_one_job returns False when no jobs are queued."""
        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        assert worker.process_one_job() is False


class TestWorkerThread:
    def test_start_and_stop(self, db, results_dir, encryption_key):
        """Worker can be started and stopped cleanly."""
        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        worker.start()
        assert worker.is_alive()
        worker.stop()
        worker.join(timeout=10)
        assert not worker.is_alive()
