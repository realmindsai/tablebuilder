# ABOUTME: Batch fetch 20 NL queries using the HTTP client for speed.
# ABOUTME: Uses ChatResolver for NL->TableRequest, then http_fetch_table for the actual fetch.

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tablebuilder.service.chat_resolver import ChatResolver
from tablebuilder.dictionary_db import DEFAULT_DB_PATH
from tablebuilder.config import load_config
from tablebuilder.http_session import TableBuilderHTTPSession
from tablebuilder.http_table import http_fetch_table
from tablebuilder.models import TableRequest
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
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def _slugify(text):
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')[:80]


def main():
    setup_logging(verbose=True)
    api_key = _get_api_key()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not found")
        sys.exit(1)
    if not DEFAULT_DB_PATH.exists():
        print(f"ERROR: Dictionary DB not found at {DEFAULT_DB_PATH}")
        sys.exit(1)

    config = load_config()
    resolver = ChatResolver(anthropic_api_key=api_key)
    output_dir = Path(__file__).parent.parent / "output" / "batch_http"
    output_dir.mkdir(parents=True, exist_ok=True)
    results_file = output_dir / "batch_results.json"
    results = []

    print(f"\n{'='*70}")
    print(f"BATCH FETCH (HTTP): {len(QUERIES)} queries")
    print(f"Output dir: {output_dir}")
    print(f"{'='*70}\n")

    for i, query in enumerate(QUERIES, 1):
        print(f"\n[{i}/{len(QUERIES)}] Resolving: {query}")
        slug = _slugify(query)
        csv_path = output_dir / f"{i:02d}_{slug}.csv"
        entry = {"query": query, "index": i, "csv_path": str(csv_path), "status": "pending"}

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
        print(f"  Rows: {rows}, Cols: {cols}, Wafers: {wafers}")

        # Step 2: Fetch via HTTP client
        try:
            request = TableRequest(dataset=dataset, rows=rows, cols=cols, wafers=wafers)
        except ValueError as e:
            entry["status"] = "invalid_request"
            entry["error"] = str(e)
            results.append(entry)
            print(f"  INVALID REQUEST: {e}")
            continue

        try:
            start = time.time()
            with TableBuilderHTTPSession(config) as session:
                http_fetch_table(session, request, str(csv_path))
            duration = time.time() - start
            entry["status"] = "success"
            entry["duration_seconds"] = round(duration, 1)
            entry["csv_size"] = csv_path.stat().st_size if csv_path.exists() else 0
            print(f"  SUCCESS: {csv_path.name} ({duration:.0f}s, {entry['csv_size']} bytes)")
        except Exception as e:
            entry["status"] = "fetch_error"
            entry["error"] = str(e)
            entry["duration_seconds"] = round(time.time() - start, 1)
            print(f"  FETCH ERROR: {e}")

        results.append(entry)
        results_file.write_text(json.dumps(results, indent=2))

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    success = sum(1 for r in results if r["status"] == "success")
    clarify = sum(1 for r in results if r["status"] == "clarification")
    errors = sum(1 for r in results if "error" in r.get("status", ""))
    total_time = sum(r.get("duration_seconds", 0) for r in results)
    print(f"  Success:        {success}/{len(QUERIES)}")
    print(f"  Clarification:  {clarify}/{len(QUERIES)}")
    print(f"  Errors:         {errors}/{len(QUERIES)}")
    print(f"  Total time:     {total_time:.0f}s ({total_time/60:.1f}m)")
    if success > 0:
        avg = total_time / success
        print(f"  Avg per table:  {avg:.0f}s")
    print(f"  Results: {results_file}")


if __name__ == "__main__":
    main()
