import pytest
from pydantic import ValidationError

from cosmya.audit.schema import (
    AuditResult,
    Finding,
    InvalidAuditResponseError,
    parse_audit_result,
)

VALID_JSON = """
{
    "summary": {"score": 72, "critical": 1, "high": 0, "medium": 0, "low": 0, "info": 0},
    "findings": [
        {
            "id": "COS-SEC-001",
            "severity": "critical",
            "category": "security",
            "title": "SQL injection",
            "file": "src/database.py",
            "line": 142,
            "confidence": 0.96,
            "description": "User input concatenated directly into a query.",
            "evidence": "cursor.execute('SELECT * FROM users WHERE id=' + user_id)",
            "impact": "Full database compromise.",
            "recommendation": "Use parameterized queries."
        }
    ]
}
"""


def test_parses_valid_json():
    result = parse_audit_result(VALID_JSON)
    assert result.summary.score == 72
    assert len(result.findings) == 1
    assert result.findings[0].id == "COS-SEC-001"


def test_recovers_from_markdown_code_fence():
    fenced = f"```json\n{VALID_JSON}\n```"
    result = parse_audit_result(fenced)
    assert result.summary.score == 72


def test_rejects_invalid_json():
    with pytest.raises(InvalidAuditResponseError):
        parse_audit_result("this is not json at all {")


def test_rejects_json_missing_required_fields():
    with pytest.raises(InvalidAuditResponseError):
        parse_audit_result('{"summary": {"score": 50, "critical": "not-a-number"}}')


def test_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        Finding(
            id="X-1",
            severity="high",
            category="bug",
            title="test",
            confidence=1.5,
            description="d",
            recommendation="r",
        )


def test_rejects_score_out_of_range():
    with pytest.raises(InvalidAuditResponseError):
        parse_audit_result('{"summary": {"score": 150}, "findings": []}')


def test_empty_findings_is_valid():
    result = parse_audit_result('{"summary": {"score": 100}, "findings": []}')
    assert result.findings == []


def test_never_executes_response_content(monkeypatch):
    """Guard against regressions: parsing must never eval() or exec() content."""
    malicious = '{"summary": {"score": 1}, "findings": [], "__proc__": "__import__(\'os\').system(\'echo pwned\')"}'
    # Should parse harmlessly (extra field ignored) and never execute anything.
    result = parse_audit_result(malicious)
    assert isinstance(result, AuditResult)
