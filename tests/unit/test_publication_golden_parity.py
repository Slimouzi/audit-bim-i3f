"""Parité **historique** : ``bim-publication`` reproduit les payloads du code
pré-shim (commit af230e6), figés en golden JSON.

Contrairement à ``test_publication_facade_parity`` (qui compare la façade au
package qu'elle appelle — validation du *câblage*), ce test compare la sortie de
``bim-publication`` à des **golden** générés depuis l'implémentation historique
(builders lisant ``reporting.theming``, prenant un ``AuditResult``). Égalité
intégrale ⇒ l'extraction n'a **rien changé** aux payloads BCF / Smart Views ni aux
plans.

Golden régénérables via ``tests/unit/golden/_generate_golden.py`` exécuté depuis
un worktree au commit af230e6.
"""

from __future__ import annotations

import json
from pathlib import Path

import bim_publication as pub

from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.extraction.model_data import ModelSnapshot

GOLDEN = Path(__file__).parent / "golden"
PREFIX = "I3F Audit — "
MODEL_ID = 1674450
TARGET = {"cloud_id": "33617", "project_id": "2698917", "model_id": "1674450"}


def _snapshot() -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "I3F"},
        model={"name": "DIEPPE.ifc"},
        elements=[
            {"uuid": "W1", "type": "IfcWallStandardCase", "name": "Mur porteur"},
            {"uuid": "D1", "type": "IfcDoor", "object_type": "Porte EI30"},
        ],
    ).index()


def _findings() -> list[Finding]:
    return [
        Finding(
            theme=Theme.CLASSIFICATION,
            severity=Severity.MEDIUM,
            error_type=ErrorType.CLASSIFICATION_MISSING,
            element_uuid="W1",
            ifc_type="IfcWallStandardCase",
            name="Mur",
            ref_cch="CCH-CLS-1",
        ),
        Finding(
            theme=Theme.PROPERTY_MISSING,
            severity=Severity.HIGH,
            error_type=ErrorType.PROPERTY_MISSING,
            element_uuid="W1",
            ifc_type="IfcWallStandardCase",
            name="Mur",
        ),
        Finding(
            theme=Theme.PROPERTY_MISSING,
            severity=Severity.LOW,
            error_type=ErrorType.PROPERTY_MISSING,
            element_uuid="D1",
            ifc_type="IfcDoor",
            name="Porte",
        ),
    ]


def _load(name: str):
    return json.loads((GOLDEN / name).read_text())


def _plan_dump(plan) -> dict:
    return {
        "kind": plan.kind.value,
        "target": plan.target,
        "summary": plan.summary,
        "items": plan.items,
        "risks": plan.risks,
    }


def test_bcf_payloads_match_pre_shim_golden():
    got = pub.build_bcf_payloads(_findings(), phase="AVP", prefix=PREFIX, model_id=MODEL_ID)
    assert got == _load("bcf_payloads.json")


def test_smartview_payloads_match_pre_shim_golden():
    ebu = _snapshot().element_by_uuid
    got = pub.build_smartview_payloads(
        _findings(), phase="AVP", prefix=PREFIX, model_id=MODEL_ID, element_by_uuid=ebu
    )
    assert got == _load("smartview_payloads.json")


def test_smartview_from_uuids_matches_pre_shim_golden():
    ebu = _snapshot().element_by_uuid
    got = pub.build_smartview_payload_from_uuids(
        ["W1", "W1", "D1"],
        title="Sélection",
        color="#123456",
        model_id=MODEL_ID,
        element_by_uuid=ebu,
    )
    assert got == _load("smartview_from_uuids.json")


def test_prepare_bcf_matches_pre_shim_golden():
    plan = pub.prepare_bcf(_findings(), phase="AVP", target=TARGET)
    assert _plan_dump(plan) == _load("prepare_bcf.json")


def test_prepare_smart_views_matches_pre_shim_golden():
    ebu = _snapshot().element_by_uuid
    plan = pub.prepare_smart_views(_findings(), phase="AVP", target=TARGET, element_by_uuid=ebu)
    assert _plan_dump(plan) == _load("prepare_smart_views.json")


def test_prepare_smart_view_from_filter_matches_pre_shim_golden():
    plan = pub.prepare_smart_view_from_filter(
        ["W1", "D1"], name="Sélection", target=TARGET, description="note"
    )
    assert _plan_dump(plan) == _load("prepare_smart_view_from_filter.json")
