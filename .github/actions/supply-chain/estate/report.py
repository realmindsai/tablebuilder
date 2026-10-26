"""Run reports: serialize findings, diff against the previous run, build the
Slack payload. Kept pure (no network); delivery is `estate.notify`."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .findings import Finding, Severity


@dataclass(frozen=True)
class SeverityEscalation:
    previous: Finding
    current: Finding


@dataclass
class Delta:
    new: list[Finding]
    resolved: list[Finding]
    escalated: list[SeverityEscalation]
    still_open: list[Finding]

    @property
    def has_changes(self) -> bool:
        return bool(self.new or self.resolved or self.escalated)


def load_report(path: str | Path) -> list[Finding]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text() or "[]")
    return [Finding.from_dict(d) for d in data.get("findings", data if isinstance(data, list) else [])]


def write_report(
    path: str | Path,
    findings: list[Finding],
    generated_at: str,
    accepted: list[Finding] | None = None,
) -> None:
    """`accepted` findings are recorded for the audit trail only: `count` and
    `findings` exclude them, and `load_report` never reads them back, so they
    never enter a diff."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": generated_at,
        "count": len(findings),
        "findings": [f.to_dict() for f in _sorted(findings)],
    }
    if accepted:
        payload["accepted"] = [f.to_dict() for f in _sorted(accepted)]
    p.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")


def diff_findings(current: list[Finding], previous: list[Finding]) -> Delta:
    cur = _canonical_findings(current)
    prev = _canonical_findings(previous)
    new = [cur[k] for k in cur if k not in prev]
    resolved = [prev[k] for k in prev if k not in cur]
    escalated = [
        SeverityEscalation(previous=prev[k], current=cur[k])
        for k in cur
        if k in prev and cur[k].severity > prev[k].severity
    ]
    still_open = [
        cur[k]
        for k in cur
        if k in prev and cur[k].severity <= prev[k].severity
    ]
    return Delta(
        new=_sorted(new),
        resolved=_sorted(resolved),
        escalated=_sorted_escalations(escalated),
        still_open=_sorted(still_open),
    )


def _canonical_findings(findings: list[Finding]) -> dict[str, Finding]:
    canonical: dict[str, Finding] = {}
    for finding in findings:
        existing = canonical.get(finding.key())
        if existing is None or _representative_key(finding) > _representative_key(existing):
            canonical[finding.key()] = finding
    return canonical


def _representative_key(finding: Finding) -> tuple[int, str, str, str, str, str, str]:
    return (
        int(finding.severity),
        finding.asset,
        finding.check,
        finding.summary,
        finding.expected,
        finding.actual,
        finding.evidence,
    )


def _sorted(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (-int(f.severity), f.asset, f.check))


def _sorted_escalations(
    escalations: list[SeverityEscalation],
) -> list[SeverityEscalation]:
    return sorted(
        escalations,
        key=lambda entry: (
            -int(entry.current.severity),
            entry.current.asset,
            entry.current.check,
            entry.current.summary,
        ),
    )


def slack_payload(
    delta: Delta,
    generated_at: str,
    dashboard_hint: str = "",
    title: str = "Surface monitor",
    accepted: int = 0,
) -> dict:
    """Build a Slack webhook payload. Returns a 'quiet' payload when nothing
    changed so the caller can choose to skip posting.

    `title` names the job in both the quiet line and the header. It defaults to
    the original caller so surface_monitor is unaffected; every other consumer
    passes its own, because a channel carrying two jobs that both announce
    themselves as "Surface monitor" is worse than no header at all."""
    accepted_note = f", {accepted} accepted" if accepted else ""
    if not delta.has_changes:
        return {
            "quiet": True,
            "text": (
                f"{title}: no change ({len(delta.still_open)} open{accepted_note})"
                f" · {generated_at}"
            ),
        }

    lines: list[str] = [f":shield: *{title}* — {generated_at}"]
    if delta.new:
        lines.append(f"\n*{len(delta.new)} new finding(s):*")
        lines.extend(_fmt(f) for f in delta.new)
    if delta.escalated:
        lines.append(f"\n*{len(delta.escalated)} severity escalation(s):*")
        lines.extend(_fmt_escalation(entry) for entry in delta.escalated)
    if delta.resolved:
        lines.append(f"\n*{len(delta.resolved)} resolved:*")
        lines.extend(_fmt_resolved(f) for f in delta.resolved)
    if delta.still_open:
        lines.append(f"\n_{len(delta.still_open)} still open (unchanged)._")
    if accepted:
        lines.append(f"\n_{accepted} accepted (assets.yaml), not alerted._")
    if dashboard_hint:
        lines.append(f"\n{dashboard_hint}")

    return {"quiet": False, "text": "\n".join(lines)}


def bootstrap_payload(
    findings: list[Finding],
    generated_at: str,
    title: str = "Surface monitor",
    accepted: int = 0,
) -> dict:
    """Announce a run that had no baseline to compare against.

    Diffing against an absent baseline manufactures a full set of "new"
    findings out of state that was already there, and reports everything the
    estate has since fixed as "resolved". So a bootstrap says so, and lists
    what it recorded rather than what changed — the findings still have to be
    visible, or a first run that meets a P0 would report only a count.
    """
    lines = [
        f":shield: *{title}* — baseline established · {generated_at}",
        f"\n*{len(findings)} finding(s) recorded*, no previous baseline to "
        "diff against; the next run compares against this one:",
    ]
    lines.extend(_fmt(f) for f in _sorted(findings))
    if accepted:
        lines.append(f"\n_{accepted} accepted (assets.yaml), not alerted._")
    return {"quiet": False, "text": "\n".join(lines)}


_EMOJI = {
    Severity.P0: ":rotating_light:",
    Severity.HIGH: ":red_circle:",
    Severity.MED: ":large_orange_circle:",
    Severity.LOW: ":large_yellow_circle:",
    Severity.INFO: ":white_circle:",
}


def _fmt(f: Finding) -> str:
    emoji = _EMOJI.get(f.severity, "")
    tail = f" — _{f.actual}_" if f.actual else ""
    return f"  {emoji} *{f.severity.name}* `{f.asset}`/{f.check}: {f.summary}{tail}"


def _fmt_resolved(finding: Finding) -> str:
    tail = f" — _{finding.actual}_" if finding.actual else ""
    return f"  ~{finding.asset}/{finding.check}: {finding.summary}~{tail}"


def _fmt_escalation(escalation: SeverityEscalation) -> str:
    current = escalation.current
    emoji = _EMOJI.get(current.severity, "")
    tail = f" — _{current.actual}_" if current.actual else ""
    transition = f"{escalation.previous.severity.name} → {current.severity.name}"
    return f"  {emoji} *{transition}* `{current.asset}`/{current.check}: {current.summary}{tail}"

