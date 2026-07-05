"""Parité de la façade ``audit_bim.audit.engine`` sur ``bim-audit-engine``.

Deux garanties, conformément à la décision CTO :

- **Identité stricte** de ``AuditResult`` : ``audit_bim.audit.engine.AuditResult``
  EST ``bim_audit_engine.AuditResult`` (même objet, isinstance-safe, dump
  inchangé).
- **Équivalence comportementale** de ``run_audit`` (JAMAIS identité de la
  fonction) : la façade injecte ``I3F_RULES`` dans le moteur générique et produit
  exactement les mêmes findings, dans le même ordre, que l'ancienne
  implémentation en dur (6 règles I3F + même tri déterministe).
"""

from __future__ import annotations

import bim_audit_engine

from audit_bim.audit.engine import I3F_RULES, AuditResult, run_audit
from audit_bim.audit.findings import Severity
from audit_bim.audit.rules import (
    audit_classifications,
    audit_lists,
    audit_naming,
    audit_properties,
    audit_spatial,
    audit_uniqueness,
)
from audit_bim.requirements.models import BIMPhase


def _finding_projection(findings):
    """Projection stable et comparable d'une liste de findings."""
    return [
        (
            f.severity.value,
            f.theme.value,
            f.error_type.value,
            f.ifc_type or "",
            f.name or "",
            f.element_uuid or "",
            f.expected or "",
            f.actual or "",
        )
        for f in findings
    ]


def _legacy_run_audit(snap, catalog, phase):
    """Réimplémentation VERBATIM de l'ancien ``run_audit`` en dur (pré-façade).

    Ordre historique + tri identiques. ``audit_naming`` est appelé avec 2 args
    comme avant l'ajout du paramètre ``phase`` ignoré (résultat identique)."""
    findings = []
    findings.extend(audit_spatial(snap, catalog, phase))
    findings.extend(audit_naming(snap, catalog))  # ancienne signature 2-args
    findings.extend(audit_classifications(snap, catalog, phase))
    findings.extend(audit_properties(snap, catalog, phase))
    findings.extend(audit_uniqueness(snap, catalog, phase))
    findings.extend(audit_lists(snap, catalog, phase))
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
    return findings


class TestAuditResultIdentity:
    def test_auditresult_is_the_package_class(self):
        # Identité STRICTE : le ré-export est le même objet.
        assert AuditResult is bim_audit_engine.AuditResult


class TestRunAuditIsFacadeNotIdentity:
    def test_run_audit_is_not_the_package_function(self):
        # La façade lie I3F_RULES : ce n'est PAS la fonction du package.
        assert run_audit is not bim_audit_engine.run_audit

    def test_i3f_rules_order_and_membership(self):
        assert I3F_RULES == (
            audit_spatial,
            audit_naming,
            audit_classifications,
            audit_properties,
            audit_uniqueness,
            audit_lists,
        )

    def test_audit_naming_accepts_phase_without_using_it(self, snapshot_minimal, catalog):
        # Signature normalisée (snap, catalog, phase) ; phase ignoré => même sortie.
        without = _finding_projection(audit_naming(snapshot_minimal, catalog))
        with_phase = _finding_projection(audit_naming(snapshot_minimal, catalog, BIMPhase.AVP))
        assert without == with_phase


class TestRunAuditEquivalence:
    def test_equivalent_to_legacy_hardcoded_run(self, snapshot_minimal, catalog):
        for phase in (BIMPhase.AVP, BIMPhase.DCE):
            result = run_audit(snapshot_minimal, catalog, phase)
            legacy = _legacy_run_audit(snapshot_minimal, catalog, phase)
            assert isinstance(result, AuditResult)
            # Même contexte, mêmes findings, même ordre.
            assert result.phase == phase
            assert result.catalog is catalog
            assert result.snapshot is snapshot_minimal
            assert _finding_projection(result.findings) == _finding_projection(legacy)

    def test_summary_dump_unchanged(self, snapshot_minimal, catalog):
        import json

        result = run_audit(snapshot_minimal, catalog, BIMPhase.AVP)
        s = result.summary()
        json.dumps(s)  # sérialisable
        # phase reste la valeur d'Enum, comme l'ancien self.phase.value.
        assert s["phase"] == BIMPhase.AVP.value
