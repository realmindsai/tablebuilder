# ABOUTME: Health report generator for the tablebuilder system.
# ABOUTME: Formats credential status, selector health, timings, and quirks into a readable report.

from __future__ import annotations

from tablebuilder.config import ConfigError, load_config
from tablebuilder.knowledge import KnowledgeBase
from tablebuilder.selectors import ALL_SELECTORS


def check_credentials() -> bool:
    """Return True if credentials can be loaded, False otherwise."""
    try:
        load_config()
        return True
    except ConfigError:
        return False


def run_doctor(knowledge: KnowledgeBase, credentials_ok: bool) -> str:
    """Build and return a formatted health report string.

    Args:
        knowledge: The knowledge base to report on.
        credentials_ok: Whether ABS credentials were found.
    """
    lines: list[str] = []
    summary = knowledge.summary()

    lines.append("TableBuilder Doctor")
    lines.append("==================")

    # -- Configuration section --
    lines.append("Configuration:")
    if credentials_ok:
        lines.append("  Credentials: Found in ~/.tablebuilder/.env")
    else:
        lines.append(
            "  Credentials: NOT FOUND — create ~/.tablebuilder/.env "
            "with TABLEBUILDER_USER_ID and TABLEBUILDER_PASSWORD"
        )

    run_count = summary["run_count"]
    last_run = summary["last_run"]
    if last_run:
        # Trim the ISO timestamp to human-friendly format (YYYY-MM-DD HH:MM)
        display_time = last_run[:16].replace("T", " ")
        lines.append(f"  Knowledge base: {run_count} runs (last: {display_time})")
    else:
        lines.append(f"  Knowledge base: {run_count} runs")

    # -- Selector Health section --
    lines.append("")
    lines.append("Selector Health:")
    total_selectors = len(ALL_SELECTORS)
    fallback_count = summary["selectors_using_fallback"]
    lines.append(f"  {total_selectors} selectors registered")
    if fallback_count == 0:
        lines.append(
            f"  {fallback_count} using fallback selectors (all using primary)"
        )
    else:
        lines.append(f"  {fallback_count} using fallback selectors")

    # -- Timings section --
    lines.append("")
    lines.append("Timings:")
    if not knowledge.timings:
        lines.append("  No timing data yet")
    else:
        for operation, data in sorted(knowledge.timings.items()):
            avg = data["avg_duration"]
            samples = data["sample_count"]
            lines.append(f"  {operation}: ~{avg:.1f}s avg ({samples} samples)")

    # -- Dataset Quirks section --
    lines.append("")
    lines.append("Dataset Quirks:")
    if not knowledge.dataset_quirks:
        lines.append("  None recorded")
    else:
        for quirk in knowledge.dataset_quirks:
            lines.append(
                f"  {quirk['dataset_name']} [{quirk['quirk_type']}]: "
                f"{quirk['description']}"
            )

    # -- Status line --
    lines.append("")
    if credentials_ok:
        lines.append("Status: Healthy")
    else:
        lines.append("Status: Needs Configuration")

    return "\n".join(lines)
