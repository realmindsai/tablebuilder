# ABOUTME: Tests for the Claude API chat resolver.
# ABOUTME: Validates NL -> TableRequest resolution using mocked Claude responses.

from unittest.mock import MagicMock, patch

import pytest

from tablebuilder.service.chat_resolver import ChatResolver


class TestChatResolver:
    @patch("tablebuilder.service.chat_resolver.anthropic.Anthropic")
    def test_resolve_returns_interpretation(self, mock_anthropic_class):
        """Resolver returns a response dict with text key."""
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [
            MagicMock(type="text", text="I found Census 2021 with variable SEXP Sex.")
        ]
        mock_client.messages.create.return_value = mock_response

        resolver = ChatResolver(anthropic_api_key="test-key")
        result = resolver.resolve("population by sex from 2021 census")
        assert "text" in result

    @patch("tablebuilder.service.chat_resolver.anthropic.Anthropic")
    def test_resolve_returns_text_and_payloads(self, mock_anthropic_class):
        """Resolver returns dict with 'text' and 'display_payloads' keys."""
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_text = MagicMock(type="text", text="I found some interesting data for you.")
        mock_response.content = [mock_text]
        mock_client.messages.create.return_value = mock_response

        resolver = ChatResolver(anthropic_api_key="test-key")
        result = resolver.resolve("population by sex")
        assert "text" in result
        assert "display_payloads" in result
        assert isinstance(result["display_payloads"], list)
        assert result["text"] == "I found some interesting data for you."

    def test_build_system_prompt_has_persona(self):
        """System prompt establishes the data scientist persona."""
        resolver = ChatResolver(anthropic_api_key="test-key")
        prompt = resolver._build_system_prompt()
        assert "senior" in prompt.lower() or "research data scientist" in prompt.lower()
        assert "ABS" in prompt or "Australian Bureau of Statistics" in prompt
        assert "respond with ONLY a JSON" not in prompt
        assert "respond with ONLY:" not in prompt


class TestChatResolverTools:
    def test_tools_include_all_six(self):
        """Resolver has 6 tools: 3 research + 3 display."""
        from tablebuilder.service.chat_resolver import TOOLS
        tool_names = [t["name"] for t in TOOLS]
        assert "search_dictionary" in tool_names
        assert "get_dataset_variables" in tool_names
        assert "compare_datasets" in tool_names
        assert "propose_table_request" in tool_names
        assert "present_choices" in tool_names
        assert "show_session_summary" in tool_names

    def test_handle_propose_table_request(self):
        """propose_table_request tool stores proposal and returns confirmation."""
        resolver = ChatResolver(anthropic_api_key="test-key")
        result = resolver._handle_tool_call("propose_table_request", {
            "dataset": "Census 2021",
            "rows": ["SEXP Sex"],
            "cols": [],
            "wafers": [],
            "match_confidence": 85,
            "clarity_confidence": 70,
            "rationale": "Good match for sex demographics",
        })
        assert "Proposal" in result
        assert len(resolver._display_payloads) == 1
        assert resolver._display_payloads[0]["type"] == "proposal"

    def test_handle_present_choices(self):
        """present_choices tool stores choices and returns confirmation."""
        resolver = ChatResolver(anthropic_api_key="test-key")
        resolver._display_payloads = []
        result = resolver._handle_tool_call("present_choices", {
            "question": "Which geographic level?",
            "options": [
                {"label": "SA2", "description": "Suburbs"},
                {"label": "SA3", "description": "Regional"},
            ],
            "allow_multiple": False,
        })
        assert "Choices presented" in result
        assert len(resolver._display_payloads) == 1
        assert resolver._display_payloads[0]["type"] == "choices"
