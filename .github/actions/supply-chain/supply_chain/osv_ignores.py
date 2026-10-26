# ABOUTME: Flags osv-scanner ignore entries that have lapsed or were never time-bounded
# ABOUTME: An acceptance nobody revisits is indistinguishable from a suppressed finding

"""Watch the `ignoreUntil` dates in every osv-scanner.toml.

`osv-scanner` stops honouring an ignore once its `ignoreUntil` passes, so the
vulnerability reappears and the scan reddens on its own. What it never does is
warn you *beforehand*, or notice an acceptance that carries no end date at all.
Both leave a `reason` string standing long after the constraint it describes has
gone — the failure mode recorded in realmindsai/speaker-id#53, where 18 of 21
entries had quietly stopped matching anything.

Ported from speaker-id (PR #60) into the fleet-stamped CI payload so it ships in
the same re-stamp pass rather than becoming a second fleet-wide edit
(realmindsai/security#6). One level differs from that original: an entry with no
`ignoreUntil` is an **error** here, not a warning. All 69 ignore entries across
the 11 repos in the estate that have an osv-scanner.toml already carry a date, so
the stricter level reddens nothing on arrival — and an acceptance with no end
date is exactly the one that never comes up for review. An advisory that really
is unfixable can carry a far-future date and still surface; that costs one line.

Stdlib only, on purpose: this runs from the stamped payload with a bare
`python3`, with no uv sync, no venv and no network.

Exit status: 1 if any entry has lapsed, is undated, or cannot be read, else 0.
Entries expiring soon are reported as warnings and do not fail.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_WARN_WITHIN_DAYS = 14


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    path: str
    vuln_id: str
    message: str


def _coerce_date(value):
    """TOML bare dates arrive as date objects; accept a quoted date too."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value.strip())
    raise TypeError(f"unsupported type {type(value).__name__}")


def check_paths(paths, today=None, warn_within_days=DEFAULT_WARN_WITHIN_DAYS):
    """Return findings for every ignore entry that needs a human to look at it."""
    today = today or dt.date.today()
    findings: list[Finding] = []

    for path in paths:
        rel = str(path)
        try:
            data = tomllib.loads(Path(path).read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            findings.append(Finding("error", rel, "-", f"could not parse: {exc}"))
            continue

        for entry in data.get("IgnoredVulns", []):
            vuln_id = str(entry.get("id", "<no id>"))

            if "ignoreUntil" not in entry:
                findings.append(Finding(
                    "error", rel, vuln_id,
                    "no ignoreUntil — this acceptance never comes up for review",
                ))
                continue

            try:
                until = _coerce_date(entry["ignoreUntil"])
            except (ValueError, TypeError) as exc:
                findings.append(Finding(
                    "error", rel, vuln_id,
                    f"ignoreUntil is not a date ({entry['ignoreUntil']!r}): {exc}",
                ))
                continue

            days = (until - today).days
            if days <= 0:
                ago = "today" if days == 0 else f"{-days} day{'s' if -days != 1 else ''} ago"
                findings.append(Finding(
                    "error", rel, vuln_id,
                    f"expired {ago} ({until}) — osv-scanner no longer honours it",
                ))
            elif days <= warn_within_days:
                findings.append(Finding(
                    "warning", rel, vuln_id,
                    f"expires in {days} day{'s' if days != 1 else ''} ({until})",
                ))

    return findings


def render(findings):
    """Format findings for a CI log."""
    if not findings:
        return "All osv-scanner ignore entries are time-bounded and current."
    lines = []
    for f in sorted(findings, key=lambda f: (f.level != "error", f.path, f.vuln_id)):
        tag = "ERROR" if f.level == "error" else "WARN "
        lines.append(f"{tag} {f.path}: {f.vuln_id}: {f.message}")
    return "\n".join(lines)


def render_github(findings):
    """Emit GitHub Actions workflow commands so findings annotate the PR itself.

    A warning printed into a log is the thing nobody reads; an annotation is
    attached to the file and shown on the run summary.
    """
    lines = []
    for f in sorted(findings, key=lambda f: (f.level != "error", f.path, f.vuln_id)):
        # Workflow commands are line-oriented — a literal newline would truncate.
        msg = f"{f.vuln_id}: {f.message}".replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        lines.append(f"::{f.level} file={f.path}::{msg}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", type=Path,
                    help="osv-scanner.toml files (default: every one in the tree)")
    ap.add_argument("--warn-within-days", type=int, default=DEFAULT_WARN_WITHIN_DAYS,
                    help=f"warn this far ahead of expiry (default {DEFAULT_WARN_WITHIN_DAYS})")
    args = ap.parse_args(argv)

    paths = args.paths or sorted(
        p for p in Path().rglob("osv-scanner.toml") if ".venv" not in p.parts
    )
    if not paths:
        print("No osv-scanner.toml found.")
        return 0

    findings = check_paths(paths, warn_within_days=args.warn_within_days)
    print(f"Checked {len(paths)} ignore file(s): {', '.join(str(p) for p in paths)}")
    print(render(findings))
    if findings and os.environ.get("GITHUB_ACTIONS") == "true":
        print(render_github(findings))
    return 1 if any(f.level == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
