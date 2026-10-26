"""supply-chain CLI — run the supply-chain checks over a tree of repos.

Exit code is deliberately NOT key-hygiene's "0 even with findings": nothing
pings a dead-man switch from this command's ExecStartPost, and the point of a
cooldown check is to be gateable — a HIGH here means a repo resolves without a
publish-age gate, which should be able to fail a pipeline. Findings below HIGH
report and exit 0; only a real error raises.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from estate.findings import Finding, Severity
from estate.notify import SlackNotConfigured, slack_route
from estate.report import Delta, slack_payload

from .cooldown import scan_tree

DEFAULT_ROOT = "~/code/rmai"
FAIL_AT = Severity.HIGH


def _emit(findings: list[Finding], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps([f.to_dict() for f in findings], indent=2))
        return
    if not findings:
        click.echo("no findings")
        return
    # Grouped worst-first: the top of the output is what has to be acted on.
    for severity in sorted({f.severity for f in findings}, reverse=True):
        group = [f for f in findings if f.severity == severity]
        click.echo(f"== {severity.name} ({len(group)}) ==")
        for f in sorted(group, key=lambda x: x.asset):
            click.echo(f"  {f.asset}: {f.summary}")
            click.echo(f"    actual:   {f.actual}")
            click.echo(f"    expected: {f.expected}")
            click.echo(f"    {f.evidence}")


@click.group()
def cli() -> None:
    """Supply-chain checks for the RMAI estate."""


@cli.command()
@click.option("--root", default=DEFAULT_ROOT, help="Tree to scan for uv repos.")
@click.option("--json", "as_json", is_flag=True)
@click.option(
    "--notify",
    is_flag=True,
    help="Post findings to Slack through the estate's canonical client (estate.notify).",
)
@click.option(
    "--fail-on",
    type=click.Choice(["never", "P0", "HIGH", "MED", "LOW"]),
    default="HIGH",
    help="Exit 2 if a finding at/above this severity is present. Default HIGH.",
)
def cooldown(root: str, as_json: bool, notify: bool, fail_on: str) -> None:
    """Report uv repos whose publish-age cooldown is missing, shadowed or stale.

    Two callers with opposite needs, so the exit contract is explicit:

    * A pipeline wants a gate. `--fail-on HIGH` (the default) exits 2, which is
      what this command was built for and what CI still relies on.
    * A systemd timer wants a reporter. `--notify --fail-on never` posts the
      findings and exits 0. Under a timer, exiting 2 on a finding would make
      "found a HIGH" and "the job did not run" indistinguishable — and because
      ExecStartPost only runs when ExecStart succeeded, it would also skip the
      hc-ping and trip the dead-man switch. That is a false "did not run"
      stacked on top of a true finding, so cron-alert@ is left to mean the job
      actually broke.
    """
    base = Path(root).expanduser()
    if not base.exists():
        # Deliberately still an error under --notify: a bad root is the job
        # breaking, and that belongs to cron-alert@, not to the findings channel.
        raise click.ClickException(f"no such path: {base}")
    findings = scan_tree(base)
    _emit(findings, as_json)

    if notify and not _notify(findings):
        # A reporter that could not alert is a broken job: exit non-zero so the
        # unit withholds its ExecStartPost hc-ping and the dead-man switch
        # fires (security-enu). Slack cannot report its own outage.
        sys.exit(1)

    if fail_on != "never":
        threshold = Severity.from_name(fail_on)
        worst = max((f.severity for f in findings), default=None)
        if worst is not None and worst >= threshold:
            click.echo(f"{threshold.name} or worse present: {worst.name}", err=True)
            sys.exit(2)


def _notify(findings: list[Finding]) -> bool:
    """Push findings to the estate's warning channel. False: the run is not healthy.

    A clean run posts nothing — a check that speaks every day gets muted, and
    then it is not there for the run that mattered. But the route is resolved
    even on a clean run: "nothing to say" and "no way to say it" must not exit
    the same way, or the misconfiguration surfaces only on the day it matters.
    """
    try:
        route = slack_route("warning")
    except SlackNotConfigured as exc:
        click.echo(f"notify: NOT CONFIGURED — {exc}", err=True)
        return False
    if not findings:
        return True
    # Reuse the estate's finding formatter so this reads like every other
    # check in the channel. Everything is "new" here: this command keeps no
    # baseline, so there is no delta to compute.
    payload = slack_payload(
        Delta(new=findings, resolved=[], escalated=[], still_open=[]),
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        title="Supply-chain cooldown",
    )
    if route.post(payload["text"], workflow="supply-chain cooldown"):
        click.echo("notify: slack posted")
        return True
    click.echo("notify: slack FAILED", err=True)
    return False


if __name__ == "__main__":
    cli()
