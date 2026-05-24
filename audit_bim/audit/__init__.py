"""Moteur d'audit BIM I3F : règles + agrégation + comparaison."""

from .comparator import (
    ChangeEntry,
    ChangeType,
    compare_audits,
    compare_audits_from_files,
    summarize_changes,
)
from .engine import AuditResult, run_audit
from .findings import ErrorType, Finding, Severity, Theme, severity_color

__all__ = [
    "AuditResult",
    "ChangeEntry",
    "ChangeType",
    "ErrorType",
    "Finding",
    "Severity",
    "Theme",
    "compare_audits",
    "compare_audits_from_files",
    "run_audit",
    "severity_color",
    "summarize_changes",
]
