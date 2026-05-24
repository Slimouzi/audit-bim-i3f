"""Tests du module ``audit_bim.audit.comparator``."""

from __future__ import annotations

import json

import pytest

from audit_bim.audit.comparator import (
    ChangeType,
    changes_by_type,
    compare_audits,
    compare_audits_from_files,
    load_findings_from_json,
    summarize_changes,
)
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme


def _f(
    uuid: str | None, theme: Theme, et: ErrorType, sev: Severity, ifc_type: str = "IfcWall"
) -> Finding:
    return Finding(
        theme=theme,
        severity=sev,
        error_type=et,
        element_uuid=uuid,
        ifc_type=ifc_type,
    )


class TestCompareAudits:
    def test_all_resolved(self):
        old = [_f("W1", Theme.CLASSIFICATION, ErrorType.CLASSIFICATION_MISSING, Severity.MEDIUM)]
        new: list[Finding] = []
        entries = compare_audits(old, new)
        assert len(entries) == 1
        assert entries[0].change == ChangeType.RESOLVED

    def test_all_new(self):
        old: list[Finding] = []
        new = [_f("W1", Theme.CLASSIFICATION, ErrorType.CLASSIFICATION_MISSING, Severity.HIGH)]
        entries = compare_audits(old, new)
        assert len(entries) == 1
        assert entries[0].change == ChangeType.NEW
        # Le finding renvoyé pour NEW est celui de ``new``
        assert entries[0].finding.severity == Severity.HIGH

    def test_all_persistent(self):
        f = _f("W1", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.MEDIUM)
        entries = compare_audits([f], [f])
        assert len(entries) == 1
        assert entries[0].change == ChangeType.PERSISTENT

    def test_mixed_changes(self):
        # 3 anciens : W1, W2, W3. 3 nouveaux : W2, W3, W4
        # → W1 RESOLVED, W4 NEW, W2 et W3 PERSISTENT
        old = [
            _f("W1", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.MEDIUM),
            _f("W2", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.MEDIUM),
            _f("W3", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.MEDIUM),
        ]
        new = [
            _f("W2", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.MEDIUM),
            _f("W3", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.MEDIUM),
            _f("W4", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.MEDIUM),
        ]
        entries = compare_audits(old, new)
        by_change = {e.finding.element_uuid: e.change for e in entries}
        assert by_change["W1"] == ChangeType.RESOLVED
        assert by_change["W4"] == ChangeType.NEW
        assert by_change["W2"] == ChangeType.PERSISTENT
        assert by_change["W3"] == ChangeType.PERSISTENT

    def test_signature_differentiates_error_types(self):
        # Même élément, 2 types d'erreur différents → 2 entrées distinctes
        old = [
            _f("W1", Theme.CLASSIFICATION, ErrorType.CLASSIFICATION_MISSING, Severity.MEDIUM),
        ]
        new = [
            _f("W1", Theme.PROPERTY_MISSING, ErrorType.PROPERTY_MISSING, Severity.MEDIUM),
        ]
        entries = compare_audits(old, new)
        assert len(entries) == 2
        types = {e.change for e in entries}
        assert types == {ChangeType.RESOLVED, ChangeType.NEW}

    def test_project_finding_signature_uses_ifc_type(self):
        # uuid None → signature basée sur ifc_type
        old = [
            _f(
                None,
                Theme.SPATIAL_HIERARCHY,
                ErrorType.SPATIAL_ORPHAN,
                Severity.CRITICAL,
                ifc_type="IfcSite",
            )
        ]
        new = [
            _f(
                None,
                Theme.SPATIAL_HIERARCHY,
                ErrorType.SPATIAL_ORPHAN,
                Severity.CRITICAL,
                ifc_type="IfcSite",
            )
        ]
        entries = compare_audits(old, new)
        assert len(entries) == 1
        assert entries[0].change == ChangeType.PERSISTENT


class TestSummarizeChanges:
    def test_progress_score_positive_when_resolved_more(self):
        old = [
            _f(f"W{i}", Theme.CLASSIFICATION, ErrorType.CLASSIFICATION_MISSING, Severity.MEDIUM)
            for i in range(10)
        ]
        new = [
            _f(f"W{i}", Theme.CLASSIFICATION, ErrorType.CLASSIFICATION_MISSING, Severity.MEDIUM)
            for i in range(2)  # 8 résolus, 0 nouveau, 2 persistants
        ]
        entries = compare_audits(old, new)
        s = summarize_changes(entries)
        assert s["by_change"]["resolved"] == 8
        assert s["by_change"]["new"] == 0
        assert s["by_change"]["persistent"] == 2
        assert s["progress_score"] > 0  # 8 / 10

    def test_progress_score_negative_when_regressions(self):
        old = [
            _f("W1", Theme.CLASSIFICATION, ErrorType.CLASSIFICATION_MISSING, Severity.MEDIUM),
        ]
        new = [
            _f("W1", Theme.CLASSIFICATION, ErrorType.CLASSIFICATION_MISSING, Severity.MEDIUM),
            _f("W2", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.HIGH),
            _f("W3", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.HIGH),
        ]
        entries = compare_audits(old, new)
        s = summarize_changes(entries)
        assert s["by_change"]["new"] == 2
        assert s["progress_score"] < 0  # (0 - 2) / 3 = -0.67

    def test_by_change_x_severity(self):
        old = [_f("W1", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.HIGH)]
        new = [
            _f("W2", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.LOW),
            _f("W3", Theme.CLASSIFICATION, ErrorType.CLASSIFICATION_MISSING, Severity.MEDIUM),
        ]
        s = summarize_changes(compare_audits(old, new))
        assert s["by_change_x_severity"]["resolved"]["HIGH"] == 1
        assert s["by_change_x_severity"]["new"]["LOW"] == 1
        assert s["by_change_x_severity"]["new"]["MEDIUM"] == 1


class TestLoadAndCompareFromFiles:
    def test_load_findings_from_json(self, tmp_path):
        path = tmp_path / "findings.json"
        f1 = _f("W1", Theme.CLASSIFICATION, ErrorType.CLASSIFICATION_MISSING, Severity.MEDIUM)
        path.write_text(
            json.dumps([f1.model_dump(mode="json")], ensure_ascii=False),
            encoding="utf-8",
        )
        loaded = load_findings_from_json(path)
        assert len(loaded) == 1
        assert loaded[0].element_uuid == "W1"

    def test_load_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_findings_from_json(tmp_path / "missing.json")

    def test_load_raises_on_invalid_format(self, tmp_path):
        path = tmp_path / "wrong.json"
        path.write_text('{"not": "a list"}', encoding="utf-8")
        with pytest.raises(ValueError, match="Format invalide"):
            load_findings_from_json(path)

    def test_compare_audits_from_files(self, tmp_path):
        f1 = _f("W1", Theme.CLASSIFICATION, ErrorType.CLASSIFICATION_MISSING, Severity.MEDIUM)
        f2 = _f("W2", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.HIGH)
        old_path = tmp_path / "old.json"
        new_path = tmp_path / "new.json"
        old_path.write_text(json.dumps([f1.model_dump(mode="json")]), encoding="utf-8")
        new_path.write_text(json.dumps([f2.model_dump(mode="json")]), encoding="utf-8")
        result = compare_audits_from_files(old_path, new_path)
        assert result["n_old_findings"] == 1
        assert result["n_new_findings"] == 1
        assert result["summary"]["by_change"]["resolved"] == 1
        assert result["summary"]["by_change"]["new"] == 1


class TestChangesByType:
    def test_groups_by_type(self):
        old = [_f("W1", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.MEDIUM)]
        new = [
            _f("W1", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.MEDIUM),
            _f("W2", Theme.NAMING_SPACE, ErrorType.NAMING_MISSING, Severity.MEDIUM),
        ]
        entries = compare_audits(old, new)
        grouped = changes_by_type(entries)
        assert len(grouped["persistent"]) == 1
        assert len(grouped["new"]) == 1
        assert len(grouped["resolved"]) == 0
