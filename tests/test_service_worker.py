# ABOUTME: Tests for the background job worker thread.
# ABOUTME: Validates job lifecycle, error handling, and HTTP-based fetch pipeline.

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
    @patch("tablebuilder.service.worker.http_fetch_table")
    @patch("tablebuilder.service.worker.TableBuilderHTTPSession")
    def test_successful_job(
        self, mock_session_cls, mock_fetch,
        db, results_dir, encryption_key
    ):
        """A successful job moves from queued -> running -> completed."""
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

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
        mock_fetch.assert_called_once()

    @patch("tablebuilder.service.worker.TableBuilderHTTPSession")
    def test_failed_job_captures_error(
        self, mock_session_cls, db, results_dir, encryption_key
    ):
        """A failed job records error message, detail, and marks as failed."""
        mock_session_cls.return_value.__enter__ = MagicMock(
            side_effect=Exception("HTTP login failed")
        )
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        job_id = _create_test_job(db, encryption_key)

        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        worker.process_one_job()

        job = db.get_job(job_id)
        assert job["status"] == "failed"
        assert "HTTP login failed" in job["error_message"]

    @patch("tablebuilder.service.worker.http_fetch_table")
    @patch("tablebuilder.service.worker.TableBuilderHTTPSession")
    def test_fetch_error_marks_failed(
        self, mock_session_cls, mock_fetch, db, results_dir, encryption_key
    ):
        """An error during fetch marks the job as failed with details."""
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_fetch.side_effect = Exception("Variable not found")

        job_id = _create_test_job(db, encryption_key)

        worker = Worker(
            db=db,
            results_dir=results_dir,
            encryption_key=encryption_key,
        )
        worker.process_one_job()

        job = db.get_job(job_id)
        assert job["status"] == "failed"
        assert "Variable not found" in job["error_message"]

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
