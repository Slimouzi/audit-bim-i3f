"""Régressions naming (audit profond 2ᵉ passe) :

- **E4** — un ``IfcSite`` **sans Name** ne produisait aucun finding (la branche
  « manquant » n'existait que pour Building/Storey/Zone/Space) alors que la
  codification du site est la clé de l'arbre I3F.
- **E5** — ``_check_storey_name`` / ``_check_room_name`` comparaient sans
  normaliser les accents (``.upper()`` seul) → ``1ER ÉTAGE`` ≠ ``1ER ETAGE`` →
  faux ``NAMING_NOT_IN_LIST`` (ou contrôle silencieusement désactivé).
"""

from __future__ import annotations

from audit_bim.audit.findings import ErrorType
from audit_bim.audit.rules.naming import _check_room_name, _check_storey_name, audit_naming
from audit_bim.domain.text import fold_accents, fold_upper
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import RoomSpec, StoreyName


# ── domain.text ───────────────────────────────────────────────────────────────
def test_fold_accents_strips_diacritics():
    assert fold_accents("1ER ÉTAGE") == "1ER ETAGE"
    assert fold_accents("Dégagement") == "Degagement"
    assert fold_accents(None) == ""


def test_fold_upper_is_canonical():
    assert fold_upper("  1er  Étage ") == "1ER ETAGE"
    assert fold_upper("dégagement") == "DEGAGEMENT"


# ── E5 — comparaison insensible aux accents ───────────────────────────────────
def test_check_storey_name_accent_insensitive():
    allowed = {fold_upper("1ER ETAGE"), fold_upper("REZ-DE-CHAUSSEE")}
    assert _check_storey_name("1ER ÉTAGE", allowed) is True
    assert _check_storey_name("REZ-DE-CHAUSSÉE", allowed) is True
    assert _check_storey_name("SOUS-SOL 42", allowed) is False


def test_check_room_name_accent_insensitive():
    allowed = {fold_upper("DEGAGEMENT"), fold_upper("CHAMBRE")}
    assert _check_room_name("Dégagement", allowed) is True
    assert _check_room_name("CHAMBRE 01", allowed) is True  # tolérance suffixe
    assert _check_room_name("PLACARD", allowed) is False


def _snap_with_storey(name: str) -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[{"uuid": "S1", "name": "1802L", "type": "IfcSite"}],
        buildings=[{"uuid": "B1", "name": "1802L-A", "type": "IfcBuilding"}],
        storeys=[{"uuid": "F1", "name": name, "type": "IfcBuildingStorey"}],
        spaces=[],
        zones=[],
        elements=[],
    ).index()


def test_accented_storey_not_flagged_when_list_is_unaccented(catalog):
    # Le catalogue de test contient « 1ER ETAGE » (sans accent) ; la maquette
    # porte « 1ER ÉTAGE » → plus aucun NAMING_NOT_IN_LIST (régression E5).
    snap = _snap_with_storey("1ER ÉTAGE")
    not_in_list = [
        f
        for f in audit_naming(snap, catalog)
        if f.error_type == ErrorType.NAMING_NOT_IN_LIST and f.ifc_type == "IfcBuildingStorey"
    ]
    assert not_in_list == []


# ── E4 — IfcSite sans Name ────────────────────────────────────────────────────
def _snap_with_site(site: dict) -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[site],
        buildings=[{"uuid": "B1", "name": "1802L-A", "type": "IfcBuilding"}],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[],
    ).index()


def _site_naming_missing(snap, catalog) -> list:
    return [
        f
        for f in audit_naming(snap, catalog)
        if f.ifc_type == "IfcSite" and f.error_type == ErrorType.NAMING_MISSING
    ]


def test_site_without_name_is_flagged(catalog):
    snap = _snap_with_site({"uuid": "S1", "type": "IfcSite"})  # pas de Name
    findings = _site_naming_missing(snap, catalog)
    assert len(findings) == 1
    assert findings[0].field_path == "IfcSite.Name"


def test_site_with_name_emits_no_missing(catalog):
    snap = _snap_with_site({"uuid": "S1", "name": "1802L", "type": "IfcSite"})
    assert _site_naming_missing(snap, catalog) == []


def test_room_spec_object_reachable():
    # garde-fou d'import : les modèles utilisés dans les fixtures existent.
    assert RoomSpec(name="X", type_label="x", localisation="PP").name == "X"
    assert StoreyName(name="Y").name == "Y"
