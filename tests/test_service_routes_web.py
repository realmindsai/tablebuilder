# ABOUTME: Tests for web UI routes including cart toggle and fetch endpoints.
# ABOUTME: Validates HTMX-based proposal management and job creation from cart.

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from tablebuilder.service.app import create_app
from tablebuilder.service.auth import generate_api_key, generate_encryption_key, hash_api_key


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
    client.cookies.set("tb_api_key", api_key)
    return client, api_key, app_env


class TestCartToggle:
    def test_toggle_unchecks_proposal(self, registered_client):
        """POST /web/cart/toggle/{id} toggles a checked proposal to unchecked."""
        client, api_key, app = registered_client
        db = app.state.db
        key_hash = hash_api_key(api_key)
        user = db.get_user_by_api_key_hash(key_hash)
        session_id = db.create_chat_session(user_id=user["id"], messages_json="[]")
        db.add_proposal(session_id, {
            "id": "p1", "dataset": "D", "rows": ["R"], "cols": [], "wafers": [],
            "match_confidence": 80, "clarity_confidence": 70,
            "rationale": "test", "status": "checked", "job_id": None,
        })
        resp = client.post(
            f"/web/cart/toggle/p1",
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        proposals = db.get_proposals(session_id)
        assert proposals[0]["status"] == "unchecked"

    def test_toggle_checks_unchecked_proposal(self, registered_client):
        """Toggle an unchecked proposal back to checked."""
        client, api_key, app = registered_client
        db = app.state.db
        key_hash = hash_api_key(api_key)
        user = db.get_user_by_api_key_hash(key_hash)
        session_id = db.create_chat_session(user_id=user["id"], messages_json="[]")
        db.add_proposal(session_id, {
            "id": "p1", "dataset": "D", "rows": ["R"], "cols": [], "wafers": [],
            "match_confidence": 80, "clarity_confidence": 70,
            "rationale": "test", "status": "unchecked", "job_id": None,
        })
        resp = client.post(
            f"/web/cart/toggle/p1",
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        proposals = db.get_proposals(session_id)
        assert proposals[0]["status"] == "checked"


class TestCartFetch:
    def test_fetch_creates_jobs_for_checked(self, registered_client):
        """POST /web/cart/fetch queues jobs for all checked proposals."""
        client, api_key, app = registered_client
        db = app.state.db
        key_hash = hash_api_key(api_key)
        user = db.get_user_by_api_key_hash(key_hash)
        session_id = db.create_chat_session(user_id=user["id"], messages_json="[]")
        db.add_proposal(session_id, {
            "id": "p1", "dataset": "Census 2021", "rows": ["SEXP Sex"],
            "cols": [], "wafers": [], "match_confidence": 85,
            "clarity_confidence": 75, "rationale": "test",
            "status": "checked", "job_id": None,
        })
        db.add_proposal(session_id, {
            "id": "p2", "dataset": "Census 2021", "rows": ["AGEP Age"],
            "cols": [], "wafers": [], "match_confidence": 80,
            "clarity_confidence": 70, "rationale": "test",
            "status": "unchecked", "job_id": None,
        })
        resp = client.post(
            "/web/cart/fetch",
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        jobs = db.list_user_jobs(user["id"])
        assert len(jobs) == 1


class TestWebChat:
    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_web_chat_returns_oob_cart_update(self, mock_resolve, registered_client):
        """Web chat includes OOB swap for cart when proposals are returned."""
        mock_resolve.return_value = {
            "text": "I found income data for you.",
            "display_payloads": [
                {"type": "proposal", "data": {
                    "id": "p1", "dataset": "Census 2021", "rows": ["INCP Income"],
                    "cols": [], "wafers": [], "match_confidence": 85,
                    "clarity_confidence": 75, "rationale": "Income match",
                    "status": "checked", "job_id": None,
                }},
            ],
            "messages": [],
        }
        client, api_key, app = registered_client
        resp = client.post(
            "/web/chat",
            data={"message": "income data", "session_id": ""},
        )
        assert resp.status_code == 200
        html = resp.text
        assert "I found income data for you." in html
        assert 'hx-swap-oob' in html
        assert "Census 2021" in html
