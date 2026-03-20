# ABOUTME: Script to check which of the 25 failed datasets are actually available on ABS TableBuilder.
# ABOUTME: Logs in, lists all datasets, and compares against the failed list from progress.json.

import json
from pathlib import Path

from tablebuilder.browser import TableBuilderSession
from tablebuilder.config import load_config
from tablebuilder.navigator import list_datasets
from tablebuilder.tree_extractor import DEFAULT_PROGRESS_PATH


def main():
    progress = json.loads(DEFAULT_PROGRESS_PATH.read_text())
    failed_names = list(progress["failed"].keys())
    print(f"Failed datasets to check: {len(failed_names)}")
    for name in failed_names:
        print(f"  - {name}")
    print()

    config = load_config()
    with TableBuilderSession(config, headless=False) as page:
        print("Logged in. Listing all available datasets...")
        available = list_datasets(page)
        print(f"Found {len(available)} datasets on site.")
        print()

        # Check which failed datasets are available now
        found = []
        not_found = []
        for name in failed_names:
            name_lower = name.lower()
            # Try exact match first
            if name in available:
                found.append((name, name))
                continue
            # Try substring match
            matches = [a for a in available if name_lower in a.lower()]
            if matches:
                found.append((name, matches[0]))
                continue
            # Try partial word match
            words = name_lower.split()
            partial = [a for a in available if all(w in a.lower() for w in words[:3])]
            if partial:
                found.append((name, partial[0]))
                continue
            not_found.append(name)

        print(f"=== AVAILABLE ({len(found)}) ===")
        for orig, match in found:
            if orig == match:
                print(f"  EXACT: {orig}")
            else:
                print(f"  FUZZY: {orig}")
                print(f"      -> {match}")

        print(f"\n=== NOT FOUND ({len(not_found)}) ===")
        for name in not_found:
            print(f"  {name}")

        # Also check for Census datasets (were excluded before)
        census = [a for a in available if "Census" in a]
        cached = [p.stem.replace("_", " ") for p in Path.home().joinpath(".tablebuilder/dict_cache").glob("*.json")]
        print(f"\n=== CENSUS DATASETS ({len(census)}) ===")
        for name in census:
            status = "CACHED" if any(name.replace(" ", "_").replace("/", "_") == c.replace(" ", "_") for c in cached) else "MISSING"
            print(f"  [{status}] {name}")

        # Show all available datasets not in our cache
        cache_dir = Path.home() / ".tablebuilder" / "dict_cache"
        cached_names = set()
        for p in cache_dir.glob("*.json"):
            data = json.loads(p.read_text())
            cached_names.add(data.get("dataset_name", ""))

        uncached = [a for a in available if a not in cached_names]
        print(f"\n=== ALL UNCACHED DATASETS ({len(uncached)}) ===")
        for name in uncached:
            print(f"  {name}")


if __name__ == "__main__":
    main()
