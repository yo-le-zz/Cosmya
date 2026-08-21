"""Strict schema for the AI model's final audit result.

The model is instructed (see ``agent/prompts.py``) to return only JSON
matching this schema. Every response is validated here before it is ever
rendered or trusted -- an unvalidated/malformed response is never
displayed as if it were a legitimate finding.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Category(str, Enum):
    SECURITY = "security"
    BUG = "bug"
    LOGIC = "logic"
    ARCHITECTURE = "architecture"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    BAD_PRACTICE = "bad_practice"
    SUSPICIOUS = "suspicious"
    RELIABILITY = "reliability"
    DEPENDENCY = "dependency"
    OTHER = "other"


class Finding(BaseModel):
    id: str
    severity: Severity
    category: Category
    title: str
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    description: str
    evidence: str | None = None
    impact: str | None = None
    recommendation: str

    @field_validator("id")
    @classmethod
    def _id_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Finding id must not be empty.")
        return value


class Summary(BaseModel):
    score: int = Field(ge=0, le=100)
    critical: int = Field(ge=0, default=0)
    high: int = Field(ge=0, default=0)
    medium: int = Field(ge=0, default=0)
    low: int = Field(ge=0, default=0)
    info: int = Field(ge=0, default=0)


class AuditResult(BaseModel):
    """The full, validated output of one audit run."""

    summary: Summary
    findings: list[Finding] = Field(default_factory=list)

    # Note: if the model's self-reported `summary` counts disagree with the
    # actual `findings` list, we do not reject the response -- report.py
    # recomputes real counts from `findings` for display purposes.


class InvalidAuditResponseError(Exception):
    """Raised when the model's response cannot be parsed/validated as JSON
    matching :class:`AuditResult`, even after a corrective retry."""


def parse_audit_result(raw_text: str) -> AuditResult:
    """Parse and validate a model response as :class:`AuditResult`.

    Attempts one safe recovery step -- stripping a Markdown code fence some
    models wrap JSON in -- before giving up. Never evaluates or executes the
    response content; this is pure, inert JSON parsing.
    """
    import json

    candidate = raw_text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise InvalidAuditResponseError(
            f"Model response is not valid JSON: {exc}"
        ) from exc

    try:
        return AuditResult.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError, kept generic on purpose
        raise InvalidAuditResponseError(
            f"Model response did not match the required audit schema: {exc}"
        ) from exc
