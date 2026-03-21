# ABOUTME: Batch fetch script that resolves natural language queries and downloads CSVs.
# ABOUTME: Uses ChatResolver to translate queries, then fetches via browser automation.

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tablebuilder.service.chat_resolver import ChatResolver
from tablebuilder.dictionary_db import DEFAULT_DB_PATH
from tablebuilder.config import load_config
from tablebuilder.browser import TableBuilderSession
from tablebuilder.navigator import open_dataset
from tablebuilder.table_builder import build_table
from tablebuilder.downloader import queue_and_download
from tablebuilder.models import TableRequest
from tablebuilder.knowledge import KnowledgeBase
from tablebuilder.logging_config import setup_logging


QUERIES = [
    "population by remoteness area 2021",
    "employment by industry 2021",
    "housing tenure by state 2021",
    "age by sex 2021",
    "country of birth by language",
    "income by occupation 2021",
    "disability in Australia",
    "age and sex by marital status 2021 census",
    "occupation and industry by income 2021",
    "indigenous status and age by sex, census 2021",
    "age by sex with indigenous status as layers, 2021 census",
    "marital status by sex layered by state 2021 census",
    "I want age in rows, sex in columns, and marital status as wafer layers from the 2021 census",
    "show me hours worked by occupation with income as layers, census 2021",
    "education level by employment status from education and work 2024",
    "remoteness area by household income from the general social survey 2014",
    "labour force status by sex from the labour force survey",
    "I want to see how many people work in different industries broken down by their age group and sex from the 2021 census",
    "Can you get me a cross tabulation of occupation against income for the most recent census?",
    "break down the population by how they get to work and which state they live in from the 2021 census",
]


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


def _slugify(text: str) -> str:
    """Convert a query string to a filename-safe slug."""
    slug = re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')
    return slug[:80]


def main():
    setup_logging(verbose=True)
    api_key = _get_api_key()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not found")
        sys.exit(1)

    if not DEFAULT_DB_PATH.exists():
        print(f"ERROR: Dictionary DB not found at {DEFAULT_DB_PATH}")
        sys.exit(1)

    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)

    results_file = output_dir / "batch_results.json"
    resolver = ChatResolver(anthropic_api_key=api_key)
    config = load_config()
    knowledge = KnowledgeBase()
    results = []

    print(f"\n{'='*70}")
    print(f"BATCH FETCH: {len(QUERIES)} queries")
    print(f"Output dir: {output_dir}")
    print(f"{'='*70}\n")

    for i, query in enumerate(QUERIES, 1):
        print(f"\n[{i}/{len(QUERIES)}] Resolving: {query}")
        slug = _slugify(query)
        csv_path = output_dir / f"{i:02d}_{slug}.csv"
        entry = {
            "query": query,
            "index": i,
            "csv_path": str(csv_path),
            "status": "pending",
        }

        # Step 1: Resolve via ChatResolver
        try:
            resolved = resolver.resolve(query)
        except Exception as e:
            entry["status"] = "resolve_error"
            entry["error"] = str(e)
            results.append(entry)
            print(f"  RESOLVE ERROR: {e}")
            continue

        if "clarification" in resolved:
            entry["status"] = "clarification"
            entry["clarification"] = resolved["clarification"]
            results.append(entry)
            print(f"  CLARIFICATION: {resolved['clarification'][:100]}")
            continue

        entry["resolved"] = resolved
        dataset = resolved.get("dataset", "")
        rows = resolved.get("rows", [])
        cols = resolved.get("cols", [])
        wafers = resolved.get("wafers", [])
        print(f"  Dataset: {dataset}")
        print(f"  Rows: {rows}")
        print(f"  Cols: {cols}")
        if wafers:
            print(f"  Wafers: {wafers}")

        # Step 2: Fetch via browser automation
        try:
            request = TableRequest(
                dataset=dataset,
                rows=rows,
                cols=cols,
                wafers=wafers,
            )
        except ValueError as e:
            entry["status"] = "invalid_request"
            entry["error"] = str(e)
            results.append(entry)
            print(f"  INVALID REQUEST: {e}")
            continue

        try:
            start = time.time()
            with TableBuilderSession(config, headless=True, knowledge=knowledge) as page:
                open_dataset(page, request.dataset, knowledge)
                build_table(page, request, knowledge)
                queue_and_download(page, str(csv_path), knowledge=knowledge)

            duration = time.time() - start
            entry["status"] = "success"
            entry["duration_seconds"] = round(duration, 1)
            entry["csv_size"] = csv_path.stat().st_size if csv_path.exists() else 0
            print(f"  SUCCESS: {csv_path.name} ({duration:.0f}s, {entry['csv_size']} bytes)")

        except Exception as e:
            entry["status"] = "fetch_error"
            entry["error"] = str(e)
            print(f"  FETCH ERROR: {e}")

        results.append(entry)

        # Save incremental results
        results_file.write_text(json.dumps(results, indent=2))

    # Final summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    success = sum(1 for r in results if r["status"] == "success")
    clarify = sum(1 for r in results if r["status"] == "clarification")
    errors = sum(1 for r in results if "error" in r.get("status", ""))
    print(f"  Success:        {success}/{len(QUERIES)}")
    print(f"  Clarification:  {clarify}/{len(QUERIES)}")
    print(f"  Errors:         {errors}/{len(QUERIES)}")
    print(f"  Results: {results_file}")


if __name__ == "__main__":
    main()
