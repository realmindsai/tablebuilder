# ABOUTME: Claude API integration for resolving natural language into TableRequests.
# ABOUTME: Uses tool-use to search the dictionary DB and build structured requests.

import json

import anthropic

from tablebuilder.dictionary_db import DEFAULT_DB_PATH, search, get_dataset
from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.service.chat_resolver")

SYSTEM_PROMPT = """You are a data assistant for ABS TableBuilder. You help users find and request Australian Bureau of Statistics census data.

You have access to a dictionary of datasets and variables. Use the search_dictionary tool to find matching datasets and variables. Use get_dataset_variables to see the full variable tree for a specific dataset.

When the user asks for data, search the dictionary, identify the right dataset and variables, and propose a structured request. Always confirm with the user before they submit.

Respond with a JSON object containing:
- "dataset": the exact dataset name
- "rows": list of variable labels for rows (required, at least one)
- "cols": list of variable labels for columns (optional)
- "wafers": list of variable labels for wafers/layers (optional)
- "confirmation": a human-readable summary asking the user to confirm

If you need clarification (ambiguous dataset, multiple matches), ask a follow-up question instead of guessing. In that case, respond with:
- "clarification": the question to ask the user"""

TOOLS = [
    {
        "name": "search_dictionary",
        "description": "Search the ABS data dictionary for datasets and variables matching a query. Returns ranked results with dataset name, variable code, label, and categories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'population remoteness area')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_dataset_variables",
        "description": "Get the full variable tree for a specific dataset by exact name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_name": {
                    "type": "string",
                    "description": "Exact dataset name",
                },
            },
            "required": ["dataset_name"],
        },
    },
]


class ChatResolver:
    """Resolves natural language queries into TableRequests using Claude API."""

    def __init__(self, anthropic_api_key: str):
        self.api_key = anthropic_api_key
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _build_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return the result as a string."""
        if tool_name == "search_dictionary":
            if not DEFAULT_DB_PATH.exists():
                return json.dumps([])
            results = search(
                DEFAULT_DB_PATH,
                tool_input["query"],
                limit=tool_input.get("limit", 10),
            )
            return json.dumps(results)

        elif tool_name == "get_dataset_variables":
            if not DEFAULT_DB_PATH.exists():
                return json.dumps(None)
            result = get_dataset(DEFAULT_DB_PATH, tool_input["dataset_name"])
            return json.dumps(result)

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def resolve(
        self, user_message: str, conversation_history: list[dict] | None = None
    ) -> dict:
        """Resolve a natural language query. Returns a dict with either
        dataset/rows/cols/wafers/confirmation or clarification."""
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": user_message})

        for _ in range(5):
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=self._build_system_prompt(),
                tools=TOOLS,
                messages=messages,
            )

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if tool_use_blocks:
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in tool_use_blocks:
                    result = self._handle_tool_call(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            text_blocks = [b for b in response.content if b.type == "text"]
            if text_blocks:
                try:
                    return json.loads(text_blocks[0].text)
                except json.JSONDecodeError:
                    return {"clarification": text_blocks[0].text}

        return {"clarification": "I wasn't able to resolve your request. Could you be more specific?"}
