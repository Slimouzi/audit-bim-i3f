"""Parité de façade : audit-bim délègue à ``bim-publication`` à l'identique.

Après extraction, ``audit_bim.bcf.builder`` / ``audit_bim.smartview.builder`` et
les ``prepare_*`` des planners sont des **façades** au-dessus de
``bim_publication``. Ces tests garantissent que les payloads / plans produits
côté audit sont **identiques** à ceux du package sur les mêmes entrées.
"""

from __future__ import annotations

import bim_publication as pub

from audit_bim.audit.engine import AuditResult
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.bcf import builder as ab_bcf
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import BIMPhase
from audit_bim.smartview import builder as ab_sv


def _audit() -> AuditResult:
    snap = ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        elements=[{"uuid": "W1", "type": "IfcWallStandardCase", "name": "Mur porteur"}],
    ).index()
    findings = [
        Finding(
            theme=Theme.CLASSIFICATION,
            severity=Severity.MEDIUM,
            error_type=ErrorType.CLASSIFICATION_MISSING,
            element_uuid="W1",
            ifc_type="IfcWallStandardCase",
            name="Mur",
        ),
        Finding(
            theme=Theme.PROPERTY_MISSING,
            severity=Severity.HIGH,
            error_type=ErrorType.PROPERTY_MISSING,
            element_uuid="W1",
            ifc_type="IfcWallStandardCase",
            name="Mur",
        ),
    ]
    return AuditResult(phase=BIMPhase.AVP, catalog=None, snapshot=snap, findings=findings)


TARGET = {"cloud_id": "33617", "project_id": "2698917", "model_id": "1674450"}


def test_bcf_builder_facade_matches_package():
    res = _audit()
    assert ab_bcf.build_bcf_payloads(res, model_id=1674450) == pub.build_bcf_payloads(
        res.findings, phase=res.phase.value, model_id=1674450
    )


def test_smartview_builder_facade_matches_package():
    res = _audit()
    ebu = res.snapshot.element_by_uuid
    assert ab_sv.build_smartview_payloads(res, model_id=1674450) == pub.build_smartview_payloads(
        res.findings, phase=res.phase.value, model_id=1674450, element_by_uuid=ebu
    )


def test_from_uuids_is_direct_reexport():
    assert ab_sv.build_smartview_payload_from_uuids is pub.build_smartview_payload_from_uuids


def test_prepare_bcf_facade_matches_package():
    from audit_bim.actions import prepare_bcf

    res = _audit()
    facade = prepare_bcf(res, target=TARGET)
    direct = pub.prepare_bcf(res.findings, phase=res.phase.value, target=TARGET)
    assert facade.kind == direct.kind
    assert facade.items == direct.items
    assert facade.summary == direct.summary
    assert facade.risks == direct.risks


def test_prepare_smart_views_facade_matches_package():
    from audit_bim.actions import prepare_smart_views

    res = _audit()
    ebu = res.snapshot.element_by_uuid
    facade = prepare_smart_views(res, target=TARGET)
    direct = pub.prepare_smart_views(
        res.findings, phase=res.phase.value, target=TARGET, element_by_uuid=ebu
    )
    assert facade.kind == direct.kind
    assert facade.items == direct.items
    assert facade.summary == direct.summary
