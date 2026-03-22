# ABOUTME: Claude API integration for resolving natural language into TableRequests.
# ABOUTME: Uses tool-use to search the dictionary DB and build structured requests.

import json

import anthropic

from tablebuilder.dictionary_db import DEFAULT_DB_PATH, search, get_dataset, compare_datasets
from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.service.chat_resolver")

SYSTEM_PROMPT = """You are a senior research data scientist with deep expertise in Australian Bureau of Statistics census and survey data. You've spent years working with the 96 datasets in ABS TableBuilder — you know the variables, the quirks, the gaps.

A researcher has come to you for help. Your job is to understand their research question and help them get the exact data they need. You're collegial, curious, and opinionated when it matters. You get excited when you spot a connection the researcher hasn't seen. You know when to suggest a better variable and when to just give them what they asked for.

You understand research methodology — you can advise on denominators, confounders, and geographic levels. You know that cross-tabulation needs compatible datasets and that geographic hierarchies matter.

You have tools to search and explore the ABS data dictionary. Use them proactively — when a researcher mentions a topic, search for it immediately. Show them what's available. Suggest combinations they might not have considered.

When you find relevant data, use the propose_table_request tool to add it to the researcher's data cart. Include your confidence assessment:
- match_confidence (0-100): how well the dataset's variables cover what the researcher is asking about
- clarity_confidence (0-100): has the researcher been specific enough that you're confident this data will answer their question?

If clarity_confidence would be below 70, ask a follow-up question before proposing. Use present_choices when a structured selection would be clearer than an open question (e.g., geographic levels, variable options).

When the researcher asks for a summary of the session, use show_session_summary.

Variable labels in proposals must EXACTLY match the labels from the dictionary. Do not modify or abbreviate them.

Stay focused on data. You're a data scientist in a consultation — if the conversation drifts off-topic, gently steer it back: "That's outside my wheelhouse — I'm here to help you find the right data. What are you working on?"
"""

TOOLS = [
    {
        "name": "search_dictionary",
        "description": "Search the ABS data dictionary for datasets and variables matching a query. Returns ranked results with dataset name, variable code, label, and categories. Use this proactively when the researcher mentions any data topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g., 'population remoteness area')"},
                "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_dataset_variables",
        "description": "Get the full variable tree for a specific dataset by exact name. Use to explore what variables and categories are available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_name": {"type": "string", "description": "Exact dataset name from search results"},
            },
            "required": ["dataset_name"],
        },
    },
    {
        "name": "compare_datasets",
        "description": "Compare 2-3 datasets side-by-side to see variable overlap and differences. Use when the researcher's question could be answered by multiple datasets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_names": {"type": "array", "items": {"type": "string"}, "description": "List of exact dataset names to compare"},
            },
            "required": ["dataset_names"],
        },
    },
    {
        "name": "propose_table_request",
        "description": "Propose a data table for the researcher's cart. This adds a card to their shopping cart with the dataset, variables, and your confidence assessment. The researcher can accept or reject it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Exact dataset name"},
                "rows": {"type": "array", "items": {"type": "string"}, "description": "Variable labels for row axis"},
                "cols": {"type": "array", "items": {"type": "string"}, "description": "Variable labels for column axis"},
                "wafers": {"type": "array", "items": {"type": "string"}, "description": "Variable labels for wafer (layer) axis"},
                "match_confidence": {"type": "integer", "description": "0-100: how well this dataset covers the research question"},
                "clarity_confidence": {"type": "integer", "description": "0-100: how clearly the researcher has specified what they need"},
                "rationale": {"type": "string", "description": "Brief explanation of why this dataset and these variables"},
            },
            "required": ["dataset", "rows", "match_confidence", "clarity_confidence", "rationale"],
        },
    },
    {
        "name": "present_choices",
        "description": "Show the researcher a structured multiple-choice question. Use this when a selection from a fixed set of options would be clearer than an open question.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask"},
                "options": {"type": "array", "items": {"type": "object", "properties": {"label": {"type": "string"}, "description": {"type": "string"}}, "required": ["label"]}, "description": "List of options to present"},
                "allow_multiple": {"type": "boolean", "description": "Whether multiple selections are allowed", "default": False},
            },
            "required": ["question", "options"],
        },
    },
    {
        "name": "show_session_summary",
        "description": "Generate a summary of this research session — datasets explored, variables selected, proposals made, and jobs queued.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


class ChatResolver:
    """Resolves natural language queries into TableRequests using Claude API."""

    def __init__(self, anthropic_api_key: str):
        self.api_key = anthropic_api_key
        self._client = None
        self._display_payloads: list = []
        self._session_id: str | None = None
        self._db = None

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _build_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Extract a JSON object from text, handling markdown code blocks."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting from ```json ... ``` code blocks
        import re
        match = re.search(r'```(?:json)?\s*\n?({.*?})\s*\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Try finding the first { ... } block
        brace_start = text.find('{')
        if brace_start >= 0:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start:i + 1])
                        except json.JSONDecodeError:
                            break
        return None

    def _handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return the result as a string."""
        if tool_name == "search_dictionary":
            if not DEFAULT_DB_PATH.exists():
                return json.dumps([])
            results = search(DEFAULT_DB_PATH, tool_input["query"], limit=tool_input.get("limit", 10))
            return json.dumps(results)

        elif tool_name == "get_dataset_variables":
            if not DEFAULT_DB_PATH.exists():
                return json.dumps(None)
            result = get_dataset(DEFAULT_DB_PATH, tool_input["dataset_name"])
            if result is None:
                return json.dumps(None)
            summary = {"name": result["name"], "geographies": result.get("geographies", []), "groups": []}
            for group in result.get("groups", []):
                g = {"path": group["path"], "variables": []}
                for var in group.get("variables", []):
                    cats = var.get("categories", [])
                    g["variables"].append({"code": var.get("code", ""), "label": var["label"], "category_count": len(cats), "sample_categories": cats[:5]})
                summary["groups"].append(g)
            return json.dumps(summary)

        elif tool_name == "compare_datasets":
            if not DEFAULT_DB_PATH.exists():
                return json.dumps([])
            result = compare_datasets(DEFAULT_DB_PATH, tool_input["dataset_names"])
            return json.dumps(result)

        elif tool_name == "propose_table_request":
            proposal_id = f"p{len(self._display_payloads) + 1}"
            proposal = {
                "id": proposal_id,
                "dataset": tool_input["dataset"],
                "rows": tool_input.get("rows", []),
                "cols": tool_input.get("cols", []),
                "wafers": tool_input.get("wafers", []),
                "match_confidence": tool_input["match_confidence"],
                "clarity_confidence": tool_input["clarity_confidence"],
                "rationale": tool_input["rationale"],
                "status": "checked",
                "job_id": None,
            }
            self._display_payloads.append({"type": "proposal", "data": proposal})
            return f"Proposal #{proposal_id} stored and shown to researcher."

        elif tool_name == "present_choices":
            choices = {
                "question": tool_input["question"],
                "options": tool_input["options"],
                "allow_multiple": tool_input.get("allow_multiple", False),
            }
            self._display_payloads.append({"type": "choices", "data": choices})
            return "Choices presented, waiting for researcher's selection."

        elif tool_name == "show_session_summary":
            events = []
            if self._db and self._session_id:
                events = self._db.get_session_events(self._session_id)
                proposals = self._db.get_proposals(self._session_id)
            else:
                proposals = []
            summary_data = {"events": events, "proposals": proposals}
            self._display_payloads.append({"type": "summary", "data": summary_data})
            return json.dumps(summary_data)

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def resolve(
        self, user_message: str, conversation_history: list[dict] | None = None
    ) -> dict:
        """Resolve a natural language query. Returns a dict with either
        dataset/rows/cols/wafers/confirmation or clarification."""
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": user_message})

        for round_num in range(10):
            try:
                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2048,
                    system=self._build_system_prompt(),
                    tools=TOOLS,
                    messages=messages,
                )
            except Exception as e:
                logger.error("Claude API error: %s", e)
                return {"clarification": f"Sorry, I encountered an error: {e}"}

            logger.info("Round %d: stop_reason=%s, content_types=%s",
                        round_num + 1, response.stop_reason,
                        [b.type for b in response.content])

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if tool_use_blocks:
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in tool_use_blocks:
                    logger.info("Tool call: %s(%s)", block.name, json.dumps(block.input)[:100])
                    result = self._handle_tool_call(block.name, block.input)
                    logger.info("Tool result: %s chars", len(result))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            text_blocks = [b for b in response.content if b.type == "text"]
            if text_blocks:
                text = text_blocks[0].text
                logger.info("Text response: %s", text[:200])
                parsed = self._extract_json(text)
                if parsed is not None:
                    return parsed
                return {"clarification": text}

        return {"clarification": "I wasn't able to resolve your request. Could you be more specific?"}
