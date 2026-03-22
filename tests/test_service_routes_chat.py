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
            "text": "I found Census 2021 with variable SEXP Sex. Shall I fetch this?",
            "display_payloads": [],
            "messages": [],
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
    def test_chat_returns_text_and_payloads(self, mock_resolve, registered_client):
        """Chat endpoint returns text and display_payloads from resolver."""
        mock_resolve.return_value = {
            "text": "I found some data for you.",
            "display_payloads": [
                {"type": "proposal", "data": {"id": "p1", "dataset": "Census 2021"}},
            ],
            "messages": [
                {"role": "user", "content": "test"},
                {"role": "assistant", "content": [{"type": "text", "text": "I found some data for you."}]},
            ],
        }
        client, api_key = registered_client
        resp = client.post(
            "/api/chat",
            json={"message": "test"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "text" in body["response"]
        assert "display_payloads" in body["response"]

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_chat_confirm_creates_job(self, mock_resolve, registered_client):
        mock_resolve.return_value = {
            "text": "Here's a dataset for you.",
            "display_payloads": [
                {"type": "proposal", "data": {
                    "id": "p1", "dataset": "Census 2021", "rows": ["SEXP Sex"],
                    "cols": [], "wafers": [], "match_confidence": 85,
                    "clarity_confidence": 75, "rationale": "test",
                    "status": "checked", "job_id": None,
                }},
            ],
            "messages": [],
        }
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}

        # Chat first (this persists the proposal via the updated route)
        resp = client.post("/api/chat", json={"message": "test"}, headers=headers)
        session_id = resp.json()["session_id"]

        # Confirm
        resp = client.post("/api/chat/confirm", json={"session_id": session_id}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "jobs" in body
        assert len(body["jobs"]) == 1

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_confirm_queues_checked_proposals(self, mock_resolve, registered_client):
        """Confirm creates jobs for all checked proposals."""
        mock_resolve.return_value = {
            "text": "Here are two datasets for you.",
            "display_payloads": [
                {"type": "proposal", "data": {
                    "id": "p1", "dataset": "Census 2021", "rows": ["SEXP Sex"],
                    "cols": [], "wafers": [], "match_confidence": 85,
                    "clarity_confidence": 75, "rationale": "test",
                    "status": "checked", "job_id": None,
                }},
                {"type": "proposal", "data": {
                    "id": "p2", "dataset": "Census 2021", "rows": ["AGEP Age"],
                    "cols": [], "wafers": [], "match_confidence": 80,
                    "clarity_confidence": 75, "rationale": "test",
                    "status": "checked", "job_id": None,
                }},
            ],
            "messages": [],
        }
        client, api_key = registered_client
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = client.post("/api/chat", json={"message": "test"}, headers=headers)
        session_id = resp.json()["session_id"]
        resp = client.post("/api/chat/confirm", json={"session_id": session_id}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["jobs"]) == 2

    def test_chat_without_auth(self, app_env):
        client = TestClient(app_env)
        resp = client.post("/api/chat", json={"message": "test"})
        assert resp.status_code == 401
