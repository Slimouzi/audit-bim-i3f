"""Parité **historique** : ``bim-publication`` reproduit les payloads du code
pré-shim (commit af230e6), figés en golden JSON.

Contrairement à ``test_publication_facade_parity`` (qui compare la façade au
package qu'elle appelle — validation du *câblage*), ce test compare la sortie de
``bim-publication`` à des **golden** générés depuis l'implémentation historique
(builders lisant ``reporting.theming``, prenant un ``AuditResult``). Égalité
intégrale ⇒ l'extraction n'a **rien changé** aux payloads BCF / Smart Views ni aux
plans.

**Une déviation volontaire depuis le lot B3** : ``originating_system`` vaut
``audit-bim-mcp`` dans les golden BCF, alors que le code pré-shim écrivait
``audit-bim-i3f``. La provenance a changé *après* l'extraction, délibérément —
elle nomme la distribution productrice, qui sert trois AMO.

Conséquence pour qui régénère : ``tests/unit/golden/_generate_golden.py``
exécuté depuis un worktree au commit af230e6 **réécrirait l'ancienne
provenance** et annulerait B3 sur 28 lignes, sans que rien d'autre ne bouge. Il
faut alors réappliquer la provenance courante — c'est le seul écart attendu
entre les golden et ce que produit af230e6.
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


# ── E11 : invariants STRUCTURELS indépendants (anti-tautologie) ───────────────
# Les tests ci-dessus comparent le builder à un golden régénéré par… le builder →
# tautologie. On épingle donc des invariants de payload **indépendants** (clés
# obligatoires, préfixe, format), vérifiés à la fois sur la sortie fraîche du
# builder ET sur le golden — un golden régénéré cassé échoue aussi.
_BCF_REQUIRED_KEYS = {
    "title",
    "description",
    "topic_type",
    "topic_status",
    "priority",
    "labels",
    "viewpoints",
    "models",
}
_SMARTVIEW_REQUIRED_KEYS = {"title", "format", "viewpoints", "models"}


def _assert_bcf_invariants(payloads):
    assert isinstance(payloads, list) and payloads
    for p in payloads:
        assert _BCF_REQUIRED_KEYS <= set(p), f"clés BCF manquantes : {_BCF_REQUIRED_KEYS - set(p)}"
        assert isinstance(p["title"], str) and p["title"].startswith(PREFIX)
        assert isinstance(p["topic_type"], str) and p["topic_type"]
        assert isinstance(p["topic_status"], str) and p["topic_status"]
        assert isinstance(p["labels"], list)
        assert isinstance(p["models"], list) and MODEL_ID in p["models"]


def _assert_smartview_invariants(payloads):
    items = payloads if isinstance(payloads, list) else [payloads]
    assert items
    for p in items:
        assert _SMARTVIEW_REQUIRED_KEYS <= set(p)
        assert p["format"] == "bimdata-smartview"
        assert isinstance(p["models"], list) and MODEL_ID in p["models"]


def _assert_plan_invariants(dump: dict, kind: str):
    assert dump["kind"] == kind
    assert set(dump["target"]) >= {"cloud_id", "project_id", "model_id"}
    assert dump["target"] == TARGET
    assert isinstance(dump["items"], list)
    assert isinstance(dump["summary"], dict)
    assert isinstance(dump["risks"], list)


def test_bcf_payload_invariants_hold_on_builder_and_golden():
    got = pub.build_bcf_payloads(_findings(), phase="AVP", prefix=PREFIX, model_id=MODEL_ID)
    _assert_bcf_invariants(got)
    _assert_bcf_invariants(_load("bcf_payloads.json"))  # golden aussi


def test_smartview_payload_invariants_hold_on_builder_and_golden():
    ebu = _snapshot().element_by_uuid
    got = pub.build_smartview_payloads(
        _findings(), phase="AVP", prefix=PREFIX, model_id=MODEL_ID, element_by_uuid=ebu
    )
    _assert_smartview_invariants(got)
    _assert_smartview_invariants(_load("smartview_payloads.json"))
    for p in got:
        assert p["title"].startswith(PREFIX)


def test_prepare_plan_invariants():
    _assert_plan_invariants(
        _plan_dump(pub.prepare_bcf(_findings(), phase="AVP", target=TARGET)), "bcf_topics"
    )
    ebu = _snapshot().element_by_uuid
    sv = pub.prepare_smart_views(_findings(), phase="AVP", target=TARGET, element_by_uuid=ebu)
    _assert_plan_invariants(_plan_dump(sv), "smart_views")


def test_golden_regeneration_is_gated_by_invariants():
    # Garde de régénération : les 5 goldens de payload/plan doivent satisfaire les
    # invariants (un golden régénéré depuis un builder cassé serait attrapé ici).
    _assert_bcf_invariants(_load("bcf_payloads.json"))
    _assert_smartview_invariants(_load("smartview_payloads.json"))
    _assert_smartview_invariants(_load("smartview_from_uuids.json"))
    _assert_plan_invariants(_load("prepare_bcf.json"), "bcf_topics")
    _assert_plan_invariants(_load("prepare_smart_views.json"), "smart_views")
