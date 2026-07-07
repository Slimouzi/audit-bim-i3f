"""Verrou générique ``field_path`` (docs/scope-field-path.md, §4).

Invariant : **chaque** finding émis par une règle d'audit satisfait
 - soit ``field_path`` respecte la **grammaire** ``<IfcClass>.<Attribut>`` /
   ``<IfcClass>.<Pset>.<Prop>`` **et** son premier segment == la **classe IFC réelle**
   de l'objet du finding (``ifc_type``) — *note d'implémentation B* ;
 - soit ``field_path is None`` **et** le finding est légitimement sans champ : soit
   il n'a **aucun objet** (``element_uuid is None`` → couverture/cardinalité), soit son
   ``error_type`` est dans la **liste blanche** gelée (§3).

Les findings **importés** (audit préliminaire externe) sont **exclus** du verrou via
un **marqueur structuré de provenance** (``is_imported_finding``), pas un nom de règle
— *note d'implémentation A*.

Objectif : rendre **impossible** l'ajout d'une règle qui émet un ``field_path`` mal
formé, un premier segment ≠ classe de l'objet, ou un ``None`` non justifié, sans faire
échouer la CI.
"""

from __future__ import annotations

import re

import pytest

from audit_bim.audit.engine import run_audit
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.audit.rules.preliminary import PROVENANCE_PREFIX, is_imported_finding
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import BIMPhase

# ── Contrat gelé (§1 grammaire + §3 liste blanche) ────────────────────────────
_GRAMMAR = re.compile(r"^Ifc[A-Za-z0-9]+(\.[A-Za-z0-9_]+){1,2}$")
_NONE_WHITELIST = {
    ErrorType.SPATIAL_ORPHAN,
    ErrorType.CLASSIFICATION_MISSING,
    ErrorType.CLASSIFICATION_INVALID,
}


def field_path_ok(f: Finding) -> bool:
    """Règle de verrou (§4) appliquée à un finding **émis par une règle**."""
    if f.field_path is None:
        # Exemption : couverture/cardinalité (aucun objet) OU error_type sans champ unique.
        return f.element_uuid is None or f.error_type in _NONE_WHITELIST
    # Grammaire (§1) + note B : premier segment == classe IFC réelle de l'objet.
    return bool(_GRAMMAR.fullmatch(f.field_path)) and f.field_path.split(".", 1)[0] == (
        f.ifc_type or ""
    )


# ── Corpus : un modèle volontairement non conforme, audité en réel ────────────
def _broken_snapshot() -> ModelSnapshot:
    """Snapshot déclenchant un maximum de familles (nommage, propriétés, quantités,
    géoréférencement, unicité, classifications, couverture)."""
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[
            {"uuid": "S1", "name": "BADSITE", "type": "IfcSite"}
        ],  # nom invalide + géoloc absente
        buildings=[{"uuid": "B1", "type": "IfcBuilding"}],  # Name manquant + adresse manquante
        storeys=[{"uuid": "F1", "name": "SOUS-SOL 42", "type": "IfcBuildingStorey"}],  # hors liste
        spaces=[
            {"uuid": "SP1", "type": "IfcSpace"},  # LongName manquant + quantité manquante
            {"uuid": "SP2", "longname": "chambre", "type": "IfcSpace"},  # minuscules
            {
                "uuid": "SP3",
                "longname": "SALON IMPROBABLE",
                "type": "IfcSpace",
            },  # hors liste pièces
        ],
        zones=[{"uuid": "Z1", "type": "IfcZone"}],  # Name + ObjectType manquants
        elements=[
            {  # équipement sans Tag + sans classification
                "uuid": "D1",
                "type": "IfcDoor",
                "name": "Porte 01",
                "classifications": [],
                "property_sets": [],
            },
            {  # mur sans les propriétés requises (Surface, IsExternal)
                "uuid": "W1",
                "type": "IfcWallStandardCase",
                "name": "Mur 01",
                "classifications": [{"notation": "C1010", "source": "UniFormat"}],
                "property_sets": [],
            },
        ],
    ).index()


@pytest.mark.parametrize("phase", [BIMPhase.AVP, BIMPhase.DOE])
def test_all_rule_findings_satisfy_the_lock(catalog, phase):
    """Bout-en-bout : TOUS les findings émis par ``run_audit`` respectent le verrou,
    sur plusieurs phases (AVP déclenche les propriétés murs, DOE la couverture zones)."""
    result = run_audit(_broken_snapshot(), catalog, phase)
    rule_findings = [f for f in result.findings if not is_imported_finding(f)]
    assert rule_findings, "le corpus doit produire des findings"
    offenders = [
        (f.error_type.value, f.ifc_type, repr(f.field_path))
        for f in rule_findings
        if not field_path_ok(f)
    ]
    assert not offenders, f"field_path non conforme : {offenders}"


def test_corpus_actually_exercises_the_grammar_forms(catalog):
    """Garde-fou : le corpus émet bien les 3 formes de la grammaire (sinon le test
    ci-dessus passerait à vide sur les chemins réels). Phase AVP = propriétés murs
    exigées."""
    result = run_audit(_broken_snapshot(), catalog, BIMPhase.AVP)
    paths = {f.field_path for f in result.findings if f.field_path}
    # attribut <IfcClass>.<Attribut>
    assert "IfcSite.Name" in paths
    assert "IfcSpace.LongName" in paths
    assert "IfcZone.ObjectType" in paths
    # quantité <IfcClass>.<Qto>.<Quantity>
    assert "IfcSpace.BaseQuantities.NetFloorArea" in paths
    # propriété <IfcClass>.<Pset>.<Prop> (locateur technique, pas le libellé humain)
    assert "IfcWallStandardCase.Pset_WallCommon.IsExternal" in paths
    # tous grammaticalement valides
    assert all(_GRAMMAR.fullmatch(p) for p in paths), paths


# ── Verrou : propriétés de la règle field_path_ok elle-même ───────────────────
def _f(**kw) -> Finding:
    kw.setdefault("theme", Theme.NAMING_SPACE)
    kw.setdefault("severity", Severity.LOW)
    kw.setdefault("error_type", ErrorType.NAMING_MISSING)
    return Finding(**kw)


@pytest.mark.parametrize(
    "good", ["IfcSpace.Name", "IfcDoor.Pset_DoorCommon.Tag", "IfcSite.Latitude"]
)
def test_grammar_accepts_wellformed(good):
    assert field_path_ok(_f(field_path=good, ifc_type=good.split(".")[0], element_uuid="X"))


@pytest.mark.parametrize(
    "bad",
    [
        "Space.Name",  # ne commence pas par Ifc
        "IfcSpace",  # 1 seul segment
        "IfcWall.Pset WallCommon.IsExternal",  # espace
        "IfcWall.a.b.c.d",  # trop de segments
        "IfcBuilding.Adresse du bâtiment",  # libellé humain (accents/espaces)
    ],
)
def test_grammar_rejects_malformed(bad):
    assert not field_path_ok(_f(field_path=bad, ifc_type="IfcSpace", element_uuid="X"))


def test_note_b_first_segment_must_match_object_class():
    # Grammaire OK mais 1er segment ≠ classe réelle de l'objet → REFUSÉ.
    assert not field_path_ok(_f(field_path="IfcWindow.Name", ifc_type="IfcDoor", element_uuid="X"))
    assert field_path_ok(_f(field_path="IfcDoor.Name", ifc_type="IfcDoor", element_uuid="X"))


def test_none_exempt_for_coverage_without_object():
    # Couverture/cardinalité : aucun objet (element_uuid None) → None toléré.
    assert field_path_ok(
        _f(field_path=None, error_type=ErrorType.PROPERTY_MISSING, ifc_type="IfcWall")
    )


def test_none_exempt_for_whitelisted_error_types_with_object():
    # Findings porteurs d'un objet mais sans champ unique → liste blanche par error_type.
    for et in _NONE_WHITELIST:
        assert field_path_ok(
            _f(field_path=None, error_type=et, ifc_type="IfcDoor", element_uuid="X")
        )


def test_none_rejected_for_object_bearing_non_whitelisted():
    # Objet présent, error_type hors liste blanche, field_path None → REFUSÉ.
    assert not field_path_ok(
        _f(
            field_path=None,
            error_type=ErrorType.PROPERTY_MISSING,
            ifc_type="IfcWall",
            element_uuid="X",
        )
    )


# ── Note A : exclusion des findings importés par marqueur de provenance ───────
def test_imported_findings_are_excluded_by_provenance_marker():
    imported = _f(
        field_path="chemin/sale non conforme",  # field_path arbitraire de l'import
        ref_cch=f"{PROVENANCE_PREFIX} · run_space_clash_audit",
        element_uuid="X",
    )
    assert is_imported_finding(imported)  # marqueur structuré reconnu
    # Un finding de règle (ref_cch = chapitre CCH) n'est PAS importé.
    rule = _f(
        field_path="IfcSpace.Name", ref_cch="Chap 6.3.2", ifc_type="IfcSpace", element_uuid="X"
    )
    assert not is_imported_finding(rule)
