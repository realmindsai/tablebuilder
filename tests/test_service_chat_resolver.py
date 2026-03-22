# ABOUTME: Tests for the Claude API chat resolver.
# ABOUTME: Validates NL -> TableRequest resolution using mocked Claude responses.

from unittest.mock import MagicMock, patch

import pytest

from tablebuilder.service.chat_resolver import ChatResolver


class TestChatResolver:
    @patch("tablebuilder.service.chat_resolver.anthropic.Anthropic")
    def test_resolve_returns_interpretation(self, mock_anthropic_class):
        """Resolver returns an interpretation dict with dataset and variables."""
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [
            MagicMock(
                type="text",
                text='{"dataset": "Census 2021", "rows": ["SEXP Sex"], "cols": [], "wafers": [], "confirmation": "I found Census 2021 with variable SEXP Sex. Shall I fetch this?"}',
            )
        ]
        mock_client.messages.create.return_value = mock_response

        resolver = ChatResolver(anthropic_api_key="test-key")
        result = resolver.resolve("population by sex from 2021 census")
        assert "dataset" in result or "confirmation" in result

    def test_build_system_prompt_has_persona(self):
        """System prompt establishes the data scientist persona."""
        resolver = ChatResolver(anthropic_api_key="test-key")
        prompt = resolver._build_system_prompt()
        assert "senior" in prompt.lower() or "research data scientist" in prompt.lower()
        assert "ABS" in prompt or "Australian Bureau of Statistics" in prompt
        assert "respond with ONLY a JSON" not in prompt
        assert "respond with ONLY:" not in prompt
