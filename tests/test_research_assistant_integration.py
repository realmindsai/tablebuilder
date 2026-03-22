# ABOUTME: Integration tests for the research assistant bot.
# ABOUTME: Tests full conversation flow through web and API routes with real DB.

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tablebuilder.service.app import create_app
from tablebuilder.service.auth import generate_encryption_key, hash_api_key


# -- Fixtures --


@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "test.db"
    results_dir = tmp_path / "results"
    encryption_key = generate_encryption_key()
    return create_app(
        db_path=db_path,
        results_dir=results_dir,
        encryption_key=encryption_key,
        anthropic_api_key="test-key",
        start_worker=False,
    )


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def registered_api_client(client):
    """Register a user and return (client, api_key, headers) for API routes."""
    resp = client.post("/api/auth/register", json={
        "abs_user_id": "testuser",
        "abs_password": "testpass",
    })
    api_key = resp.json()["api_key"]
    headers = {"Authorization": f"Bearer {api_key}"}
    return client, api_key, headers


@pytest.fixture
def registered_web_client(client):
    """Register a user and return (client, api_key, app) for web routes with cookie set."""
    resp = client.post("/api/auth/register", json={
        "abs_user_id": "testuser",
        "abs_password": "testpass",
    })
    api_key = resp.json()["api_key"]
    client.cookies.set("tb_api_key", api_key)
    return client, api_key


def _make_proposal(proposal_id, dataset, rows, **overrides):
    """Build a proposal dict with sensible defaults."""
    base = {
        "id": proposal_id,
        "dataset": dataset,
        "rows": rows,
        "cols": [],
        "wafers": [],
        "match_confidence": 85,
        "clarity_confidence": 75,
        "rationale": f"Good match for {dataset}",
        "status": "checked",
        "job_id": None,
    }
    base.update(overrides)
    return base


def _resolver_result(text, proposals=None, choices=None):
    """Build a resolver return value with optional proposals and choices."""
    payloads = []
    if proposals:
        for p in proposals:
            payloads.append({"type": "proposal", "data": p})
    if choices:
        payloads.append({"type": "choices", "data": choices})
    return {
        "text": text,
        "display_payloads": payloads,
        "messages": [
            {"role": "user", "content": "test"},
            {"role": "assistant", "content": [{"type": "text", "text": text}]},
        ],
    }


# -- Integration Test Classes --


class TestFullConversationFlow:
    """Scenario 1: chat -> proposal -> cart -> toggle -> fetch -> events."""

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_chat_to_proposal_to_cart_to_fetch(self, mock_resolve, registered_api_client, app):
        """Full lifecycle: send message, get proposal, toggle, fetch, verify events."""
        client, api_key, headers = registered_api_client
        db = app.state.db

        proposal = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        mock_resolve.return_value = _resolver_result(
            "I found sex data in Census 2021.", proposals=[proposal],
        )

        # 1. Chat -> proposal is created
        resp = client.post("/api/chat", json={"message": "population by sex"}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        session_id = body["session_id"]
        assert body["response"]["text"] == "I found sex data in Census 2021."
        assert len(body["response"]["display_payloads"]) == 1
        assert body["response"]["display_payloads"][0]["type"] == "proposal"

        # 2. Verify proposal is in DB
        proposals = db.get_proposals(session_id)
        assert len(proposals) == 1
        assert proposals[0]["dataset"] == "Census 2021"
        assert proposals[0]["status"] == "checked"

        # 3. Toggle proposal off
        db.update_proposal_status(session_id, "p1", "unchecked")
        db.add_session_event(session_id, "proposal_toggled", "p1 -> unchecked")
        proposals = db.get_proposals(session_id)
        assert proposals[0]["status"] == "unchecked"

        # 4. Toggle proposal back on
        db.update_proposal_status(session_id, "p1", "checked")
        db.add_session_event(session_id, "proposal_toggled", "p1 -> checked")
        proposals = db.get_proposals(session_id)
        assert proposals[0]["status"] == "checked"

        # 5. Confirm -> job is created
        resp = client.post(
            "/api/chat/confirm", json={"session_id": session_id}, headers=headers,
        )
        assert resp.status_code == 200
        confirm_body = resp.json()
        assert len(confirm_body["jobs"]) == 1
        assert confirm_body["jobs"][0]["dataset"] == "Census 2021"
        job_id = confirm_body["jobs"][0]["job_id"]

        # 6. Verify job exists
        job = db.get_job(job_id)
        assert job is not None
        assert job["status"] == "queued"

        # 7. Verify session events cover the full flow
        events = db.get_session_events(session_id)
        event_types = [e["event_type"] for e in events]
        assert "user_message" in event_types
        assert "assistant_message" in event_types
        assert "proposal_created" in event_types
        assert "proposal_toggled" in event_types
        assert "jobs_queued" in event_types


class TestMultiProposalSession:
    """Scenario 2: Multiple proposals, selective fetch."""

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_two_proposals_uncheck_one_fetch(self, mock_resolve, registered_api_client, app):
        """Two proposals, uncheck one, fetch -> only 1 job created."""
        client, api_key, headers = registered_api_client
        db = app.state.db

        p1 = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        p2 = _make_proposal("p2", "Census 2021", ["AGEP Age"])
        mock_resolve.return_value = _resolver_result(
            "I found two relevant variables.", proposals=[p1, p2],
        )

        resp = client.post("/api/chat", json={"message": "sex and age data"}, headers=headers)
        session_id = resp.json()["session_id"]

        # Verify both proposals are saved
        proposals = db.get_proposals(session_id)
        assert len(proposals) == 2

        # Uncheck p2
        db.update_proposal_status(session_id, "p2", "unchecked")

        # Confirm -> only p1 should become a job
        resp = client.post(
            "/api/chat/confirm", json={"session_id": session_id}, headers=headers,
        )
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        assert len(jobs) == 1
        assert jobs[0]["dataset"] == "Census 2021"

        # Verify p2 is still in the cart as unchecked (not lost)
        proposals = db.get_proposals(session_id)
        unchecked = [p for p in proposals if p["status"] == "unchecked"]
        assert len(unchecked) == 1
        assert unchecked[0]["id"] == "p2"

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_confirm_with_all_unchecked_returns_400(self, mock_resolve, registered_api_client, app):
        """Confirm with no checked proposals returns 400."""
        client, api_key, headers = registered_api_client
        db = app.state.db

        p1 = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        mock_resolve.return_value = _resolver_result("Found data.", proposals=[p1])

        resp = client.post("/api/chat", json={"message": "test"}, headers=headers)
        session_id = resp.json()["session_id"]

        # Uncheck the only proposal
        db.update_proposal_status(session_id, "p1", "unchecked")

        resp = client.post(
            "/api/chat/confirm", json={"session_id": session_id}, headers=headers,
        )
        assert resp.status_code == 400


class TestChoiceButtonsFlow:
    """Scenario 3: Choices returned from resolver."""

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_choices_rendered_in_web_chat(self, mock_resolve, registered_web_client, app):
        """Chat returning choices produces HTML with choice buttons."""
        client, api_key = registered_web_client

        choices_data = {
            "question": "Which geographic level?",
            "options": [
                {"label": "SA2", "description": "Statistical Area Level 2"},
                {"label": "SA3", "description": "Statistical Area Level 3"},
                {"label": "LGA", "description": "Local Government Area"},
            ],
            "allow_multiple": False,
        }
        mock_resolve.return_value = _resolver_result(
            "I need to know the geographic level.", choices=choices_data,
        )

        resp = client.post("/web/chat", data={"message": "population data", "session_id": ""})
        assert resp.status_code == 200
        html = resp.text

        # Verify choice buttons are present
        assert "SA2" in html
        assert "SA3" in html
        assert "LGA" in html
        assert 'name="message"' in html
        assert 'value="SA2"' in html

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_choice_selection_sends_label_as_message(self, mock_resolve, registered_web_client, app):
        """Selecting a choice sends the label as the next chat message."""
        client, api_key = registered_web_client
        db = app.state.db

        # First message returns choices
        choices_data = {
            "question": "Which level?",
            "options": [{"label": "SA2"}, {"label": "SA3"}],
            "allow_multiple": False,
        }
        mock_resolve.return_value = _resolver_result(
            "Pick a level.", choices=choices_data,
        )
        resp = client.post("/web/chat", data={"message": "population", "session_id": ""})
        session_id_html = resp.text
        # Extract session_id from the script tag
        import re
        match = re.search(r'getElementById\("session_id"\)\.value = "([^"]+)"', session_id_html)
        assert match, "Session ID not found in response HTML"
        session_id = match.group(1)

        # Second message: user "clicks" SA2
        proposal = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        mock_resolve.return_value = _resolver_result(
            "Great, SA2 it is!", proposals=[proposal],
        )
        resp = client.post(
            "/web/chat",
            data={"message": "SA2", "session_id": session_id},
        )
        assert resp.status_code == 200

        # Verify the resolver was called with "SA2" as the message
        call_args = mock_resolve.call_args
        assert call_args[0][0] == "SA2"


class TestSessionEventAuditTrail:
    """Scenario 4: Verify session events are logged in order."""

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_full_conversation_event_trail(self, mock_resolve, registered_api_client, app):
        """A full conversation produces an ordered audit trail of session events."""
        client, api_key, headers = registered_api_client
        db = app.state.db

        proposal = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        mock_resolve.return_value = _resolver_result(
            "Found Census 2021 for you.", proposals=[proposal],
        )

        # 1. Chat
        resp = client.post("/api/chat", json={"message": "sex data"}, headers=headers)
        session_id = resp.json()["session_id"]

        # 2. Toggle off
        db.update_proposal_status(session_id, "p1", "unchecked")
        db.add_session_event(session_id, "proposal_toggled", "p1 -> unchecked")

        # 3. Toggle on
        db.update_proposal_status(session_id, "p1", "checked")
        db.add_session_event(session_id, "proposal_toggled", "p1 -> checked")

        # 4. Confirm
        client.post("/api/chat/confirm", json={"session_id": session_id}, headers=headers)

        # 5. Verify events in order
        events = db.get_session_events(session_id)
        event_types = [e["event_type"] for e in events]

        assert event_types == [
            "user_message",
            "proposal_created",
            "assistant_message",
            "proposal_toggled",
            "proposal_toggled",
            "jobs_queued",
        ]

        # Verify event messages contain useful information
        user_msg_events = [e for e in events if e["event_type"] == "user_message"]
        assert user_msg_events[0]["message"] == "sex data"

        proposal_events = [e for e in events if e["event_type"] == "proposal_created"]
        assert "Census 2021" in proposal_events[0]["message"]

        # Verify metadata is persisted on proposal events
        meta = json.loads(proposal_events[0]["metadata_json"])
        assert meta["dataset"] == "Census 2021"

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_events_have_timestamps(self, mock_resolve, registered_api_client, app):
        """All session events have non-null timestamps."""
        client, api_key, headers = registered_api_client
        db = app.state.db

        mock_resolve.return_value = _resolver_result("Hello!", proposals=[])
        resp = client.post("/api/chat", json={"message": "hi"}, headers=headers)
        session_id = resp.json()["session_id"]

        events = db.get_session_events(session_id)
        assert len(events) >= 2  # user_message + assistant_message
        for event in events:
            assert event["timestamp"] is not None
            assert len(event["timestamp"]) > 0


class TestCartContextPassedToResolver:
    """Scenario 5: Cart state is visible to Claude."""

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_second_chat_includes_cart_context(self, mock_resolve, registered_api_client, app):
        """When proposals exist, the resolver receives cart_context on the next message."""
        client, api_key, headers = registered_api_client

        # First chat creates a proposal
        proposal = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        mock_resolve.return_value = _resolver_result(
            "I found sex data.", proposals=[proposal],
        )
        resp = client.post("/api/chat", json={"message": "sex data"}, headers=headers)
        session_id = resp.json()["session_id"]

        # Second chat should include cart context
        mock_resolve.return_value = _resolver_result("What else do you need?")
        resp = client.post(
            "/api/chat",
            json={"message": "what else is there?", "session_id": session_id},
            headers=headers,
        )
        assert resp.status_code == 200

        # Verify the resolver was called with cart_context containing the proposal
        call_args = mock_resolve.call_args
        cart_context = call_args.kwargs.get("cart_context", "")
        assert "Census 2021" in cart_context
        assert "CHECKED" in cart_context

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_unchecked_proposal_shown_as_unchecked_in_context(self, mock_resolve, registered_api_client, app):
        """Unchecked proposals appear as 'unchecked' in cart_context."""
        client, api_key, headers = registered_api_client
        db = app.state.db

        proposal = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        mock_resolve.return_value = _resolver_result("Found it.", proposals=[proposal])
        resp = client.post("/api/chat", json={"message": "sex data"}, headers=headers)
        session_id = resp.json()["session_id"]

        # Uncheck the proposal
        db.update_proposal_status(session_id, "p1", "unchecked")

        # Second chat
        mock_resolve.return_value = _resolver_result("OK.")
        client.post(
            "/api/chat",
            json={"message": "anything else?", "session_id": session_id},
            headers=headers,
        )

        call_args = mock_resolve.call_args
        cart_context = call_args.kwargs.get("cart_context", "")
        assert "unchecked" in cart_context


class TestApiRoutesJsonFormat:
    """Scenario 6: API routes return correct JSON structure."""

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_chat_response_format(self, mock_resolve, registered_api_client):
        """POST /api/chat returns {session_id, response: {text, display_payloads}}."""
        client, api_key, headers = registered_api_client

        mock_resolve.return_value = _resolver_result("Hello researcher!")
        resp = client.post("/api/chat", json={"message": "hi"}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()

        # Verify top-level keys
        assert "session_id" in body
        assert isinstance(body["session_id"], str)
        assert len(body["session_id"]) > 0

        assert "response" in body
        assert "text" in body["response"]
        assert "display_payloads" in body["response"]
        assert isinstance(body["response"]["display_payloads"], list)

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_confirm_response_format(self, mock_resolve, registered_api_client):
        """POST /api/chat/confirm returns {session_id, jobs: [...], status}."""
        client, api_key, headers = registered_api_client

        proposal = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        mock_resolve.return_value = _resolver_result("Found it.", proposals=[proposal])
        resp = client.post("/api/chat", json={"message": "test"}, headers=headers)
        session_id = resp.json()["session_id"]

        resp = client.post(
            "/api/chat/confirm", json={"session_id": session_id}, headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()

        assert body["session_id"] == session_id
        assert "jobs" in body
        assert isinstance(body["jobs"], list)
        assert len(body["jobs"]) == 1
        assert "job_id" in body["jobs"][0]
        assert "dataset" in body["jobs"][0]
        assert body["status"] == "queued"

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_multi_turn_conversation_via_api(self, mock_resolve, registered_api_client):
        """Multiple chat messages on the same session_id share history."""
        client, api_key, headers = registered_api_client

        # First message
        mock_resolve.return_value = _resolver_result("What topic?")
        resp = client.post("/api/chat", json={"message": "hi"}, headers=headers)
        session_id = resp.json()["session_id"]

        # Second message on same session
        mock_resolve.return_value = _resolver_result("Got it, looking up sex data.")
        resp = client.post(
            "/api/chat",
            json={"message": "sex data", "session_id": session_id},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["session_id"] == session_id

        # Verify resolver received conversation history on the second call
        call_args = mock_resolve.call_args
        history = call_args.kwargs.get("conversation_history", call_args[0][1] if len(call_args[0]) > 1 else [])
        assert len(history) > 0, "Second call should receive conversation history"

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_chat_without_session_creates_new(self, mock_resolve, registered_api_client, app):
        """Chat without session_id creates a fresh session."""
        client, api_key, headers = registered_api_client
        db = app.state.db

        mock_resolve.return_value = _resolver_result("Hello!")
        resp1 = client.post("/api/chat", json={"message": "hi"}, headers=headers)
        resp2 = client.post("/api/chat", json={"message": "hello"}, headers=headers)

        assert resp1.json()["session_id"] != resp2.json()["session_id"]


class TestWebCartFullFlow:
    """Test the full flow through web routes (HTMX-style)."""

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_web_chat_to_toggle_to_fetch(self, mock_resolve, registered_web_client, app):
        """Web: chat -> proposal -> toggle -> fetch -> verify job."""
        client, api_key = registered_web_client
        db = app.state.db

        proposal = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        mock_resolve.return_value = _resolver_result(
            "Found sex data.", proposals=[proposal],
        )

        # Chat via web
        resp = client.post("/web/chat", data={"message": "sex data", "session_id": ""})
        assert resp.status_code == 200
        html = resp.text
        assert "hx-swap-oob" in html  # Cart OOB swap present
        assert "Census 2021" in html

        # Extract session_id
        import re
        match = re.search(r'getElementById\("session_id"\)\.value = "([^"]+)"', html)
        assert match
        session_id = match.group(1)

        # Toggle off via web endpoint
        resp = client.post(
            "/web/cart/toggle/p1",
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        proposals = db.get_proposals(session_id)
        assert proposals[0]["status"] == "unchecked"

        # Toggle back on
        resp = client.post(
            "/web/cart/toggle/p1",
            data={"session_id": session_id},
        )
        assert resp.status_code == 200
        proposals = db.get_proposals(session_id)
        assert proposals[0]["status"] == "checked"

        # Fetch via web endpoint
        resp = client.post("/web/cart/fetch", data={"session_id": session_id})
        assert resp.status_code == 200

        # Verify job was created
        key_hash = hash_api_key(api_key)
        user = db.get_user_by_api_key_hash(key_hash)
        jobs = db.list_user_jobs(user["id"])
        assert len(jobs) == 1

        # Verify proposal status changed to confirmed
        proposals = db.get_proposals(session_id)
        assert proposals[0]["status"] == "confirmed"

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_web_fetch_no_checked_returns_400(self, mock_resolve, registered_web_client, app):
        """Web cart fetch with no checked proposals returns 400."""
        client, api_key = registered_web_client
        db = app.state.db

        proposal = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        mock_resolve.return_value = _resolver_result(
            "Found it.", proposals=[proposal],
        )

        resp = client.post("/web/chat", data={"message": "test", "session_id": ""})
        import re
        match = re.search(r'getElementById\("session_id"\)\.value = "([^"]+)"', resp.text)
        session_id = match.group(1)

        # Uncheck the proposal
        db.update_proposal_status(session_id, "p1", "unchecked")

        resp = client.post("/web/cart/fetch", data={"session_id": session_id})
        assert resp.status_code == 400

    @patch("tablebuilder.service.chat_resolver.ChatResolver.resolve")
    def test_web_toggle_logs_session_event(self, mock_resolve, registered_web_client, app):
        """Toggling a proposal via /web/cart/toggle logs a session event."""
        client, api_key = registered_web_client
        db = app.state.db

        proposal = _make_proposal("p1", "Census 2021", ["SEXP Sex"])
        mock_resolve.return_value = _resolver_result(
            "Here's data.", proposals=[proposal],
        )

        resp = client.post("/web/chat", data={"message": "test", "session_id": ""})
        import re
        match = re.search(r'getElementById\("session_id"\)\.value = "([^"]+)"', resp.text)
        session_id = match.group(1)

        # Toggle
        client.post("/web/cart/toggle/p1", data={"session_id": session_id})

        events = db.get_session_events(session_id)
        toggle_events = [e for e in events if e["event_type"] == "proposal_toggled"]
        assert len(toggle_events) == 1
        assert "p1" in toggle_events[0]["message"]
        assert "unchecked" in toggle_events[0]["message"]
