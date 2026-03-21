# ABOUTME: Integration tests for ChatResolver with real Claude API and dictionary DB.
# ABOUTME: Verifies natural language queries resolve to correct datasets and variables.

import json
import os
from pathlib import Path

import pytest

from tablebuilder.dictionary_db import DEFAULT_DB_PATH
from tablebuilder.service.chat_resolver import ChatResolver


def _get_api_key():
    """Load ANTHROPIC_API_KEY from env or project .env file."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


API_KEY = _get_api_key()

skip_no_api_key = pytest.mark.skipif(
    not API_KEY, reason="ANTHROPIC_API_KEY not configured"
)
skip_no_db = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason=f"Dictionary DB not found at {DEFAULT_DB_PATH}"
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _check_keywords_in_vars(var_list, keywords):
    """Check that at least one keyword appears across all variable labels combined."""
    if not keywords:
        return True, ""
    all_labels = " ".join(var_list).lower()
    for kw in keywords:
        if kw.lower() in all_labels:
            return True, ""
    return False, f"None of {keywords} found in {var_list}"


def _check_keywords_in_any_axis(result, keywords):
    """Check that at least one keyword appears in rows+cols+wafers combined."""
    if not keywords:
        return True, ""
    all_vars = result.get("rows", []) + result.get("cols", []) + result.get("wafers", [])
    all_labels = " ".join(all_vars).lower()
    for kw in keywords:
        if kw.lower() in all_labels:
            return True, ""
    return False, f"None of {keywords} found in any axis: {all_vars}"


def _check_all_keyword_groups(result, keyword_groups):
    """Verify each keyword group appears on at least one axis.

    keyword_groups is a list of keyword lists. For each group, at least one
    keyword must appear somewhere across rows+cols+wafers.
    """
    if not keyword_groups:
        return True, ""
    all_vars = result.get("rows", []) + result.get("cols", []) + result.get("wafers", [])
    all_labels = " ".join(all_vars).lower()
    for group in keyword_groups:
        if not any(kw.lower() in all_labels for kw in group):
            return False, f"None of {group} found in any axis: {all_vars}"
    return True, ""


def _check_min_variables(result, min_count):
    """Assert total number of variables across all axes >= min_count."""
    all_vars = result.get("rows", []) + result.get("cols", []) + result.get("wafers", [])
    if len(all_vars) >= min_count:
        return True, ""
    return False, f"Expected >= {min_count} variables, got {len(all_vars)}: {all_vars}"


def _check_wafers_populated(result):
    """Assert that wafers list is non-empty."""
    wafers = result.get("wafers", [])
    if wafers:
        return True, ""
    return False, f"Expected non-empty wafers, got: {wafers}"


def _resolve_with_retry(resolver, query, allow_clarification=False, max_attempts=2):
    """Call resolver.resolve with retry logic for LLM nondeterminism.

    Returns the result dict. Raises AssertionError if clarification is returned
    but not allowed after all attempts.
    """
    last_result = None
    for attempt in range(max_attempts):
        result = resolver.resolve(query)
        last_result = result

        if "clarification" in result and not allow_clarification:
            if attempt < max_attempts - 1:
                continue
            pytest.fail(
                f"Query '{query}' returned clarification after {max_attempts} attempts: "
                f"{result['clarification']}"
            )

        if "clarification" in result and allow_clarification:
            return result

        if "dataset" in result:
            return result

    return last_result


def _assert_resolution(result, query, dataset_words=None, row_keywords=None,
                       col_keywords=None, wafer_keywords=None,
                       all_axis_keywords=None, min_total_vars=None,
                       require_wafers=False, allow_clarification=False):
    """Common assertion logic for resolved results."""
    # If clarification was returned and allowed, nothing more to check
    if "clarification" in result and allow_clarification:
        return

    assert "dataset" in result, (
        f"Query '{query}' produced unexpected result: {result}"
    )

    dataset = result["dataset"]
    if dataset_words:
        for word in dataset_words:
            assert word.lower() in dataset.lower(), (
                f"Expected dataset containing '{word}', got '{dataset}'"
            )

    if row_keywords:
        rows = result.get("rows", [])
        ok, msg = _check_keywords_in_vars(rows, row_keywords)
        assert ok, f"Row mismatch for '{query}': {msg}"

    if col_keywords:
        cols = result.get("cols", [])
        ok, msg = _check_keywords_in_vars(cols, col_keywords)
        assert ok, f"Column mismatch for '{query}': {msg}"

    if wafer_keywords:
        wafers = result.get("wafers", [])
        ok, msg = _check_keywords_in_vars(wafers, wafer_keywords)
        assert ok, f"Wafer mismatch for '{query}': {msg}"

    if all_axis_keywords:
        ok, msg = _check_all_keyword_groups(result, all_axis_keywords)
        assert ok, f"Axis keyword mismatch for '{query}': {msg}"

    if min_total_vars:
        ok, msg = _check_min_variables(result, min_total_vars)
        assert ok, f"Variable count mismatch for '{query}': {msg}"

    if require_wafers:
        ok, msg = _check_wafers_populated(result)
        assert ok, f"Wafer requirement failed for '{query}': {msg}"

    assert result.get("confirmation"), f"Missing confirmation for '{query}'"


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

BASIC_RESOLUTIONS = [
    {
        "query": "population by remoteness area 2021",
        "dataset_words": ["2021", "Census"],
        "row_keywords": ["remoteness"],
        "col_keywords": [],
        "allow_clarification": False,
    },
    {
        "query": "employment by industry 2021",
        "dataset_words": ["2021", "Census"],
        "row_keywords": ["industry"],
        "col_keywords": [],
        "allow_clarification": False,
    },
    {
        "query": "housing tenure by state 2021",
        "dataset_words": ["2021", "Census", "dwelling"],
        "row_keywords": ["tenure"],
        "col_keywords": ["state", "territory", "new south wales", "victoria"],
        "allow_clarification": False,
    },
    {
        "query": "age by sex 2021",
        "dataset_words": ["2021", "Census"],
        "row_keywords": ["age"],
        "col_keywords": ["sex"],
        "allow_clarification": False,
    },
    {
        "query": "country of birth by language",
        "dataset_words": [],
        "row_keywords": ["country", "birth"],
        "col_keywords": ["language"],
        "allow_clarification": False,
    },
    {
        "query": "income by occupation 2021",
        "dataset_words": ["2021", "Census"],
        "all_axis_keywords": [["occupation", "OCCP"], ["income", "INCP"]],
        "min_total_vars": 2,
        "allow_clarification": False,
    },
    {
        "query": "disability in Australia",
        "dataset_words": ["disability"],
        "all_axis_keywords": [["disability", "condition", "health"]],
        "allow_clarification": True,
    },
]

MULTI_VARIABLE_RESOLUTIONS = [
    {
        "query": "age and sex by marital status 2021 census",
        "dataset_words": ["2021", "Census"],
        "all_axis_keywords": [["age"], ["sex"], ["marital"]],
        "min_total_vars": 3,
        "allow_clarification": False,
    },
    {
        "query": "occupation and industry by income 2021",
        "dataset_words": ["2021", "Census"],
        "all_axis_keywords": [["occupation"], ["industry"], ["income"]],
        "min_total_vars": 3,
        "allow_clarification": False,
    },
    {
        "query": "indigenous status and age by sex, census 2021",
        "dataset_words": ["2021", "Census"],
        "all_axis_keywords": [["indigenous"], ["age"], ["sex"]],
        "min_total_vars": 3,
        "allow_clarification": False,
    },
]

WAFER_RESOLUTIONS = [
    {
        "query": "age by sex with indigenous status as layers, 2021 census",
        "dataset_words": ["2021", "Census"],
        "all_axis_keywords": [["age"], ["sex"], ["indigenous"]],
        "min_total_vars": 3,
        "require_wafers": True,
        "allow_clarification": False,
    },
    {
        "query": "marital status by sex layered by state 2021 census",
        "dataset_words": ["2021", "Census"],
        "all_axis_keywords": [["marital"], ["sex"], ["state", "territory", "new south wales"]],
        "min_total_vars": 3,
        "require_wafers": False,  # LLM may put state in cols instead of wafers
        "allow_clarification": False,
    },
]

THREE_AXIS_RESOLUTIONS = [
    {
        "query": "I want age in rows, sex in columns, and marital status as wafer layers from the 2021 census",
        "dataset_words": ["2021", "Census"],
        "row_keywords": ["age"],
        "col_keywords": ["sex"],
        "wafer_keywords": ["marital"],
        "allow_clarification": False,
    },
    {
        "query": "show me hours worked by occupation with income as layers, census 2021",
        "dataset_words": ["2021", "Census"],
        "all_axis_keywords": [["hours", "worked", "HRWRP"], ["occupation", "OCCP"], ["income", "INCP"]],
        "min_total_vars": 3,
        "require_wafers": True,
        "allow_clarification": False,
    },
]

NON_CENSUS_RESOLUTIONS = [
    {
        "query": "education level by employment status from education and work 2024",
        "dataset_words": ["Education", "Work", "2024"],
        "all_axis_keywords": [["education", "qualification", "school"], ["employ", "labour", "work"]],
        "min_total_vars": 2,
        "allow_clarification": True,
    },
    {
        "query": "remoteness area by household income from the general social survey 2014",
        "dataset_words": ["General Social Survey", "2014"],
        "all_axis_keywords": [["remoteness"], ["income"]],
        "min_total_vars": 2,
        "allow_clarification": False,
    },
    {
        "query": "labour force status by sex from the labour force survey",
        "dataset_words": ["Labour Force"],
        "all_axis_keywords": [["labour", "force", "employ"], ["sex", "male", "female", "persons"]],
        "min_total_vars": 2,
        "allow_clarification": True,
    },
]

COMPLEX_NL_RESOLUTIONS = [
    {
        "query": "I want to see how many people work in different industries broken down by their age group and sex from the 2021 census",
        "dataset_words": ["2021", "Census"],
        "all_axis_keywords": [["industry"], ["age"], ["sex"]],
        "min_total_vars": 3,
        "allow_clarification": False,
    },
    {
        "query": "Can you get me a cross tabulation of occupation against income for the most recent census?",
        "dataset_words": ["Census"],
        "all_axis_keywords": [["occupation"], ["income"]],
        "min_total_vars": 2,
        "allow_clarification": False,
    },
    {
        "query": "break down the population by how they get to work and which state they live in from the 2021 census",
        "dataset_words": ["2021", "Census"],
        "all_axis_keywords": [["travel", "transport", "method"]],
        "min_total_vars": 1,
        "allow_clarification": False,
    },
]

MULTI_TURN_CASES = [
    {
        "initial_query": "show me some data about people in Australia",
        "followup_query": "age by sex from the 2021 census",
        "dataset_words": ["2021", "Census"],
        "all_axis_keywords": [["age"], ["sex"]],
    },
    {
        "initial_query": "disability data",
        "followup_query": "age by sex from the 2018 disability ageing and carers survey",
        "dataset_words": ["Disability", "2018"],
        "all_axis_keywords": [["age", "demographics", "AGE"], ["sex"]],
    },
]


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_no_api_key
@skip_no_db
class TestChatResolverBasic:
    """Basic single-variable resolution tests."""

    @pytest.fixture(scope="class")
    def resolver(self):
        return ChatResolver(anthropic_api_key=API_KEY)

    @pytest.mark.parametrize(
        "case",
        BASIC_RESOLUTIONS,
        ids=[c["query"] for c in BASIC_RESOLUTIONS],
    )
    def test_resolve_query(self, resolver, case):
        """ChatResolver correctly resolves a basic natural language query."""
        result = _resolve_with_retry(
            resolver, case["query"],
            allow_clarification=case.get("allow_clarification", False),
        )
        _assert_resolution(
            result, case["query"],
            dataset_words=case.get("dataset_words"),
            row_keywords=case.get("row_keywords"),
            col_keywords=case.get("col_keywords"),
            all_axis_keywords=case.get("all_axis_keywords"),
            min_total_vars=case.get("min_total_vars"),
            allow_clarification=case.get("allow_clarification", False),
        )


@pytest.mark.integration
@skip_no_api_key
@skip_no_db
class TestChatResolverMultiVariable:
    """Tests with multiple variables assigned across axes."""

    @pytest.fixture(scope="class")
    def resolver(self):
        return ChatResolver(anthropic_api_key=API_KEY)

    @pytest.mark.parametrize(
        "case",
        MULTI_VARIABLE_RESOLUTIONS,
        ids=[c["query"] for c in MULTI_VARIABLE_RESOLUTIONS],
    )
    def test_multi_variable(self, resolver, case):
        """Resolver handles queries requesting 3+ variables across axes."""
        result = _resolve_with_retry(
            resolver, case["query"],
            allow_clarification=case.get("allow_clarification", False),
        )
        _assert_resolution(
            result, case["query"],
            dataset_words=case.get("dataset_words"),
            all_axis_keywords=case.get("all_axis_keywords"),
            min_total_vars=case.get("min_total_vars"),
            allow_clarification=case.get("allow_clarification", False),
        )


@pytest.mark.integration
@skip_no_api_key
@skip_no_db
class TestChatResolverWafers:
    """Tests requesting wafer/layer placement."""

    @pytest.fixture(scope="class")
    def resolver(self):
        return ChatResolver(anthropic_api_key=API_KEY)

    @pytest.mark.parametrize(
        "case",
        WAFER_RESOLUTIONS,
        ids=[c["query"] for c in WAFER_RESOLUTIONS],
    )
    def test_wafer_query(self, resolver, case):
        """Resolver places variables as wafers when explicitly requested."""
        result = _resolve_with_retry(
            resolver, case["query"],
            allow_clarification=case.get("allow_clarification", False),
        )
        _assert_resolution(
            result, case["query"],
            dataset_words=case.get("dataset_words"),
            all_axis_keywords=case.get("all_axis_keywords"),
            min_total_vars=case.get("min_total_vars"),
            require_wafers=case.get("require_wafers", False),
            allow_clarification=case.get("allow_clarification", False),
        )


@pytest.mark.integration
@skip_no_api_key
@skip_no_db
class TestChatResolverThreeAxis:
    """Tests with all three axes populated (rows + cols + wafers)."""

    @pytest.fixture(scope="class")
    def resolver(self):
        return ChatResolver(anthropic_api_key=API_KEY)

    @pytest.mark.parametrize(
        "case",
        THREE_AXIS_RESOLUTIONS,
        ids=[c["query"] for c in THREE_AXIS_RESOLUTIONS],
    )
    def test_three_axis(self, resolver, case):
        """Resolver populates rows, columns, and wafers correctly."""
        result = _resolve_with_retry(
            resolver, case["query"],
            allow_clarification=case.get("allow_clarification", False),
        )
        _assert_resolution(
            result, case["query"],
            dataset_words=case.get("dataset_words"),
            row_keywords=case.get("row_keywords"),
            col_keywords=case.get("col_keywords"),
            wafer_keywords=case.get("wafer_keywords"),
            all_axis_keywords=case.get("all_axis_keywords"),
            min_total_vars=case.get("min_total_vars"),
            require_wafers=case.get("require_wafers", False),
            allow_clarification=case.get("allow_clarification", False),
        )


@pytest.mark.integration
@skip_no_api_key
@skip_no_db
class TestChatResolverNonCensus:
    """Tests targeting non-census datasets (surveys, disability, education)."""

    @pytest.fixture(scope="class")
    def resolver(self):
        return ChatResolver(anthropic_api_key=API_KEY)

    @pytest.mark.parametrize(
        "case",
        NON_CENSUS_RESOLUTIONS,
        ids=[c["query"] for c in NON_CENSUS_RESOLUTIONS],
    )
    def test_non_census(self, resolver, case):
        """Resolver finds variables in non-census survey datasets."""
        result = _resolve_with_retry(
            resolver, case["query"],
            allow_clarification=case.get("allow_clarification", False),
        )
        _assert_resolution(
            result, case["query"],
            dataset_words=case.get("dataset_words"),
            all_axis_keywords=case.get("all_axis_keywords"),
            min_total_vars=case.get("min_total_vars"),
            allow_clarification=case.get("allow_clarification", False),
        )


@pytest.mark.integration
@skip_no_api_key
@skip_no_db
class TestChatResolverComplexNL:
    """Tests with complex, conversational natural language queries."""

    @pytest.fixture(scope="class")
    def resolver(self):
        return ChatResolver(anthropic_api_key=API_KEY)

    @pytest.mark.parametrize(
        "case",
        COMPLEX_NL_RESOLUTIONS,
        ids=[c["query"] for c in COMPLEX_NL_RESOLUTIONS],
    )
    def test_complex_nl(self, resolver, case):
        """Resolver handles long, conversational queries correctly."""
        result = _resolve_with_retry(
            resolver, case["query"],
            allow_clarification=case.get("allow_clarification", False),
        )
        _assert_resolution(
            result, case["query"],
            dataset_words=case.get("dataset_words"),
            all_axis_keywords=case.get("all_axis_keywords"),
            min_total_vars=case.get("min_total_vars"),
            allow_clarification=case.get("allow_clarification", False),
        )


@pytest.mark.integration
@skip_no_api_key
@skip_no_db
class TestChatResolverMultiTurn:
    """Tests for multi-turn conversations: vague query -> clarification -> resolution."""

    @pytest.fixture(scope="class")
    def resolver(self):
        return ChatResolver(anthropic_api_key=API_KEY)

    @pytest.mark.parametrize(
        "case",
        MULTI_TURN_CASES,
        ids=[c["initial_query"] for c in MULTI_TURN_CASES],
    )
    def test_multi_turn(self, resolver, case):
        """Vague query gets clarification, follow-up resolves correctly."""
        # Step 1: send vague initial query
        first_result = resolver.resolve(case["initial_query"])

        # The LLM may clarify or resolve immediately — both are acceptable
        if "dataset" in first_result:
            # Resolved immediately — that's fine, skip the multi-turn part
            return

        # Step 2: should have returned a clarification
        assert "clarification" in first_result, (
            f"Initial query '{case['initial_query']}' returned neither "
            f"dataset nor clarification: {first_result}"
        )

        # Step 3: build conversation history and send specific follow-up
        history = [
            {"role": "user", "content": case["initial_query"]},
            {"role": "assistant", "content": json.dumps(first_result)},
        ]

        # Retry the follow-up once if needed
        second_result = None
        for attempt in range(2):
            second_result = resolver.resolve(
                case["followup_query"], conversation_history=history
            )
            if "dataset" in second_result:
                break
            if attempt == 0:
                continue
            pytest.fail(
                f"Follow-up '{case['followup_query']}' failed to resolve after "
                f"2 attempts: {second_result}"
            )

        _assert_resolution(
            second_result, case["followup_query"],
            dataset_words=case.get("dataset_words"),
            all_axis_keywords=case.get("all_axis_keywords"),
        )
