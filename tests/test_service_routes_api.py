# ABOUTME: Tests for the service REST API routes.
# ABOUTME: Covers auth registration, job CRUD, dictionary search, and error responses.

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tablebuilder.service.app import create_app
from tablebuilder.service.auth import generate_encryption_key


@pytest.fixture
def app_env(tmp_path):
    """Set up a test app with temporary database and results directory."""
    db_path = tmp_path / "test.db"
    results_dir = tmp_path / "results"
    encryption_key = generate_encryption_key()
    app = create_app(
        db_path=db_path,
        results_dir=results_dir,
        encryption_key=encryption_key,
        start_worker=False,
    )
    return app, db_path, results_dir, encryption_key


@pytest.fixture
def client(app_env):
    app, _, _, _ = app_env
    return TestClient(app)


@pytest.fixture
def registered_client(client):
    """A client with a registered user. Returns (client, api_key)."""
    resp = client.post("/api/auth/register", json={
        "abs_user_id": "testuser",
        "abs_password": "testpass",
    })
    api_key = resp.json()["api_key"]
    return client, api_key


class TestAuthRegister:
    def test_register_returns_api_key(self, client):
        resp = client.post("/api/auth/register", json={
            "abs_user_id": "testuser",
            "abs_password": "testpass",
        })
        assert resp.status_code == 200
        assert "api_key" in resp.json()
        assert resp.json()["api_key"].startswith("tb_")

    def test_register_missing_fields(self, client):
        resp = client.post("/api/auth/register", json={"abs_user_id": "test"})
        assert resp.status_code == 422


class TestAuthVerify:
    @patch("tablebuilder.service.routes_api.TableBuilderSession")
    def test_verify_valid_credentials(self, mock_session, registered_client):
        mock_page = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_page)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        client, api_key = registered_client
        resp = client.post(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "valid"

    @patch("tablebuilder.service.routes_api.TableBuilderSession")
    def test_verify_invalid_credentials(self, mock_session, registered_client):
        from tablebuilder.browser import LoginError
        mock_session.return_value.__enter__ = MagicMock(side_effect=LoginError("Bad creds"))
        client, api_key = registered_client
        resp = client.post(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 401

    def test_verify_without_auth(self, client):
        resp = client.post("/api/auth/verify")
        assert resp.status_code == 401


class TestAuthDelete:
    def test_delete_credentials(self, registered_client):
        client, api_key = registered_client
        resp = client.delete(
            "/api/auth/credentials",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        resp = client.get(
            "/api/jobs",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 401

    def test_delete_without_auth(self, client):
        resp = client.delete("/api/auth/credentials")
        assert resp.status_code == 401


class TestDictionarySearch:
    def test_search_no_auth_required(self, client):
        resp = client.get("/api/search", params={"q": "population"})
        assert resp.status_code == 200

    def test_search_returns_list(self, client):
        resp = client.get("/api/search", params={"q": "age"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestJobSubmission:
    def test_submit_job(self, registered_client):
        client, api_key = registered_client
        resp = client.post(
            "/api/jobs",
            json={"dataset": "Test Dataset", "rows": ["VAR1"]},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "queued"

    def test_submit_job_without_auth(self, client):
        resp = client.post("/api/jobs", json={"dataset": "X", "rows": ["Y"]})
        assert resp.status_code == 401

    def test_submit_job_empty_rows(self, registered_client):
        client, api_key = registered_client
        resp = client.post(
            "/api/jobs",
            json={"dataset": "Test", "rows": []},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    def test_get_job_status(self, registered_client):
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = client.post("/api/jobs", json={"dataset": "Test", "rows": ["V"]}, headers=headers)
        job_id = resp.json()["job_id"]
        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_list_jobs(self, registered_client):
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}
        client.post("/api/jobs", json={"dataset": "D", "rows": ["R"]}, headers=headers)
        client.post("/api/jobs", json={"dataset": "D", "rows": ["R"]}, headers=headers)
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_download_before_completion(self, registered_client):
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = client.post("/api/jobs", json={"dataset": "D", "rows": ["R"]}, headers=headers)
        job_id = resp.json()["job_id"]
        resp = client.get(f"/api/jobs/{job_id}/download", headers=headers)
        assert resp.status_code == 409

    def test_get_job_events(self, registered_client):
        client, api_key = registered_client
        headers ={"Authorization": f"Bearer {api_key}"}
        resp = client.post("/api/jobs", json={"dataset": "D", "rows": ["R"]}, headers=headers)
        job_id = resp.json()["job_id"]
        resp = client.get(f"/api/jobs/{job_id}/events", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
