"""Tests du module ``audit_bim.audit.findings``."""

from __future__ import annotations

from audit_bim.audit.findings import (
    ErrorType,
    Finding,
    Severity,
    Theme,
    severity_color,
)


class TestSeverity:
    def test_ordered_returns_critical_first(self):
        ordered = Severity.ordered()
        assert ordered[0] == Severity.CRITICAL
        assert ordered[-1] == Severity.INFO

    def test_ordered_contains_all_severities(self):
        assert set(Severity.ordered()) == set(Severity)


class TestSeverityColor:
    def test_traffic_light_palette(self):
        assert severity_color(Severity.HIGH) == "DC3545"
        assert severity_color(Severity.MEDIUM) == "FF8C00"
        assert severity_color(Severity.LOW) == "28A745"

    def test_critical_red_dark(self):
        assert severity_color(Severity.CRITICAL) == "8B0000"

    def test_info_blue(self):
        assert severity_color(Severity.INFO) == "4682B4"


class TestFinding:
    def test_short_label_with_name(self, sample_finding):
        assert sample_finding.short_label() == "IfcSpace — salle de bain"

    def test_short_label_falls_back_to_uuid(self):
        f = Finding(
            theme=Theme.NAMING_SPACE,
            severity=Severity.LOW,
            error_type=ErrorType.NAMING_MISSING,
            element_uuid="ABC",
            ifc_type="IfcDoor",
        )
        assert f.short_label() == "IfcDoor — ABC"

    def test_json_roundtrip(self, sample_finding):
        d = sample_finding.model_dump(mode="json")
        assert d["severity"] == "MEDIUM"
        assert d["error_type"] == "naming_not_in_list"
        # Reconstruction
        f2 = Finding.model_validate(d)
        assert f2 == sample_finding


class TestEnumValues:
    """Les valeurs string des Enum sont contractuelles (sérialisation JSON)."""

    def test_severity_values_are_uppercase(self):
        for s in Severity:
            assert s.value == s.value.upper()

    def test_error_type_values_are_snake_case(self):
        for et in ErrorType:
            assert et.value == et.value.lower()
            assert " " not in et.value
