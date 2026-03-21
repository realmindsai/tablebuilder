# ABOUTME: Local JSON knowledge base that accumulates learnings across runs.
# ABOUTME: Records selector successes/failures, timing patterns, and dataset quirks.

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

def _resolve_knowledge_path() -> Path:
    """Resolve knowledge file path: TABLEBUILDER_DATA_DIR env > ./data/ > ~/.tablebuilder/."""
    import os
    if env_dir := os.environ.get("TABLEBUILDER_DATA_DIR"):
        return Path(env_dir) / "knowledge.json"
    local = Path.cwd() / "data" / "knowledge.json"
    if local.exists():
        return local
    return Path.home() / ".tablebuilder" / "knowledge.json"


KNOWLEDGE_PATH = _resolve_knowledge_path()


class KnowledgeBase:
    """Persistent knowledge base that learns from each scraping run.

    Stores selector preferences, operation timings, and dataset quirks
    in a local JSON file so that future runs benefit from past experience.
    """

    def __init__(self, path: Path = KNOWLEDGE_PATH):
        self.path = path
        self.selectors: dict[str, dict] = {}
        self.timings: dict[str, dict] = {}
        self.dataset_quirks: list[dict] = []
        self.run_count: int = 0
        self.last_run: str | None = None
        self._load()

    def _load(self) -> None:
        """Load from disk. If file missing or corrupt JSON, start fresh."""
        if not self.path.exists():
            return

        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            logger.warning(
                "Corrupt knowledge file at %s, starting fresh", self.path
            )
            return

        self.selectors = data.get("selectors", {})
        self.timings = data.get("timings", {})
        self.dataset_quirks = data.get("dataset_quirks", [])
        self.run_count = data.get("run_count", 0)
        self.last_run = data.get("last_run", None)

    def save(self) -> None:
        """Persist to disk as JSON. Creates parent directory if needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "run_count": self.run_count,
            "last_run": self.last_run,
            "selectors": self.selectors,
            "timings": self.timings,
            "dataset_quirks": self.dataset_quirks,
        }
        self.path.write_text(json.dumps(data, indent=2))

    # -- Selector methods --

    def record_selector_success(self, name: str, working_selector: str) -> None:
        """Record that a selector worked. Increments success_count, updates last_success."""
        entry = self.selectors.setdefault(
            name,
            {
                "working_selector": None,
                "last_success": None,
                "success_count": 0,
                "failed_selectors": [],
            },
        )
        entry["working_selector"] = working_selector
        entry["last_success"] = datetime.now().isoformat()
        entry["success_count"] += 1

    def record_selector_failure(self, name: str, failed_selector: str) -> None:
        """Record that a selector failed. Appends to failed_selectors list (deduped)."""
        entry = self.selectors.setdefault(
            name,
            {
                "working_selector": None,
                "last_success": None,
                "success_count": 0,
                "failed_selectors": [],
            },
        )
        if failed_selector not in entry["failed_selectors"]:
            entry["failed_selectors"].append(failed_selector)

    def get_preferred_selector(self, name: str) -> str | None:
        """Get the most recently successful selector for this element. Returns None if unknown."""
        entry = self.selectors.get(name)
        if entry is None:
            return None
        return entry.get("working_selector")

    # -- Timing methods --

    def record_timing(self, operation: str, duration_seconds: float) -> None:
        """Record operation duration. Computes running average."""
        entry = self.timings.get(operation)
        if entry is None:
            self.timings[operation] = {
                "avg_duration": duration_seconds,
                "last_duration": duration_seconds,
                "sample_count": 1,
            }
        else:
            n = entry["sample_count"] + 1
            old_avg = entry["avg_duration"]
            new_avg = (old_avg * (n - 1) + duration_seconds) / n
            entry["avg_duration"] = new_avg
            entry["last_duration"] = duration_seconds
            entry["sample_count"] = n

    def get_expected_timing(self, operation: str) -> float | None:
        """Get the average duration for an operation. Returns None if no data."""
        entry = self.timings.get(operation)
        if entry is None:
            return None
        return entry["avg_duration"]

    # -- Dataset quirk methods --

    def record_dataset_quirk(
        self, dataset_name: str, quirk_type: str, description: str
    ) -> None:
        """Record a dataset-specific quirk. Dedupes by (dataset_name, quirk_type)."""
        for quirk in self.dataset_quirks:
            if (
                quirk["dataset_name"] == dataset_name
                and quirk["quirk_type"] == quirk_type
            ):
                quirk["description"] = description
                quirk["last_seen"] = datetime.now().isoformat()
                return

        self.dataset_quirks.append(
            {
                "dataset_name": dataset_name,
                "quirk_type": quirk_type,
                "description": description,
                "last_seen": datetime.now().isoformat(),
            }
        )

    def get_dataset_quirks(self, dataset_name: str) -> list[dict]:
        """Get all known quirks for a dataset."""
        return [
            q for q in self.dataset_quirks if q["dataset_name"] == dataset_name
        ]

    # -- Run tracking --

    def record_run(self) -> None:
        """Increment run counter and set last_run to now."""
        self.run_count += 1
        self.last_run = datetime.now().isoformat()

    def summary(self) -> dict:
        """Return a summary dict with run_count, last_run, selector_count, quirk_count,
        and selectors_using_fallback (count of selectors that have a working_selector set)."""
        selectors_using_fallback = sum(
            1
            for entry in self.selectors.values()
            if entry.get("working_selector") is not None
        )
        return {
            "run_count": self.run_count,
            "last_run": self.last_run,
            "selector_count": len(self.selectors),
            "quirk_count": len(self.dataset_quirks),
            "selectors_using_fallback": selectors_using_fallback,
        }
