"""Moteur d'audit BIM I3F : règles + agrégation."""

from .engine import AuditResult, run_audit
from .findings import ErrorType, Finding, Severity, Theme, severity_color

__all__ = [
    "AuditResult",
    "ErrorType",
    "Finding",
    "Severity",
    "Theme",
    "run_audit",
    "severity_color",
]
