"""Pydantic models shared across every mcp-doctor module."""

from mcp_doctor.model.eval import (
    SELECTION_KINDS,
    ArgumentCheck,
    CaseKind,
    CaseOutcome,
    CaseSuite,
    ConfusionCell,
    EvalCase,
    EvalResult,
    EvalScores,
    Rate,
    ToolScore,
)
from mcp_doctor.model.finding import (
    SEVERITY_ORDER,
    Finding,
    LintResult,
    Problem,
    Severity,
    at_least,
    severity_rank,
)
from mcp_doctor.model.health import CiReport, HealthPoint, HealthScore
from mcp_doctor.model.tool import (
    InspectResult,
    ServerInfo,
    ToolAnnotations,
    ToolSpec,
    canonical_json,
    tool_digest,
)

__all__ = [
    "SELECTION_KINDS",
    "SEVERITY_ORDER",
    "ArgumentCheck",
    "CaseKind",
    "CaseOutcome",
    "CaseSuite",
    "CiReport",
    "ConfusionCell",
    "EvalCase",
    "EvalResult",
    "EvalScores",
    "Finding",
    "HealthPoint",
    "HealthScore",
    "InspectResult",
    "LintResult",
    "Problem",
    "Rate",
    "ServerInfo",
    "Severity",
    "ToolAnnotations",
    "ToolScore",
    "ToolSpec",
    "at_least",
    "canonical_json",
    "severity_rank",
    "tool_digest",
]
