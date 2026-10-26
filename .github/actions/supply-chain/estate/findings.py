"""Severity and Finding: the vocabulary every check in the estate emits."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import IntEnum

_OSV_ADVISORY_ID = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._+]*-[A-Za-z0-9][A-Za-z0-9._+:-]*"
)
MALFORMED_OSV_IDENTITY = "osv-meta:missing-id"


def validated_osv_advisory_id(value: object) -> str:
    """Return a safe OSV identifier token, or empty string when invalid."""
    if not isinstance(value, str) or _OSV_ADVISORY_ID.fullmatch(value) is None:
        return ""
    return value


def _normalized_identity(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _legacy_osv_identity(actual: object, evidence: object) -> str:
    if actual == "?:":
        return MALFORMED_OSV_IDENTITY

    if isinstance(actual, str):
        prefix, separator, _ = actual.partition(": ")
        if separator:
            advisory_id = validated_osv_advisory_id(prefix)
            return (
                f"osv:{advisory_id}"
                if advisory_id
                else MALFORMED_OSV_IDENTITY
            )

    if isinstance(evidence, str) and evidence.startswith("OSV "):
        advisory_id, separator, context = evidence[4:].partition(" (")
        if separator and context.endswith(")"):
            advisory_id = validated_osv_advisory_id(advisory_id)
            return (
                f"osv:{advisory_id}"
                if advisory_id
                else MALFORMED_OSV_IDENTITY
            )
    return ""


class Severity(IntEnum):
    """Ordered so the highest number is the most urgent.

    Comparisons and sorting use the numeric order; the name is what appears in
    Slack and reports.
    """

    INFO = 0
    LOW = 1
    MED = 2
    HIGH = 3
    P0 = 4

    @classmethod
    def from_name(cls, name: str) -> Severity:
        return cls[name.strip().upper()]


@dataclass(frozen=True)
class Finding:
    """A single security observation about one asset from one check.

    A finding always describes something worth surfacing; checks that pass
    emit no finding (absence is the "all clear"). `key()` is the stable
    identity used to diff one run against the previous one, so the same
    unresolved issue does not re-alert every hour.
    """

    asset: str
    check: str
    severity: Severity
    summary: str
    expected: str = ""
    actual: str = ""
    evidence: str = ""
    identity: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity", _normalized_identity(self.identity))

    def key(self) -> str:
        """Stable identity for run-over-run delta (ignores volatile evidence)."""
        return f"{self.asset}::{self.check}::{self.identity or self.summary}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.name
        if not self.identity:
            del d["identity"]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Finding:
        identity = _normalized_identity(d.get("identity", ""))
        if not identity and d.get("check") == "cve-version":
            identity = _legacy_osv_identity(
                d.get("actual", ""), d.get("evidence", ""),
            )
        return cls(
            asset=d["asset"],
            check=d["check"],
            severity=Severity.from_name(d["severity"]),
            summary=d["summary"],
            expected=d.get("expected", ""),
            actual=d.get("actual", ""),
            evidence=d.get("evidence", ""),
            identity=identity,
        )
