"""Orchestrateur d'audit : joue toutes les règles et agrège les findings."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from ..extraction.model_data import ModelSnapshot
from ..requirements.models import BIMPhase, RequirementsCatalog
from .findings import Finding, Severity, Theme
from .rules import (
    audit_classifications,
    audit_lists,
    audit_naming,
    audit_properties,
    audit_spatial,
    audit_uniqueness,
)


@dataclass
class AuditResult:
    """Résultat complet d'un audit (catalogue + snapshot + findings)."""

    phase: BIMPhase
    catalog: RequirementsCatalog
    snapshot: ModelSnapshot
    findings: list[Finding] = field(default_factory=list)

    # ── Statistiques ────────────────────────────────────────────────────────

    def count_by_theme(self) -> dict[str, int]:
        return dict(Counter(f.theme.value for f in self.findings))

    def count_by_severity(self) -> dict[str, int]:
        return dict(Counter(f.severity.value for f in self.findings))

    def count_by_error_type(self) -> dict[str, int]:
        return dict(Counter(f.error_type.value for f in self.findings))

    def count_by_ifc_type(self) -> dict[str, int]:
        return dict(Counter((f.ifc_type or "?") for f in self.findings))

    def filter(
        self,
        *,
        theme: Optional[str] = None,
        severity: Optional[str] = None,
        error_type: Optional[str] = None,
        ifc_type: Optional[str] = None,
    ) -> list[Finding]:
        out = list(self.findings)
        if theme:
            out = [f for f in out if f.theme.value == theme]
        if severity:
            out = [f for f in out if f.severity.value == severity]
        if error_type:
            out = [f for f in out if f.error_type.value == error_type]
        if ifc_type:
            out = [f for f in out if (f.ifc_type or "") == ifc_type]
        return out

    def conformity_rate(self) -> float:
        """Taux de conformité grossier : 1 - (anomalies pondérées / total éléments)."""
        weights = {
            Severity.CRITICAL: 5,
            Severity.HIGH: 3,
            Severity.MEDIUM: 1,
            Severity.LOW: 0.3,
            Severity.INFO: 0.0,
        }
        n_elements = max(1, len(self.snapshot.element_by_uuid))
        weighted = sum(weights.get(f.severity, 1) for f in self.findings)
        return max(0.0, min(1.0, 1.0 - (weighted / (n_elements * 3))))

    def summary(self) -> dict:
        return {
            "phase": self.phase.value,
            "n_findings": len(self.findings),
            "by_severity": self.count_by_severity(),
            "by_theme": self.count_by_theme(),
            "by_error_type": self.count_by_error_type(),
            "conformity_rate": round(self.conformity_rate(), 3),
            "model": self.snapshot.summary(),
        }


def run_audit(
    snap: ModelSnapshot,
    catalog: RequirementsCatalog,
    phase: BIMPhase,
) -> AuditResult:
    """Exécute toutes les règles d'audit dans l'ordre et trie les findings."""
    findings: list[Finding] = []
    findings.extend(audit_spatial(snap, catalog, phase))
    findings.extend(audit_naming(snap, catalog))
    findings.extend(audit_classifications(snap, catalog, phase))
    findings.extend(audit_properties(snap, catalog, phase))
    findings.extend(audit_uniqueness(snap, catalog, phase))
    findings.extend(audit_lists(snap, catalog, phase))

    # Tri stable : sévérité décroissante puis thème puis type
    sev_order = {s: i for i, s in enumerate(Severity.ordered())}
    findings.sort(
        key=lambda f: (
            sev_order.get(f.severity, 99),
            f.theme.value,
            f.error_type.value,
            f.ifc_type or "",
            f.name or "",
        )
    )

    return AuditResult(phase=phase, catalog=catalog, snapshot=snap, findings=findings)
