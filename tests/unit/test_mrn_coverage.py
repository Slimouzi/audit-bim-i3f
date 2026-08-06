"""Couverture MRN — évaluabilité, jamais conformité.

Les constats verrouillés ici viennent de la mesure sur MN_BAT. Ils disent une
chose que le code seul ne dirait pas : **ce référentiel n'est pas évaluable sur
une maquette architecturale seule**, et un moteur qui trancherait « non
conforme » produirait plus de la moitié du référentiel en faux constats.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from audit_bim.profiles.bim_in_motion.mrn.coverage import (
    COVERAGE_STATUSES,
    assess_mrn_coverage,
    matching_classes,
    normalize_pset,
)


@dataclass
class _Req:
    sheet: str
    row: int
    property_name: str
    ifc_object: str
    pset: str = ""
    carrier_models: list = field(default_factory=list)


class _Snapshot:
    def __init__(self, elements):
        self.elements = elements


def _element(ifc_class, psets=()):
    return {
        "type": ifc_class,
        "property_sets": [{"name": name, "properties": []} for name in psets],
    }


SNAPSHOT = _Snapshot([_element("IfcWall", ["Pset_WallCommon", "AC_Pset_Local"])])


def test_an_absent_class_is_never_a_non_conformity():
    """Le constat qui commande tout le lot.

    Rien ne dit qu'une maquette architecturale devait porter une classe CVC.
    Conclure « non conforme » produirait un livrable chiffré, crédible et faux.
    """
    reqs = [_Req("CVC-PLB-SSI-ELEC", 10, "Rearmement", "IfcAlarm", "Pset_AlarmCommon")]
    coverage = assess_mrn_coverage(reqs, SNAPSHOT)

    verdicts = {r.status for r in coverage.requirements}
    assert verdicts == {"non_evaluable_classe_absente"}
    assert not any("conforme" == s for s in verdicts)


def test_out_of_scope_needs_both_a_declared_and_a_known_active_carrier():
    """« Hors périmètre » exige deux conditions, pas une.

    Un porteur déclaré ne suffit pas : sans savoir ce que porte la maquette
    analysée, conclure « ce n'était pas à elle de le contenir » est une
    supposition. Les feuilles techniques n'ayant aucun porteur, leurs exigences
    restent « non évaluables » — un aveu, pas un jugement.
    """
    reqs = [_Req("Généralités", 4, "RefLatitude", "IfcSite", "", ["ARC"])]

    unknown = assess_mrn_coverage(reqs, SNAPSHOT).requirements[0]
    assert unknown.status == "non_evaluable_classe_absente"

    other = assess_mrn_coverage(reqs, SNAPSHOT, active_carriers=["STR"]).requirements[0]
    assert other.status == "hors_perimetre_modele"


def test_an_exact_pset_on_a_present_class_is_evaluable():
    reqs = [_Req("Gros Oeuvre - CEA", 10, "IsExternal", "IfcWall", "Pset_WallCommon")]
    coverage = assess_mrn_coverage(reqs, SNAPSHOT)
    assert coverage.requirements[0].status == "evaluable_pset_exact"
    assert coverage.requirements[0].pset_match_kind == "exact"


def test_a_requirement_without_pset_is_evaluable_elsewhere():
    """La propriété se cherche en trois niveaux — la couverture constate, elle ne cherche pas."""
    reqs = [_Req("Généralités", 8, "Name", "IfcWall")]
    coverage = assess_mrn_coverage(reqs, SNAPSHOT)
    assert coverage.requirements[0].status == "evaluable_without_pset"
    assert coverage.requirements[0].pset_match_kind == "not_declared"


def test_an_unmatched_pset_blocks_evaluation_without_judging():
    reqs = [_Req("Gros Oeuvre - CEA", 12, "Finish", "IfcWall", "Pset_CoveringCommon")]
    coverage = assess_mrn_coverage(reqs, SNAPSHOT)
    assert coverage.requirements[0].status == "non_evaluable_mapping_pset"
    assert coverage.requirements[0].pset_match_kind == "missing"


def test_normalization_is_soft_and_never_invents_a_mapping():
    """Casse, accents, séparateurs, préfixe — rien de plus.

    Sur le fichier réel, elle rattrape **zéro** correspondance : l'écart est de
    vocabulaire, pas de graphie. Une heuristique généreuse produirait des
    rapprochements faux qu'aucun relecteur ne distinguerait des vrais.
    """
    assert normalize_pset("Pset_WallCommon") == normalize_pset("pset wall-common")
    assert normalize_pset("Pset_Élément") == normalize_pset("element")
    assert normalize_pset("Pset_CoveringCommon") != normalize_pset("AC_Pset_Local")


def test_only_coverage_statuses_are_produced():
    """Aucun statut de conformité ne peut sortir de ce lot."""
    reqs = [
        _Req("Généralités", 4, "a", "IfcSite", "", ["ARC"]),
        _Req("Gros Oeuvre - CEA", 5, "b", "IfcWall", "Pset_WallCommon"),
        _Req("Gros Oeuvre - CEA", 6, "c", "IfcWall"),
        _Req("Gros Oeuvre - CEA", 7, "d", "IfcWall", "Pset_Absent"),
        _Req("CVC-PLB-SSI-ELEC", 8, "e", "IfcAlarm", "Pset_AlarmCommon"),
    ]
    coverage = assess_mrn_coverage(reqs, SNAPSHOT)
    assert {r.status for r in coverage.requirements} <= set(COVERAGE_STATUSES)
    assert "conforme" not in COVERAGE_STATUSES
    assert "non_conforme" not in COVERAGE_STATUSES


def test_the_verdict_names_the_limit_instead_of_scoring_it():
    """Sous 25 % d'évaluabilité, le lecteur doit lire une phrase, pas un taux.

    Un score de 11 % se lit comme « mauvaise maquette ». La phrase dit ce qui
    est vrai : le référentiel n'est pas évaluable sur cette maquette seule.
    """
    reqs = [_Req("CVC-PLB-SSI-ELEC", i, "p", "IfcAlarm", "Pset_X") for i in range(10)]
    reqs.append(_Req("Gros Oeuvre - CEA", 99, "q", "IfcWall", "Pset_WallCommon"))
    verdict = assess_mrn_coverage(reqs, SNAPSHOT).verdict()

    assert "pas suffisamment évaluable" in verdict
    assert "synthèse de couverture, pas une grille de conformité" in verdict


def test_the_summary_reports_causes_not_only_totals():
    reqs = [
        _Req("Gros Oeuvre - CEA", 5, "b", "IfcWall", "Pset_WallCommon"),
        _Req("CVC-PLB-SSI-ELEC", 8, "e", "IfcAlarm", "Pset_AlarmCommon"),
    ]
    summary = assess_mrn_coverage(reqs, SNAPSHOT, model_name="MN_BAT").summary()

    assert summary["model_name"] == "MN_BAT"
    assert summary["requirements_total"] == 2
    assert summary["requirements_evaluable"] == 1
    assert summary["by_status"]["non_evaluable_classe_absente"] == 1
    assert summary["by_pset_match"] == {"exact": 1, "missing": 1}
    assert summary["per_sheet"]["CVC-PLB-SSI-ELEC"]["absent_classes"] == 1


@pytest.mark.parametrize("status", COVERAGE_STATUSES)
def test_no_coverage_status_reads_as_a_conformity_verdict(status):
    """Non-vacuité du contrat : aucun libellé ne peut se lire comme un jugement."""
    assert status.startswith(("evaluable", "non_evaluable", "hors_perimetre"))


# ── Les trois biais corrigés — non-régression ─────────────────────────


def test_a_pset_carried_by_another_class_never_makes_a_requirement_evaluable():
    """Un ``Pset_DoorCommon`` porté par un mur ne dit rien des portes.

    Mesurer les Psets globalement surestimait la couverture, et l'erreur était
    invisible : le total restait plausible.
    """
    snapshot = _Snapshot([_element("IfcWall", ["Pset_DoorCommon"]), _element("IfcDoor", [])])
    reqs = [_Req("Gros Oeuvre - CEA", 1, "Height", "IfcDoor", "Pset_DoorCommon")]
    result = assess_mrn_coverage(reqs, snapshot).requirements[0]

    assert result.status == "non_evaluable_mapping_pset"
    assert result.pset_match_kind == "missing"


def test_the_class_scoped_count_is_lower_than_the_global_one():
    """Contre-épreuve : le même Pset, bien placé, redevient évaluable.

    Sans elle, le contrôle précédent pourrait passer parce que *rien* n'est
    jamais évaluable, plutôt que parce que la portée est respectée.
    """
    reqs = [_Req("Gros Oeuvre - CEA", 1, "Height", "IfcDoor", "Pset_DoorCommon")]

    misplaced = _Snapshot([_element("IfcWall", ["Pset_DoorCommon"]), _element("IfcDoor", [])])
    well_placed = _Snapshot([_element("IfcDoor", ["Pset_DoorCommon"])])

    assert len(assess_mrn_coverage(reqs, misplaced).evaluable) == 0
    assert len(assess_mrn_coverage(reqs, well_placed).evaluable) == 1


def test_a_known_subclass_counts_as_the_required_class():
    """``IfcWall`` exigé et ``IfcWallStandardCase`` présent sont la même chose.

    Les traiter comme distincts transformerait des exigences évaluables en
    « classe absente » — une sous-estimation qui passerait pour de la rigueur.
    """
    snapshot = _Snapshot([_element("IfcWallStandardCase", ["Pset_WallCommon"])])
    reqs = [_Req("Gros Oeuvre - CEA", 1, "IsExternal", "IfcWall", "Pset_WallCommon")]

    assert assess_mrn_coverage(reqs, snapshot).requirements[0].status == "evaluable_pset_exact"
    assert "IfcWallStandardCase" in matching_classes("IfcWall")


@pytest.mark.parametrize(
    ("active", "expected"),
    [
        (None, "non_evaluable_classe_absente"),
        (["ARC"], "hors_perimetre_modele"),
        (["CVC"], "non_evaluable_classe_absente"),
    ],
    ids=["porteur-inconnu", "porteur-autre", "porteur-visé"],
)
def test_out_of_scope_requires_knowing_the_active_carrier(active, expected):
    """Un porteur déclaré ne suffit pas : il faut savoir ce que porte la maquette.

    Le cas décisif est le dernier — une exigence CVC absente d'une maquette
    **CVC** est un manque, pas un hors-sujet. Sans le porteur actif, la classer
    « hors périmètre » masquerait le défaut derrière une justification.
    """
    reqs = [_Req("CVC-PLB-SSI-ELEC", 1, "Rearmement", "IfcAlarm", "Pset_X", ["CVC"])]
    snapshot = _Snapshot([_element("IfcWall", [])])

    result = assess_mrn_coverage(reqs, snapshot, active_carriers=active).requirements[0]
    assert result.status == expected


def test_the_normalized_status_is_part_of_the_contract():
    """Figé même si MN_BAT n'en produit aucun : le statut existe, donc il se déclare."""
    assert "evaluable_pset_normalized" in COVERAGE_STATUSES

    snapshot = _Snapshot([_element("IfcWall", ["pset wall-common"])])
    reqs = [_Req("Gros Oeuvre - CEA", 1, "IsExternal", "IfcWall", "Pset_WallCommon")]
    result = assess_mrn_coverage(reqs, snapshot).requirements[0]
    assert result.status == "evaluable_pset_normalized"
    assert result.pset_match_kind == "normalized"


def test_scope_is_decided_before_class_and_pset():
    """Le porteur actif filtre en premier, sinon il ne filtre presque rien.

    Une exigence portée par CVC n'est pas « évaluable » sur une maquette ARC
    sous prétexte que la classe et le Pset s'y trouvent : elle n'y est pas
    attendue. Appliqué seulement au cas « classe absente », le contrôle laissait
    passer tout ce qui existait par ailleurs.
    """
    snapshot = _Snapshot([_element("IfcWall", ["Pset_WallCommon"])])
    reqs = [_Req("Généralités", 1, "IsExternal", "IfcWall", "Pset_WallCommon", ["CVC"])]

    assert assess_mrn_coverage(reqs, snapshot).requirements[0].status == "evaluable_pset_exact"
    filtered = assess_mrn_coverage(reqs, snapshot, active_carriers=["ARC"]).requirements[0]
    assert filtered.status == "hors_perimetre_modele"


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("IfcWall / IfcWallStandardCase", ["IfcWall", "IfcWallStandardCase"]),
        ("IfcSpace ou IfcCovering (si modélisé)", ["IfcSpace", "IfcCovering"]),
        ("IfcFlowSegment ou IfcPipeSegment", ["IfcFlowSegment", "IfcPipeSegment"]),
        ("IfcFooting\nIfcPile (si pieu)", ["IfcFooting", "IfcPile"]),
    ],
    ids=["slash", "ou-annote", "ou-simple", "retour-ligne"],
)
def test_a_composite_class_cell_yields_every_class(cell, expected):
    """Le fichier réel ne met pas toujours une classe unique dans la cellule.

    La prendre pour un nom de classe classait 54 exigences « classe absente »
    alors que la maquette porte l'une des variantes citées.
    """
    from audit_bim.profiles.bim_in_motion.mrn.coverage import declared_classes

    assert declared_classes(cell) == expected


def test_any_declared_class_present_makes_the_requirement_evaluable():
    """Il suffit qu'une des classes citées existe."""
    snapshot = _Snapshot([_element("IfcPipeSegment", ["Pset_PipeSegmentCommon"])])
    reqs = [
        _Req(
            "CVC-PLB-SSI-ELEC",
            1,
            "Material",
            "IfcFlowSegment ou IfcPipeSegment",
            "Pset_PipeSegmentCommon",
        )
    ]
    assert assess_mrn_coverage(reqs, snapshot).requirements[0].status == "evaluable_pset_exact"


def test_a_composite_cell_with_no_present_class_stays_unevaluable():
    """Contre-épreuve : l'extraction ne rend pas tout évaluable."""
    snapshot = _Snapshot([_element("IfcWall", [])])
    reqs = [_Req("CVC-PLB-SSI-ELEC", 1, "x", "IfcFooting\nIfcPile (si pieu)", "P")]
    assert (
        assess_mrn_coverage(reqs, snapshot).requirements[0].status == "non_evaluable_classe_absente"
    )
