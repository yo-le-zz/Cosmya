"""Renders a validated :class:`AuditResult` as a readable Rich terminal report.

The AI never controls terminal color or layout -- this module owns that
entirely, mapping severities to fixed colors.
"""

from __future__ import annotations

from collections import Counter

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cosmya.audit.schema import AuditResult, Finding, Severity

_SEVERITY_COLOR = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
    Severity.INFO: "grey62",
}

_SEVERITY_ORDER = [
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
]


def real_severity_counts(result: AuditResult) -> Counter:
    """Recompute severity counts from the actual findings list.

    We never trust the model's self-reported summary counts for display;
    they are recomputed here so the rendered report is always internally
    consistent with the findings actually shown.
    """
    return Counter(f.severity for f in result.findings)


def render_summary_table(result: AuditResult) -> Table:
    counts = real_severity_counts(result)
    table = Table(title="Audit Summary", show_header=True, header_style="bold")
    table.add_column("Score", justify="center")
    for severity in _SEVERITY_ORDER:
        table.add_column(severity.value.upper(), justify="center")

    row = [str(result.summary.score)]
    for severity in _SEVERITY_ORDER:
        color = _SEVERITY_COLOR[severity]
        row.append(f"[{color}]{counts.get(severity, 0)}[/{color}]")
    table.add_row(*row)
    return table


def render_finding(finding: Finding) -> Panel:
    color = _SEVERITY_COLOR[finding.severity]
    location = (
        f"{finding.file}:{finding.line}"
        if finding.file and finding.line
        else (finding.file or "")
    )

    body_parts = [Markdown(f"**Description**\n\n{finding.description}")]
    if finding.evidence:
        body_parts.append(Markdown(f"**Evidence**\n\n```\n{finding.evidence}\n```"))
    if finding.impact:
        body_parts.append(Markdown(f"**Impact**\n\n{finding.impact}"))
    body_parts.append(Markdown(f"**Recommendation**\n\n{finding.recommendation}"))

    title = Text()
    title.append(f"{finding.severity.value.upper()} ", style=color)
    title.append(f"— {finding.title}")
    subtitle = (
        f"{location}  ·  confidence {finding.confidence:.0%}"
        if location
        else f"confidence {finding.confidence:.0%}"
    )

    return Panel(
        Group(*body_parts),
        title=title,
        subtitle=subtitle,
        border_style=color,
        title_align="left",
        subtitle_align="right",
    )


def render_report(result: AuditResult, console: Console | None = None) -> None:
    console = console or Console()
    console.print(render_summary_table(result))
    console.print()

    if not result.findings:
        console.print("[green]No findings were reported.[/green]")
        return

    ordered = sorted(
        result.findings,
        key=lambda f: (_SEVERITY_ORDER.index(f.severity), -f.confidence),
    )
    for finding in ordered:
        console.print(render_finding(finding))
        console.print()
