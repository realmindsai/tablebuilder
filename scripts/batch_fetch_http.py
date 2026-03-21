# ABOUTME: Batch fetch 20 pre-resolved table requests using the HTTP client.
# ABOUTME: Each request is a dataset + variable combination, fetched via http_fetch_table.

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tablebuilder.config import load_config
from tablebuilder.http_session import TableBuilderHTTPSession
from tablebuilder.http_table import http_fetch_table
from tablebuilder.models import TableRequest
from tablebuilder.logging_config import setup_logging


# Pre-resolved table requests from previous ChatResolver batch run
REQUESTS = [
    {"name": "population_by_remoteness", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["Remoteness Areas (EN)"], "cols": []},
    {"name": "employment_by_industry", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["IND21P Industry of Employment"], "cols": []},
    {"name": "housing_tenure_by_state", "dataset": "2021 Census - counting dwellings, place of enumeration", "rows": ["TEND Tenure Type"], "cols": ["Greater Capital City Statistical Areas (EN)"]},
    {"name": "age_by_sex", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["AGE5P Age in Five Year Groups"], "cols": ["SEXP Sex"]},
    {"name": "country_of_birth_by_language", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["BPLP Country of Birth of Person"], "cols": ["LANP Language Spoken at Home"]},
    {"name": "income_by_occupation", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["INCP Individual Income (weekly)"], "cols": ["OCC21P Occupation"]},
    {"name": "age_sex_by_marital", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["AGE5P Age in Five Year Groups", "SEXP Sex"], "cols": ["MSTP Registered Marital Status"]},
    {"name": "indigenous_by_age_sex", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["INGP Indigenous Status"], "cols": ["AGE5P Age in Five Year Groups", "SEXP Sex"]},
    {"name": "sex_simple", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["SEXP Sex"], "cols": []},
    {"name": "age_simple", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["AGE10P Age in Ten Year Groups"], "cols": []},
    {"name": "marital_by_sex", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["MSTP Registered Marital Status"], "cols": ["SEXP Sex"]},
    {"name": "labour_force", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["LFSP Labour Force Status"], "cols": []},
    {"name": "education_level", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["QALFP Non-School Qualification: Level of Education"], "cols": []},
    {"name": "travel_to_work", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["MTWP Method of Travel to Work"], "cols": []},
    {"name": "dwelling_structure", "dataset": "2021 Census - counting dwellings, place of enumeration", "rows": ["STRD Dwelling Structure"], "cols": []},
    {"name": "household_income", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["HIND Household Income (weekly)"], "cols": []},
    {"name": "birthplace_by_sex", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["BPLP Country of Birth of Person"], "cols": ["SEXP Sex"]},
    {"name": "occupation_by_sex", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["OCC21P Occupation"], "cols": ["SEXP Sex"]},
    {"name": "religion", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["RELP Religious Affiliation"], "cols": []},
    {"name": "ancestry", "dataset": "2021 Census - counting persons, place of enumeration", "rows": ["ANC1P Ancestry 1st Response"], "cols": []},
]


def main():
    setup_logging(verbose=False)
    config = load_config()
    output_dir = Path(__file__).parent.parent / "output" / "batch_http"
    output_dir.mkdir(parents=True, exist_ok=True)
    results_file = output_dir / "batch_results.json"
    results = []

    print(f"\n{'='*70}")
    print(f"BATCH FETCH (HTTP): {len(REQUESTS)} tables")
    print(f"Output dir: {output_dir}")
    print(f"{'='*70}\n")

    for i, req_def in enumerate(REQUESTS, 1):
        name = req_def["name"]
        csv_path = output_dir / f"{i:02d}_{name}.csv"
        entry = {"name": name, "index": i, "csv_path": str(csv_path), "status": "pending"}

        print(f"[{i:2d}/{len(REQUESTS)}] {name}")
        print(f"  Dataset: {req_def['dataset'][:60]}")
        print(f"  Rows: {req_def['rows']}, Cols: {req_def.get('cols', [])}")

        try:
            request = TableRequest(
                dataset=req_def["dataset"],
                rows=req_def["rows"],
                cols=req_def.get("cols", []),
                wafers=req_def.get("wafers", []),
            )
        except ValueError as e:
            entry["status"] = "invalid_request"
            entry["error"] = str(e)
            results.append(entry)
            print(f"  INVALID: {e}\n")
            continue

        try:
            start = time.time()
            with TableBuilderHTTPSession(config) as session:
                http_fetch_table(session, request, str(csv_path))
            duration = time.time() - start
            entry["status"] = "success"
            entry["duration_seconds"] = round(duration, 1)
            entry["csv_size"] = csv_path.stat().st_size if csv_path.exists() else 0
            print(f"  OK: {duration:.0f}s, {entry['csv_size']} bytes\n")
        except Exception as e:
            duration = time.time() - start
            entry["status"] = "fetch_error"
            entry["error"] = str(e)[:200]
            entry["duration_seconds"] = round(duration, 1)
            print(f"  ERROR ({duration:.0f}s): {str(e)[:150]}\n")

        results.append(entry)
        results_file.write_text(json.dumps(results, indent=2))

    # Summary
    print(f"\n{'='*70}")
    success = sum(1 for r in results if r["status"] == "success")
    errors = sum(1 for r in results if r["status"] == "fetch_error")
    total_time = sum(r.get("duration_seconds", 0) for r in results)
    print(f"SUCCESS: {success}/{len(REQUESTS)} | ERRORS: {errors} | TIME: {total_time:.0f}s ({total_time/60:.1f}m)")
    if success > 0:
        print(f"AVG: {total_time/success:.0f}s per table")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
