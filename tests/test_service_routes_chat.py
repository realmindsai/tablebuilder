# ABOUTME: Tests for the chat API routes.
# ABOUTME: Validates session creation, multi-turn conversation, and job confirmation.

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from tablebuilder.service.app import create_app
from tablebuilder.service.auth import generate_encryption_key


@pytest.fixture
def app_env(tmp_path):
    db_path = tmp_path / "test.db"
    results_dir = tmp_path / "results"
    encryption_key = generate_encryption_key()
    app = create_app(
        db_path=db_path,
        results_dir=results_dir,
        encryption_key=encryption_key,
        anthropic_api_key="test-key",
        start_worker=False,
    )
    return app


@pytest.fixture
def registered_client(app_env):
    client = TestClient(app_env)
    resp = client.post("/api/auth/register", json={
        "abs_user_id": "testuser",
        "abs_password": "testpass",
    })
    api_key = resp.json()["api_key"]
    return client, api_key


class TestChatRoutes:
    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_chat_creates_session(self, mock_resolve, registered_client):
        mock_resolve.return_value = {
            "dataset": "Census 2021",
            "rows": ["SEXP Sex"],
            "cols": [],
            "wafers": [],
            "confirmation": "Shall I fetch this?",
        }
        client, api_key = registered_client
        resp = client.post(
            "/api/chat",
            json={"message": "population by sex"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_chat_confirm_creates_job(self, mock_resolve, registered_client):
        mock_resolve.return_value = {
            "dataset": "Census 2021",
            "rows": ["SEXP Sex"],
            "cols": [],
            "wafers": [],
            "confirmation": "Shall I fetch this?",
        }
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}

        resp = client.post(
            "/api/chat",
            json={"message": "population by sex"},
            headers=headers,
        )
        session_id = resp.json()["session_id"]

        resp = client.post(
            "/api/chat/confirm",
            json={"session_id": session_id},
            headers=headers,
        )
        assert resp.status_code == 200
        assert "job_id" in resp.json()

    def test_chat_without_auth(self, app_env):
        client = TestClient(app_env)
        resp = client.post("/api/chat", json={"message": "test"})
        assert resp.status_code == 401
