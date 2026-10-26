"""Slack delivery and the self-hosted Healthchecks dead-man ping.

Slack: ONE entry point for this repo. The canonical client is
infra-shared/slack-notify.sh — it owns credential selection (SLACK_BOT_TOKEN,
else the per-severity webhooks), channel routing (alert-channels.conf) and the
`ok`-field check chat.postMessage needs because it answers HTTP 200 to
invalid_auth. Nothing here re-derives any of that; Python decides only whether
there is something to say. The direct-webhook branch exists for the one runner
that cannot see infra-shared — GitHub Actions — and reads the same per-severity
variable names cron-secrets.env uses, so there is one vocabulary, not three
(security-yun step 2).

An unset credential is an error, not a skip. Callers resolve the route BEFORE
looking at their payload, so a quiet day and a missing credential never look the
same (security-enu).

Healthchecks: both consumers rely on the dead-man switch to distinguish "ran and found
nothing" from "did not run at all" — a quiet Slack channel means the same thing
in either case, so the ping is the only signal that separates them. Ping only
after a run genuinely completed; pinging on a broken run is what makes a dead
job look alive.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SLACK_NOTIFY = Path("/tank/services/active_services/infra-shared/slack-notify.sh")
# slack-notify.sh retries curl five times at --max-time 60; give it room to
# finish rather than declaring a slow delivery a failed one.
CLIENT_TIMEOUT = 360.0
WEBHOOK_TIMEOUT = 15.0


class SlackNotConfigured(RuntimeError):
    """No way to deliver: the canonical client is absent and no webhook is set.

    Deliberately not a silent skip. A run that could not have alerted has not
    proved anything, however clean its findings.
    """


@dataclass(frozen=True)
class SlackRoute:
    """A resolved way to post one severity. Resolve first; post only if needed."""

    severity: str
    script: Path | None = None
    webhook: str = ""

    def post(self, text: str, *, workflow: str) -> bool:
        """Deliver `text`. True only when the client or Slack confirmed it landed."""
        if self.script is not None:
            return _post_via_client(self.script, self.severity, workflow, text)
        return _post_via_webhook(self.webhook, text)


def slack_route(severity: str = "warning") -> SlackRoute:
    """Find how this host can post `severity`, or raise SlackNotConfigured.

    Order: the canonical client at SLACK_NOTIFY_SH (default: infra-shared's
    deploy path), else the per-severity webhook SLACK_WEBHOOK_<SEVERITY>.
    """
    script = Path(os.environ.get("SLACK_NOTIFY_SH") or DEFAULT_SLACK_NOTIFY)
    if script.is_file():
        return SlackRoute(severity=severity, script=script)
    var = f"SLACK_WEBHOOK_{severity.upper()}"
    webhook = os.environ.get(var, "")
    if webhook:
        return SlackRoute(severity=severity, webhook=webhook)
    raise SlackNotConfigured(
        f"no Slack route for severity {severity!r}: {script} is not present and {var} is unset"
    )


def post_slack(text: str, *, severity: str = "warning", workflow: str) -> bool:
    """Resolve and post in one step. Raises SlackNotConfigured; returns delivery."""
    return slack_route(severity).post(text, workflow=workflow)


def _post_via_client(script: Path, severity: str, workflow: str, text: str) -> bool:
    # argv contract: <severity> <workflow> <error_message> [node] [error_code] [service]
    # An empty node lets the script default to hostname(); REPORT replaces its
    # CRON_FAILURE default because these are findings, not a crashed unit. The
    # script's own stderr ("Alert sent" / "WARNING: Slack rejected") passes
    # through to the journal or Actions log untouched.
    try:
        completed = subprocess.run(
            [str(script), severity, workflow, text, "", "REPORT"],
            timeout=CLIENT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _post_via_webhook(webhook: str, text: str) -> bool:
    import httpx

    try:
        with httpx.Client(timeout=WEBHOOK_TIMEOUT) as client:
            resp = client.post(webhook, json={"text": text})
    except Exception:  # noqa: BLE001 - any transport failure is a non-delivery
        return False
    # Incoming webhooks answer the literal body `ok` on success and a bare error
    # name otherwise (no_service = deleted, invalid_token = revoked,
    # invalid_payload). Trust nothing but the one success shape.
    return resp.status_code == 200 and resp.text.strip() == "ok"


def ping_healthcheck(url: str, timeout: float = 10.0) -> bool:
    """GET the healthchecks ping URL. Best-effort: never raises.

    Returns whether the ping landed, so a caller that cares can report it. A
    failed ping is not a failed run — the check will alert on its own once the
    grace window passes.
    """
    if not url:
        return False

    import httpx

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            return resp.status_code < 400
    except Exception:  # noqa: BLE001 - dead-man ping is best-effort
        return False
