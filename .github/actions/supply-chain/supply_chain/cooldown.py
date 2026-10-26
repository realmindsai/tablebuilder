"""cooldown — is the uv publish-age gate actually declared, and did the lock keep it?

The gate used to live only in a shell wrapper on one Mac, so any `uv run` on a
server re-resolved without it and dropped the recorded window from uv.lock.
Committed `[tool.uv] exclude-newer` is the fix; this check is what stops the
next repo from being created without it.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import tomllib
from pathlib import Path

from estate.findings import Finding, Severity

# Same exclusions as `uv-audit-all` (see docs/uv-audit.md): these directories
# hold other projects' locks (or none worth trusting), so pruning them keeps
# scan_tree fast and keeps their locks from being misattributed as our own.
# Both "worktrees" and ".worktrees" are kept: ~/.config/superpowers uses the
# undotted form, but the fleet's actual git-worktree checkouts (e.g.
# jot-v2/.worktrees/mcp-refactor, speaker-id/.worktrees/voiceprint) are
# dot-prefixed — a worktree is a second checkout of a repo already scanned,
# so missing either form means a duplicate finding for the same pyproject.toml.
# "work" is dependabot-sweeper's gitignored scratch area: it clones the repos it
# sweeps into work/<repo>/, so their locks are transient copies, not deployed
# trees, and a finding there is noise (a daily Slack MED for
# dependabot-sweeper/work/dependabot-sweeper-e2e). A name rule rather than
# `git check-ignore`: nothing here shells to git, and on totoro svc-security
# walks checkouts owned by other svc users, which git refuses as "dubious
# ownership" without per-repo safe.directory entries.
SKIP_DIRS = {".venv", "node_modules", "worktrees", ".worktrees", "archive", ".git", "work"}

# uv accepts either a rolling window ("3 days", "P3D") or a fixed RFC-3339
# floor ("2026-06-15", "2026-06-15T00:00:00Z"). Only the rolling form is a
# cooldown; see _is_absolute_cooldown for why. A bare (unquoted) date in TOML
# arrives from tomllib as a date/datetime object, a quoted one as a string, so
# both shapes have to be recognised.
_RFC3339_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")
MIN_COOLDOWN_SECONDS = 3 * 24 * 60 * 60
_FRIENDLY_DURATION = re.compile(
    r"^([+-]?\d+)\s*(seconds?|minutes?|hours?|days?|weeks?)$",
)
_ISO_DURATION = re.compile(
    r"^(?P<sign>[+-]?)P(?:(?P<weeks>\d+)W|"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?)?)$",
)
_UNIT_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 60 * 60,
    "day": 24 * 60 * 60,
    "week": 7 * 24 * 60 * 60,
}


def _cooldown_value(pyproject_text: str) -> object | None:
    """The raw `[tool.uv] exclude-newer` value, or None if there isn't one."""
    try:
        doc = tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError:
        return None
    value = doc.get("tool", {}).get("uv", {}).get("exclude-newer")
    return value or None


def _uv_toml_cooldown(uv_toml_text: str) -> object | None:
    """The raw top-level `exclude-newer` from a uv.toml, or None."""
    try:
        doc = tomllib.loads(uv_toml_text)
    except tomllib.TOMLDecodeError:
        return None
    return doc.get("exclude-newer") or None


def _is_absolute_cooldown(value: object) -> bool:
    """Is this a fixed point in time rather than a rolling window?

    A fixed floor is not a weaker cooldown, it is a different thing wearing
    the same key. On the day it is written it admits every release already
    published — i.e. no gate at all — and from then on it only ever freezes
    resolution further, never settling into a window. uv also emits no
    `exclude-newer-span` for it, so lock_has_span can never confirm it either.
    """
    if isinstance(value, (dt.datetime, dt.date)):
        return True
    return isinstance(value, str) and bool(_RFC3339_PREFIX.match(value.strip()))


def _duration_seconds(value: object) -> int | None:
    """Parse the relative duration forms uv accepts into seconds."""
    if not isinstance(value, str):
        return None
    text = value
    friendly = _FRIENDLY_DURATION.fullmatch(text)
    if friendly:
        amount, unit = friendly.groups()
        return int(amount) * _UNIT_SECONDS[unit.lower().removesuffix("s")]

    iso = _ISO_DURATION.fullmatch(text)
    if not iso:
        return None
    parts = iso.groupdict()
    component_names = ("weeks", "days", "hours", "minutes", "seconds")
    if not any(parts[name] is not None for name in component_names):
        return None
    seconds = sum(
        int(parts[name] or 0) * _UNIT_SECONDS[name.removesuffix("s")]
        for name in component_names
    )
    return -seconds if parts["sign"] == "-" else seconds


def declares_cooldown(pyproject_text: str) -> bool:
    return _cooldown_value(pyproject_text) is not None


def _lock_span(lock_text: str) -> object | None:
    # `exclude-newer` alone is uv's own inert back-compat placeholder
    # ("This has no effect..."), so only the span counts as a real window.
    try:
        doc = tomllib.loads(lock_text)
    except tomllib.TOMLDecodeError:
        return None
    return doc.get("options", {}).get("exclude-newer-span")


def lock_has_span(lock_text: str) -> bool:
    return bool(_lock_span(lock_text))


def check_repo(
    repo_id: str,
    pyproject_text: str | None,
    lock_text: str | None,
    uv_toml_text: str | None = None,
) -> list[Finding]:
    if lock_text is None:
        return []
    if uv_toml_text is not None:
        return _shadowed_by_uv_toml(repo_id, uv_toml_text)
    value = _cooldown_value(pyproject_text or "")
    if value is None:
        return [
            Finding(
                asset=repo_id,
                check="uv-cooldown",
                severity=Severity.HIGH,
                summary="uv project declares no publish-age cooldown",
                expected='[tool.uv] exclude-newer = "3 days" in pyproject.toml',
                actual="no exclude-newer under [tool.uv]",
                evidence="any uv run/sync/add here resolves with no cooldown",
            )
        ]
    if _is_absolute_cooldown(value):
        # HIGH, the same rank as no declaration at all, because that is what it
        # amounts to: the day someone writes today's date here, nothing is
        # gated, and nothing ever will be — it drifts into an ever-wider freeze
        # instead of a window. It also defeats the other half of this check
        # (no exclude-newer-span in the lock), so the repo can never be
        # confirmed clean. Ranking it MED would let a repo with no effective
        # cooldown sit under a HIGH-gated CI threshold. The shipped template
        # carried exactly this value for 71 days.
        return [
            Finding(
                asset=repo_id,
                check="uv-cooldown",
                severity=Severity.HIGH,
                summary="uv cooldown is a fixed timestamp, not a rolling window",
                expected='[tool.uv] exclude-newer = "3 days" (a relative window)',
                actual=f"exclude-newer = {value!r}",
                evidence=(
                    "a fixed floor gates nothing on the day it is set and only "
                    "freezes resolution afterwards; uv emits no "
                    "exclude-newer-span for it, so the lock cannot confirm a "
                    'window either. Replace the date with "3 days".'
                ),
            )
        ]
    duration_seconds = _duration_seconds(value)
    if duration_seconds is None:
        return [
            Finding(
                asset=repo_id,
                check="uv-cooldown",
                severity=Severity.HIGH,
                summary="uv cooldown duration is invalid",
                expected='[tool.uv] exclude-newer = "3 days" (a relative window)',
                actual=f"exclude-newer = {value!r}",
                evidence=(
                    f"uv cannot record a window for {value!r}. Replace it with "
                    '"3 days" and regenerate uv.lock.'
                ),
            )
        ]
    if duration_seconds < MIN_COOLDOWN_SECONDS:
        return [
            Finding(
                asset=repo_id,
                check="uv-cooldown",
                severity=Severity.HIGH,
                summary="uv cooldown is shorter than the three-day policy floor",
                expected='[tool.uv] exclude-newer = "3 days" or longer',
                actual=f"exclude-newer = {value!r}",
                evidence=(
                    "a shorter window admits releases before the estate's malware "
                    'detection buffer has elapsed. Replace it with "3 days".'
                ),
            )
        ]

    span = _lock_span(lock_text)
    if not span:
        return [
            Finding(
                asset=repo_id,
                check="uv-cooldown",
                severity=Severity.MED,
                summary="cooldown is declared but uv.lock does not record it",
                expected="[options].exclude-newer-span in uv.lock",
                actual="no exclude-newer-span",
                evidence="lock predates the config — re-lock to record it",
            )
        ]
    span_seconds = _duration_seconds(span)
    if span_seconds is None:
        return [
            Finding(
                asset=repo_id,
                check="uv-cooldown",
                severity=Severity.MED,
                summary="uv.lock records an invalid cooldown span",
                expected="[options].exclude-newer-span as a relative duration",
                actual=f"exclude-newer-span = {span!r}",
                evidence="re-lock with the valid project cooldown to replace the span",
            )
        ]
    if span_seconds < MIN_COOLDOWN_SECONDS:
        return [
            Finding(
                asset=repo_id,
                check="uv-cooldown",
                severity=Severity.HIGH,
                summary="uv.lock recorded a cooldown below the three-day policy floor",
                expected='[options].exclude-newer-span = "P3D" or longer',
                actual=f"exclude-newer-span = {span!r}",
                evidence=(
                    "the committed resolution metadata proves the effective window "
                    "was shorter than three days; re-lock with the project cooldown"
                ),
            )
        ]
    return []


def _shadowed_by_uv_toml(repo_id: str, uv_toml_text: str) -> list[Finding]:
    """A uv.toml is present, so `[tool.uv]` in pyproject.toml is not read.

    uv prefers uv.toml when both exist: it prints a warning and ignores the
    pyproject table outright. So the pyproject's state cannot be reported on
    here — advice about a file uv is not reading would be worse than none —
    and a hardened pyproject standing behind a uv.toml must never read as
    all-clear. This returns instead of falling through for that reason.
    """
    value = _uv_toml_cooldown(uv_toml_text)
    if value is None or _is_absolute_cooldown(value):
        return [
            Finding(
                asset=repo_id,
                check="uv-cooldown",
                severity=Severity.HIGH,
                summary="uv.toml shadows [tool.uv] and carries no rolling cooldown",
                expected="the cooldown in pyproject.toml [tool.uv], with no uv.toml beside it",
                actual=(
                    "uv.toml present"
                    + (f" with exclude-newer = {value!r}" if value is not None else "")
                ),
                evidence=(
                    "uv reads uv.toml INSTEAD of [tool.uv] — it warns and ignores "
                    "the pyproject table entirely, so hardening pyproject.toml "
                    "here changes nothing. Fold the uv.toml settings into "
                    "pyproject.toml and delete it."
                ),
            )
        ]
    duration_seconds = _duration_seconds(value)
    if duration_seconds is None:
        return [
            Finding(
                asset=repo_id,
                check="uv-cooldown",
                severity=Severity.HIGH,
                summary="uv.toml shadows [tool.uv] with an invalid cooldown",
                expected='[tool.uv] exclude-newer = "3 days" in pyproject.toml',
                actual=f"uv.toml exclude-newer = {value!r}",
                evidence=(
                    f"uv cannot record a window for {value!r}. Delete uv.toml and "
                    'put exclude-newer = "3 days" under [tool.uv], then regenerate '
                    "uv.lock."
                ),
            )
        ]
    if duration_seconds < MIN_COOLDOWN_SECONDS:
        return [
            Finding(
                asset=repo_id,
                check="uv-cooldown",
                severity=Severity.HIGH,
                summary="uv.toml shadows [tool.uv] with a sub-policy cooldown",
                expected='[tool.uv] exclude-newer = "3 days" in pyproject.toml',
                actual=f"uv.toml exclude-newer = {value!r}",
                evidence=(
                    "delete uv.toml and put a cooldown of at least three days "
                    "under [tool.uv]"
                ),
            )
        ]
    return [
        Finding(
            asset=repo_id,
            check="uv-cooldown",
            severity=Severity.MED,
            summary="cooldown lives in uv.toml, which shadows [tool.uv]",
            expected='[tool.uv] exclude-newer = "3 days" in pyproject.toml',
            actual=f"uv.toml exclude-newer = {value!r}",
            evidence=(
                "the gate itself holds, but it sits in the one file that "
                "silently disables [tool.uv] — so harden-repo.sh's write here "
                "is inert, and deleting uv.toml would drop the gate. Fold it "
                "into pyproject.toml so one file carries the config."
            ),
        )
    ]


def scan_tree(root: Path) -> list[Finding]:
    """Walk `root` for uv repos, skipping SKIP_DIRS by pruning `os.walk` in place.

    `root.rglob("uv.lock")` filtered after the fact still descends into every
    pruned directory before discarding its hits — 6.1s and 46 locks (6 of them
    inside .venv/node_modules) over the fleet. Pruning `dirnames` in place stops
    `os.walk` from ever entering those directories: 0.1s for the same 40 real
    repos. Same answer, 72x faster.
    """
    root = Path(root)
    hits: list[tuple[str, list[Finding]]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        if "uv.lock" not in filenames:
            continue
        d = Path(dirpath)
        repo_id = str(d.relative_to(root))
        pp = d / "pyproject.toml"
        lock = d / "uv.lock"
        uv_toml = d / "uv.toml"
        try:
            pp_text = pp.read_text() if pp.exists() else None
            lock_text = lock.read_text()
            uv_toml_text = uv_toml.read_text() if uv_toml.exists() else None
        except (OSError, UnicodeDecodeError) as exc:
            # A file we can't read is not "all clear" — silence is this
            # check's whole all-clear signal, so an unreadable pyproject.toml
            # or uv.lock must never resolve to nothing. We can't confirm the
            # gate is present, which is closer to "gate absent" (HIGH) than
            # to "gate present" — so it gets the same severity as a missing
            # declaration, not a downgrade to MED or a swallowed skip. The
            # rest of the tree is still walked; only this one repo is
            # affected.
            hits.append(
                (
                    repo_id,
                    [
                        Finding(
                            asset=repo_id,
                            check="uv-cooldown",
                            severity=Severity.HIGH,
                            summary="uv repo's pyproject.toml or uv.lock could not be read",
                            expected="pyproject.toml, uv.lock and any uv.toml readable as UTF-8 text",
                            actual=f"{exc.__class__.__name__}: {exc}",
                            evidence="gate presence cannot be confirmed for this repo",
                        )
                    ],
                )
            )
            continue
        hits.append((repo_id, check_repo(repo_id, pp_text, lock_text, uv_toml_text)))
    findings: list[Finding] = []
    for _, repo_findings in sorted(hits, key=lambda item: item[0]):
        findings.extend(repo_findings)
    return findings
