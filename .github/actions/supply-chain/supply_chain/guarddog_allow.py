# ABOUTME: Gates a GuardDog JSON scan against a per-package, per-rule allowlist
# ABOUTME: Naming 12 noisy packages beats disarming 11 rules for the whole fleet

"""Accept named packages, not weakened rules.

GuardDog's `--exit-non-zero-on-finding` gates on ANY finding, so a single fat
dependency forces you to drop the rule it trips — for every repo. Measured
estate-wide (331 unique packages, GuardDog 3.2.0), only 12 packages trip the
36-rule allowlist, and `litellm` alone accounts for 7 of the 11 rules involved.
Dropping those would disarm keylogging, memory-scraping, filesystem-destruction
and three obfuscation detectors across all 36 repos to silence one package.

So the scan runs WITHOUT `--exit-non-zero-on-finding` (a non-zero exit from
GuardDog then means a real failure, not a finding) and this gates the result
instead: exit 1 unless every finding is named in the allowlist.

Acceptance is per package AND rule, never blanket per package. psutil is excused
for `threat-process-memory` because reading process memory is what it is for,
and stays gated on everything else.

Entries expire, on the same discipline as [[supply_chain/osv_ignores.py]] —
realmindsai/speaker-id#53 found 18 of 21 osv ignores matching nothing, several
justified by pins that had been bumped away. An acceptance nobody revisits is
indistinguishable from a suppressed finding, so an entry that has lapsed, has no
date, or no longer matches anything is reported.

Stdlib only: this runs from the stamped payload with a bare `python3`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_WARN_WITHIN_DAYS = 14
ALLOWLIST_NAME = "guarddog-allow.toml"


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    message: str


@dataclass(frozen=True)
class Acceptance:
    package: str
    rules: frozenset[str]
    reason: str
    until: dt.date | None
    dated: bool


def _coerce_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value.strip())
    raise TypeError(f"unsupported type {type(value).__name__}")


def load_allowlist(path) -> list[Acceptance]:
    """Read the allowlist. A missing file means: accept nothing."""
    path = Path(path)
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text())
    out = []
    for entry in data.get("AcceptedFindings", []):
        raw = entry.get("ignoreUntil")
        try:
            until = _coerce_date(raw) if raw is not None else None
        except (ValueError, TypeError):
            until = None
        out.append(Acceptance(
            package=str(entry.get("package", "<no package>")),
            rules=frozenset(entry.get("rules", [])),
            reason=str(entry.get("reason", "")),
            until=until,
            dated=raw is not None and until is not None,
        ))
    return out


def check(scan, allowlist, today=None, warn_within_days=DEFAULT_WARN_WITHIN_DAYS):
    """Gate a GuardDog scan document against the allowlist."""
    today = today or dt.date.today()
    findings: list[Finding] = []
    live: dict[tuple[str, str], Acceptance] = {}

    for acc in allowlist:
        if not acc.dated:
            findings.append(Finding(
                "error",
                f"{acc.package}: no ignoreUntil — this acceptance never comes up for review",
            ))
            continue
        days = (acc.until - today).days
        if days <= 0:
            ago = "today" if days == 0 else f"{-days} day{'s' if -days != 1 else ''} ago"
            findings.append(Finding(
                "error",
                f"{acc.package}: acceptance expired {ago} ({acc.until}) — "
                f"re-date it or drop the dependency",
            ))
            continue
        if days <= warn_within_days:
            findings.append(Finding(
                "warning",
                f"{acc.package}: acceptance expires in {days} "
                f"day{'s' if days != 1 else ''} ({acc.until})",
            ))
        for rule in acc.rules:
            live[(acc.package, rule)] = acc

    used: set[tuple[str, str]] = set()
    for pkg in scan:
        name = pkg.get("dependency", "<unknown>")
        result = pkg.get("result") or {}
        for rule, hits in (result.get("results") or {}).items():
            if not hits:
                continue
            if (name, rule) in live:
                used.add((name, rule))
                continue
            findings.append(Finding(
                "error", f"{name}: {rule} — not accepted in {ALLOWLIST_NAME}"
            ))
        # A rule that errored gated nothing. Loud, but not fatal: an upstream bug
        # must not be able to block every repo's CI.
        for rule, why in (result.get("errors") or {}).items():
            findings.append(Finding(
                "warning", f"{name}: {rule} did not run ({why})"
            ))

    # Only packages actually present in THIS scan can tell us an acceptance has
    # gone stale. The allowlist is fleet-wide and most repos hold few of its
    # packages, so warning on absence would emit ~20 lines in every repo and bury
    # the one that matters — the habituation this payload exists to prevent.
    scanned = {pkg.get("dependency") for pkg in scan}
    for (package, rule), acc in sorted(live.items()):
        if package in scanned and (package, rule) not in used:
            findings.append(Finding(
                "warning",
                f"{package}: acceptance for {rule} matched nothing — "
                f"the package no longer trips it, so drop the entry",
            ))

    return findings


def render(findings):
    if not findings:
        return "GuardDog: no findings outside the accepted list."
    order = {"error": 0, "warning": 1}
    lines = []
    for f in sorted(findings, key=lambda f: (order[f.level], f.message)):
        lines.append(f"{'ERROR' if f.level == 'error' else 'WARN '} {f.message}")
    return "\n".join(lines)


def render_github(findings):
    """Annotate the allowlist file, so findings land on the PR."""
    order = {"error": 0, "warning": 1}
    lines = []
    for f in sorted(findings, key=lambda f: (order[f.level], f.message)):
        msg = f.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        lines.append(f"::{f.level} file={ALLOWLIST_NAME}::{msg}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scan", type=Path, help="GuardDog --output-format json output")
    ap.add_argument("--allowlist", type=Path, default=Path(ALLOWLIST_NAME))
    ap.add_argument("--warn-within-days", type=int, default=DEFAULT_WARN_WITHIN_DAYS)
    args = ap.parse_args(argv)

    try:
        scan = json.loads(args.scan.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        # The scan not being readable is a failure of the gate itself, never a pass.
        print(f"ERROR could not read GuardDog output {args.scan}: {exc}")
        return 1

    findings = check(scan, load_allowlist(args.allowlist),
                     warn_within_days=args.warn_within_days)
    print(render(findings))
    if findings and os.environ.get("GITHUB_ACTIONS") == "true":
        print(render_github(findings))
    return 1 if any(f.level == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
