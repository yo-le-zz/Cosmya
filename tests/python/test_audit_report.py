import io

from rich.console import Console

from cosmya.audit.report import real_severity_counts, render_report
from cosmya.audit.schema import AuditResult, Finding, Severity, Summary


def _finding(severity: Severity, id_suffix: str) -> Finding:
    return Finding(
        id=f"COS-{id_suffix}",
        severity=severity,
        category="bug",
        title=f"Issue {id_suffix}",
        confidence=0.8,
        description="desc",
        recommendation="rec",
    )


def test_real_severity_counts_ignores_model_self_reported_summary():
    # Model claims 0 critical findings in `summary`, but the findings list
    # actually contains one. Rendering must trust the findings list.
    result = AuditResult(
        summary=Summary(score=90, critical=0, high=0, medium=0, low=0, info=0),
        findings=[_finding(Severity.CRITICAL, "1")],
    )
    counts = real_severity_counts(result)
    assert counts[Severity.CRITICAL] == 1


def test_render_report_with_no_findings_does_not_crash():
    console = Console(file=io.StringIO(), width=100)
    result = AuditResult(summary=Summary(score=100), findings=[])
    render_report(result, console=console)
    output = console.file.getvalue()
    assert "No findings" in output


def test_render_report_includes_all_findings():
    console = Console(file=io.StringIO(), width=100)
    result = AuditResult(
        summary=Summary(score=50),
        findings=[
            _finding(Severity.CRITICAL, "1"),
            _finding(Severity.LOW, "2"),
        ],
    )
    render_report(result, console=console)
    output = console.file.getvalue()
    assert "Issue 1" in output
    assert "Issue 2" in output
