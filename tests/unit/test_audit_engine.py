"""Tests du module ``audit_bim.audit.engine``."""
from __future__ import annotations

from audit_bim.audit.engine import AuditResult, run_audit
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.requirements.models import BIMPhase


class TestAuditResult:
    def _build(self, snapshot_minimal, catalog, findings):
        return AuditResult(
            phase=BIMPhase.AVP,
            catalog=catalog,
            snapshot=snapshot_minimal,
            findings=findings,
        )

    def test_count_by_severity(self, snapshot_minimal, catalog):
        findings = [
            Finding(theme=Theme.NAMING_SPACE, severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_MISSING, ifc_type="IfcSpace"),
            Finding(theme=Theme.NAMING_SPACE, severity=Severity.LOW,
                    error_type=ErrorType.NAMING_TOO_LONG, ifc_type="IfcSpace"),
            Finding(theme=Theme.CLASSIFICATION, severity=Severity.HIGH,
                    error_type=ErrorType.CLASSIFICATION_MISSING, ifc_type="IfcDoor"),
        ]
        r = self._build(snapshot_minimal, catalog, findings)
        assert r.count_by_severity() == {"HIGH": 2, "LOW": 1}

    def test_count_by_theme(self, snapshot_minimal, catalog):
        findings = [
            Finding(theme=Theme.NAMING_SPACE, severity=Severity.LOW,
                    error_type=ErrorType.NAMING_MISSING, ifc_type="IfcSpace"),
            Finding(theme=Theme.NAMING_SPACE, severity=Severity.LOW,
                    error_type=ErrorType.NAMING_MISSING, ifc_type="IfcSpace"),
            Finding(theme=Theme.CLASSIFICATION, severity=Severity.LOW,
                    error_type=ErrorType.CLASSIFICATION_MISSING, ifc_type="IfcDoor"),
        ]
        r = self._build(snapshot_minimal, catalog, findings)
        assert r.count_by_theme() == {"Nommage Pièce": 2, "Classification IFC": 1}

    def test_filter_by_severity(self, snapshot_minimal, catalog):
        findings = [
            Finding(theme=Theme.NAMING_SPACE, severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_MISSING, ifc_type="IfcSpace"),
            Finding(theme=Theme.NAMING_SPACE, severity=Severity.LOW,
                    error_type=ErrorType.NAMING_TOO_LONG, ifc_type="IfcSpace"),
        ]
        r = self._build(snapshot_minimal, catalog, findings)
        high = r.filter(severity="HIGH")
        assert len(high) == 1
        assert high[0].severity == Severity.HIGH

    def test_filter_multiple_criteria(self, snapshot_minimal, catalog):
        findings = [
            Finding(theme=Theme.NAMING_SPACE, severity=Severity.HIGH,
                    error_type=ErrorType.NAMING_MISSING, ifc_type="IfcSpace"),
            Finding(theme=Theme.CLASSIFICATION, severity=Severity.HIGH,
                    error_type=ErrorType.CLASSIFICATION_MISSING, ifc_type="IfcDoor"),
        ]
        r = self._build(snapshot_minimal, catalog, findings)
        filtered = r.filter(severity="HIGH", theme="Classification IFC")
        assert len(filtered) == 1
        assert filtered[0].ifc_type == "IfcDoor"

    def test_conformity_rate_in_zero_one(self, snapshot_minimal, catalog):
        findings = [
            Finding(theme=Theme.NAMING_SPACE, severity=Severity.MEDIUM,
                    error_type=ErrorType.NAMING_MISSING, ifc_type="IfcSpace")
            for _ in range(5)
        ]
        r = self._build(snapshot_minimal, catalog, findings)
        rate = r.conformity_rate()
        assert 0.0 <= rate <= 1.0

    def test_conformity_zero_findings_is_one(self, snapshot_minimal, catalog):
        r = self._build(snapshot_minimal, catalog, [])
        assert r.conformity_rate() == 1.0

    def test_summary_json_compatible(self, snapshot_minimal, catalog):
        import json

        r = self._build(snapshot_minimal, catalog, [])
        s = r.summary()
        # Doit être sérialisable JSON
        json.dumps(s)
        assert "phase" in s
        assert "n_findings" in s


class TestRunAudit:
    def test_returns_audit_result(self, snapshot_minimal, catalog):
        result = run_audit(snapshot_minimal, catalog, BIMPhase.AVP)
        assert isinstance(result, AuditResult)
        assert result.phase == BIMPhase.AVP

    def test_findings_sorted_by_severity_first(self, snapshot_minimal, catalog):
        result = run_audit(snapshot_minimal, catalog, BIMPhase.AVP)
        # Sévérités décroissantes
        sev_order = {s: i for i, s in enumerate(Severity.ordered())}
        for prev, cur in zip(result.findings, result.findings[1:], strict=False):
            assert sev_order[prev.severity] <= sev_order[cur.severity]

    def test_avp_finds_some_findings(self, snapshot_minimal, catalog):
        # Le snapshot minimal n'a pas de classifs, pas de Psets sur les éléments
        # spatiaux → on devrait avoir des property_missing
        result = run_audit(snapshot_minimal, catalog, BIMPhase.AVP)
        assert len(result.findings) > 0
