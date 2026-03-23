# ABOUTME: Claude API integration for resolving natural language into TableRequests.
# ABOUTME: Uses tool-use to search the dictionary DB and build structured requests.

import json

import anthropic

from tablebuilder.dictionary_db import DEFAULT_DB_PATH, search, get_dataset, compare_datasets
from tablebuilder.logging_config import get_logger

logger = get_logger("tablebuilder.service.chat_resolver")

SYSTEM_PROMPT = """You are a senior research data scientist with deep expertise in Australian Bureau of Statistics census and survey data. You've spent years working with the 96 datasets in ABS TableBuilder — you know the variables, the quirks, the gaps.

A researcher has come to you for help. Your job is to understand their research question and help them get the exact data they need. You're collegial, curious, and opinionated when it matters.

You have tools to search and explore the ABS data dictionary. Use them proactively — when a researcher mentions a topic, search for it immediately.

PROPOSING DATA:
When you find relevant data, use the propose_table_request tool. Include confidence scores:
- match_confidence (0-100): how well the variables cover what they're asking about
- clarity_confidence (0-100): has the researcher been specific enough?

You MUST NOT propose until clarity_confidence is at least 70.

CRITICAL — VARIABLE RULES:
- Variable labels MUST EXACTLY match the labels from the dictionary search results. Copy-paste them.
- Geography (state, region, city) is NOT a variable — it is selected separately in TableBuilder. NEVER put geographic names like "Victoria", "Melbourne", "NSW" as row/col/wafer variables. If the researcher wants a geographic filter, note it in the rationale but do not include it in the variable lists.
- Keep tables simple. Prefer ONE outcome variable with ONE or TWO cross-tabulation variables. Each additional variable multiplies cell count and shrinks cell sizes.

CELL SIZE AWARENESS:
You understand survey methodology. ABS survey data (not Census) has limited sample sizes. When a researcher asks about a small subpopulation (e.g., LGBTQ+ people in one city), warn them proactively:
- Cross-tabulating a rare group by many variables produces tiny cell counts that ABS will suppress.
- Suggest pairwise comparisons: e.g., "Sexual orientation × Self-assessed health" as one table, "Sexual orientation × Age" as another — not all three at once.
- Suggest comparing the subpopulation against the general population for context.
- For rare subpopulations, national-level data may be more useful than state/city because of sample size.

CONVERSATION RULES:
- Ask ONE question at a time.
- Just talk naturally. No bullet-point lists of options. Just ask a question.
- Keep responses to 2-3 sentences. Get to the point.
- Be transparent about trade-offs (cell size, geographic granularity, variable coverage).

When the researcher asks for a summary of the session, use show_session_summary.

Stay focused on data. If the conversation drifts off-topic, steer it back.
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
                "title": {"type": "string", "description": "Short descriptive title for this table, e.g. 'Health status by sexual orientation' or 'Income by age and sex'"},
                "dataset": {"type": "string", "description": "Exact dataset name"},
                "rows": {"type": "array", "items": {"type": "string"}, "description": "Variable labels for row axis"},
                "cols": {"type": "array", "items": {"type": "string"}, "description": "Variable labels for column axis"},
                "wafers": {"type": "array", "items": {"type": "string"}, "description": "Variable labels for wafer (layer) axis"},
                "match_confidence": {"type": "integer", "description": "0-100: how well this dataset covers the research question"},
                "clarity_confidence": {"type": "integer", "description": "0-100: how clearly the researcher has specified what they need"},
                "rationale": {"type": "string", "description": "One sentence: why this table answers the research question"},
            },
            "required": ["title", "dataset", "rows", "match_confidence", "clarity_confidence", "rationale"],
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
            # Normalize string inputs to lists (Claude sometimes passes a string)
            for axis in ("rows", "cols", "wafers"):
                val = tool_input.get(axis, [])
                if isinstance(val, str):
                    tool_input[axis] = [v.strip() for v in val.split(",") if v.strip()]
                elif not isinstance(val, list):
                    tool_input[axis] = []

            # Validate variables exist in the dataset before accepting
            dataset_name = tool_input["dataset"]
            all_vars = tool_input.get("rows", []) + tool_input.get("cols", []) + tool_input.get("wafers", [])
            if DEFAULT_DB_PATH.exists() and all_vars:
                ds = get_dataset(DEFAULT_DB_PATH, dataset_name)
                if ds is None:
                    return f"ERROR: Dataset '{dataset_name}' not found in dictionary. Use search_dictionary to find the exact name."
                # Build set of valid variable labels for this dataset
                valid_labels = set()
                for group in ds.get("groups", []):
                    for var in group.get("variables", []):
                        valid_labels.add(var["label"])
                        if var.get("code"):
                            valid_labels.add(f"{var['code']} {var['label']}")
                invalid = [v for v in all_vars if v not in valid_labels]
                if invalid:
                    sample_vars = sorted(valid_labels)[:20]
                    return (
                        f"ERROR: These are not valid variable labels for '{dataset_name}': {invalid}. "
                        f"You may be confusing category values (like '20-24 years') with variable names (like 'Age in Five Year Groups'). "
                        f"Geographic names like 'Victoria' are also not variables — geography is selected separately. "
                        f"Valid variable labels include: {sample_vars}. "
                        f"Use get_dataset_variables to see all variables for this dataset."
                    )
            # Reject proposals with too many variables
            total_vars = len(tool_input.get("rows", [])) + len(tool_input.get("cols", [])) + len(tool_input.get("wafers", []))
            if total_vars > 4:
                return (
                    f"ERROR: Too many variables ({total_vars}). Each additional variable multiplies cell count. "
                    f"Use at most 2-3 variables per table. Propose multiple simpler tables instead."
                )

            proposal_id = f"p{len(self._display_payloads) + 1}"
            proposal = {
                "id": proposal_id,
                "title": tool_input.get("title", ""),
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
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
        session_id: str | None = None,
        db=None,
        cart_context: str = "",
    ) -> dict:
        """Resolve a natural language query.

        Returns a dict with:
            text: Claude's natural language response
            display_payloads: list of display objects for the UI
            messages: the full conversation history (for persistence)
        """
        self._display_payloads = []
        self._session_id = session_id
        self._db = db

        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": user_message})

        system_prompt = self._build_system_prompt()
        if cart_context:
            system_prompt += f"\n\nCurrent data cart:\n{cart_context}"

        for round_num in range(25):
            try:
                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=system_prompt,
                    tools=TOOLS,
                    messages=messages,
                )
            except Exception as e:
                logger.error("Claude API error: %s", e)
                return {"text": f"Sorry, I encountered an error: {e}", "display_payloads": [], "messages": messages}

            logger.info("Round %d: stop_reason=%s, content_types=%s", round_num + 1, response.stop_reason, [b.type for b in response.content])

            # Serialize response content for history
            content_dicts = []
            for block in response.content:
                if block.type == "text":
                    content_dicts.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    content_dicts.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if tool_use_blocks:
                messages.append({"role": "assistant", "content": content_dicts})
                tool_results = []
                for block in tool_use_blocks:
                    logger.info("Tool call: %s(%s)", block.name, json.dumps(block.input)[:200])
                    result = self._handle_tool_call(block.name, block.input)
                    logger.info("Tool result: %s chars", len(result))
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
                messages.append({"role": "user", "content": tool_results})
                continue

            text_blocks = [b for b in response.content if b.type == "text"]
            if text_blocks:
                text = text_blocks[0].text
                logger.info("Text response: %s", text[:200])
                messages.append({"role": "assistant", "content": content_dicts})
                return {"text": text, "display_payloads": self._display_payloads, "messages": messages}

        return {"text": "I wasn't able to fully process your request. Could you be more specific?", "display_payloads": self._display_payloads, "messages": messages}
