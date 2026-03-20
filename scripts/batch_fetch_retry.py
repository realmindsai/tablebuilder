# ABOUTME: Retry script for the 5 previously-failing batch fetch queries.
# ABOUTME: Tests bug fixes for category walking, context destruction, fuzzy matching, and stale handles.

import json
import os
import re
import sys
import time
from pathlib import Path

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


RETRY_QUERIES = [
    (14, "show me hours worked by occupation with income as layers, census 2021"),
    (18, "I want to see how many people work in different industries broken down by their age group and sex from the 2021 census"),
    (20, "break down the population by how they get to work and which state they live in from the 2021 census"),
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
    config = load_config()
    knowledge = KnowledgeBase()
    resolver = ChatResolver(anthropic_api_key=api_key)

    output_dir = Path(__file__).parent.parent / "output" / "retry"
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    print(f"\n{'='*70}")
    print(f"RETRY BATCH: {len(RETRY_QUERIES)} previously-failing queries")
    print(f"{'='*70}\n")

    for idx, query in RETRY_QUERIES:
        print(f"\n[{idx}] Resolving: {query}")
        slug = _slugify(query)
        csv_path = output_dir / f"{idx:02d}_{slug}.csv"
        entry = {"index": idx, "query": query, "status": "pending"}

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

        try:
            request = TableRequest(dataset=dataset, rows=rows, cols=cols, wafers=wafers)
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
        (output_dir / "retry_results.json").write_text(json.dumps(results, indent=2))

    print(f"\n{'='*70}")
    s = sum(1 for r in results if r["status"] == "success")
    e = sum(1 for r in results if "error" in r.get("status", ""))
    c = sum(1 for r in results if r["status"] == "clarification")
    print(f"RETRY RESULTS: Success: {s}/{len(RETRY_QUERIES)} | Errors: {e} | Clarify: {c}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
