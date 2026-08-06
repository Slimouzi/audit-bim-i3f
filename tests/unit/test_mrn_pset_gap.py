"""Diagnostic des Psets manquants — un candidat par exigence, jamais par groupe.

Le cas qui a motivé ce fichier : `IfcWindow` / `Pset_MRN` compte 25 exigences et
un seul `IsExternal` retrouvé ailleurs. Un critère de groupe déclarait les 25
mappables ; un mapping signé sur cette base aurait rendu « évaluables » vingt-
quatre exigences dont la donnée n'existe pas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from audit_bim.profiles.bim_in_motion.mrn.pset_gap import diagnose_pset_gap


@dataclass
class _Blocked:
    sheet: str
    ifc_object: str
    pset: str
    property_name: str
    row: int = 1


class _Snapshot:
    def __init__(self, elements):
        self.elements = elements


def _element(ifc_class, psets):
    return {
        "type": ifc_class,
        "property_sets": [
            {"name": name, "properties": [{"definition": {"name": p}} for p in props]}
            for name, props in psets.items()
        ],
    }


def test_a_group_overlap_never_produces_one_candidate_per_requirement():
    """Le cas réel : 25 exigences, un seul recouvrement, un seul candidat.

    C'est le garde-fou central du lot. Sans lui, un `IsExternal` partagé
    suffirait à faire signer une convention couvrant vingt-cinq exigences.
    """
    expected = [f"Prop_{i}" for i in range(24)] + ["IsExternal"]
    blocked = [
        _Blocked("Gros Oeuvre - CEA", "IfcWindow", "Pset_MRN", name, row)
        for row, name in enumerate(expected, start=10)
    ]
    snapshot = _Snapshot([_element("IfcWindow", {"Pset_WindowCommon": ["IsExternal"]})])

    gap = diagnose_pset_gap(blocked, snapshot)[0]

    assert gap.requirements == 25
    assert len(gap.candidates) == 1, "un seul candidat, pas vingt-cinq"
    assert gap.candidates[0].required_property == "IsExternal"
    assert gap.group_overlap_rate == pytest.approx(0.04, abs=0.01)


def test_the_overlap_rate_is_diagnostic_and_unblocks_nothing():
    """Le taux signale qu'un rapprochement existe ; il ne vaut pas correspondance."""
    blocked = [
        _Blocked("s", "IfcWindow", "Pset_MRN", "IsExternal", 1),
        _Blocked("s", "IfcWindow", "Pset_MRN", "Affectation_Local", 2),
    ]
    snapshot = _Snapshot([_element("IfcWindow", {"Pset_WindowCommon": ["IsExternal"]})])
    gap = diagnose_pset_gap(blocked, snapshot)[0]

    assert gap.group_overlap_rate == 0.5
    assert {c.required_property for c in gap.candidates} == {"IsExternal"}


def test_a_requirement_whose_property_is_absent_gets_no_candidate():
    """176 exigences sont dans ce cas : la donnée n'a pas été saisie."""
    blocked = [_Blocked("s", "IfcSpace", "Pset_MRN", "Affectation_Local")]
    snapshot = _Snapshot([_element("IfcSpace", {"Pset_SpaceCommon": ["Reference"]})])
    gap = diagnose_pset_gap(blocked, snapshot)[0]

    assert gap.candidates == []
    assert gap.resolvable_by_mapping is False
    assert gap.group_overlap_rate == 0.0


def test_a_property_present_on_another_class_is_not_a_candidate():
    """La classe compte autant que le nom : même propriété, mauvais objet."""
    blocked = [_Blocked("s", "IfcDoor", "Pset_MRN", "IsExternal")]
    snapshot = _Snapshot([_element("IfcWall", {"Pset_WallCommon": ["IsExternal"]})])

    assert diagnose_pset_gap(blocked, snapshot)[0].candidates == []


def test_an_accepted_subclass_keeps_the_candidate():
    """`IfcWall` exigé et `IfcWallStandardCase` présent restent compatibles."""
    blocked = [_Blocked("s", "IfcWall", "Qto_WallBaseQuantities", "NetSideArea")]
    snapshot = _Snapshot([_element("IfcWallStandardCase", {"BaseQuantities": ["NetSideArea"]})])
    gap = diagnose_pset_gap(blocked, snapshot)[0]

    assert len(gap.candidates) == 1
    assert gap.candidates[0].candidate_source_pset == "BaseQuantities"
    assert gap.candidates[0].same_ifc_scope is True


def test_an_absent_class_yields_no_candidate_at_all():
    """Rien à rapprocher quand l'objet lui-même n'est pas modélisé."""
    blocked = [_Blocked("s", "IfcAlarm", "Pset_AlarmCommon", "Rearmement")]
    snapshot = _Snapshot([_element("IfcWall", {"Pset_WallCommon": ["Rearmement"]})])

    assert diagnose_pset_gap(blocked, snapshot)[0].candidates == []


def test_every_candidate_demands_human_validation():
    """Un mapping métier ne se devine pas, il se signe."""
    blocked = [_Blocked("s", "IfcWindow", "Pset_MRN", "IsExternal")]
    snapshot = _Snapshot([_element("IfcWindow", {"Pset_WindowCommon": ["IsExternal"]})])
    candidate = diagnose_pset_gap(blocked, snapshot)[0].candidates[0]

    assert candidate.requires_human_validation is True
    assert candidate.confidence == 1.0, "exacte sur classe compatible, ou pas de candidat"
    assert candidate.required_property and candidate.matched_property


def test_the_document_never_promises_a_guaranteed_gain():
    """Aucune des trois lectures fausses ne doit reparaître comme un gain."""
    doc = Path(__file__).resolve().parents[2] / "docs" / "scope-mrn-pset-mapping.md"
    text = " ".join(doc.read_text(encoding="utf-8").split())

    for forbidden in ("+197", "+54", "+22", "débloque 197"):
        assert forbidden not in text, forbidden
    assert "plafonné à 21 exigences, sous validation humaine" in text
    assert "structure contractuelle" in text
