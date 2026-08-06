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


def test_a_declared_carrier_turns_an_absent_class_into_out_of_scope():
    """Seule une colonne porteuse permet de dire « hors périmètre ».

    Les feuilles techniques n'en ont pas : leurs exigences restent donc
    « non évaluables », un aveu et non un jugement.
    """
    reqs = [_Req("Généralités", 4, "RefLatitude", "IfcSite", "", ["ARC"])]
    coverage = assess_mrn_coverage(reqs, SNAPSHOT)
    assert coverage.requirements[0].status == "hors_perimetre_modele"


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
