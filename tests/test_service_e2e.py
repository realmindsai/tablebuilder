# ABOUTME: End-to-end test for the full service lifecycle.
# ABOUTME: Tests register -> submit job -> poll -> download with mocked Playwright.

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from tablebuilder.service.app import create_app
from tablebuilder.service.auth import generate_encryption_key


@pytest.fixture
def service(tmp_path):
    """Create a full service with worker running."""
    db_path = tmp_path / "e2e.db"
    results_dir = tmp_path / "results"
    encryption_key = generate_encryption_key()
    app = create_app(
        db_path=db_path,
        results_dir=results_dir,
        encryption_key=encryption_key,
        start_worker=False,
    )
    client = TestClient(app)
    return client, app, results_dir


class TestServiceE2E:
    @patch("tablebuilder.service.worker.TableBuilderSession")
    @patch("tablebuilder.service.worker.open_dataset")
    @patch("tablebuilder.service.worker.build_table")
    @patch("tablebuilder.service.worker.queue_and_download")
    def test_full_lifecycle(
        self, mock_download, mock_build, mock_open, mock_session, service
    ):
        """Register -> submit -> process -> poll -> download."""
        client, app, results_dir = service

        mock_page = MagicMock()
        mock_sess = MagicMock()
        mock_sess.__enter__ = MagicMock(return_value=mock_page)
        mock_sess.__exit__ = MagicMock(return_value=False)
        mock_session.return_value = mock_sess

        def fake_download(page, output_path, timeout=600, knowledge=None):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text("col1,col2\n1,2\n")

        mock_download.side_effect = fake_download

        # 1. Register
        resp = client.post("/api/auth/register", json={
            "abs_user_id": "testuser",
            "abs_password": "testpass",
        })
        assert resp.status_code == 200
        api_key = resp.json()["api_key"]
        headers = {"Authorization": f"Bearer {api_key}"}

        # 2. Submit job
        resp = client.post("/api/jobs", json={
            "dataset": "Census 2021",
            "rows": ["SEXP Sex"],
        }, headers=headers)
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        # 3. Verify queued
        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.json()["status"] == "queued"

        # 4. Process the job via worker
        from tablebuilder.service.worker import Worker
        worker = Worker(
            db=app.state.db,
            results_dir=results_dir,
            encryption_key=app.state.encryption_key,
        )
        worker.process_one_job()

        # 5. Verify completed
        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.json()["status"] == "completed"
        assert "result_url" in resp.json()

        # 6. Download
        resp = client.get(f"/api/jobs/{job_id}/download", headers=headers)
        assert resp.status_code == 200
        assert "col1,col2" in resp.text

        # 7. Check events
        resp = client.get(f"/api/jobs/{job_id}/events", headers=headers)
        events = resp.json()
        assert len(events) > 0
        messages = [e["message"] for e in events]
        assert any("Logging in" in m for m in messages)
        assert any("Download complete" in m for m in messages)
