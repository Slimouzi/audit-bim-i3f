"""Medium (audit profond 2ᵉ passe) — audit d'unicité des équipements :

- **thème erroné** : les défauts d'identifiant Tag/Mark étaient rangés dans
  « Nommage Pièce » (`NAMING_SPACE`) → désormais `PROPERTY_MISSING` (manquant) /
  `PROPERTY_INVALID` (doublon) ;
- **classes `*Type` incluses** : les définitions de type (`IfcAirTerminalType`…)
  n'ont pas à porter un identifiant GMAO unique par instance → exclues ;
- **détection Pset sensible à la casse** : `pset_fancommon` (minuscules) était raté
  → détection « common » insensible à la casse.
"""

from __future__ import annotations

from audit_bim.audit.findings import ErrorType, Theme
from audit_bim.audit.rules.uniqueness import audit_uniqueness
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import BIMPhase, RequirementsCatalog


def _snap(elements: list[dict]) -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=elements,
    ).index()


def _audit(elements):
    return audit_uniqueness(_snap(elements), RequirementsCatalog(), BIMPhase.DCE)


def _tag_pset(name: str, tag: str) -> dict:
    return {"name": name, "properties": [{"definition": {"name": "Tag"}, "value": tag}]}


# ── Thème corrigé ─────────────────────────────────────────────────────────────
def test_missing_identifier_is_property_missing_not_room_naming():
    findings = _audit([{"uuid": "D1", "type": "IfcDoor", "name": "Porte", "property_sets": []}])
    assert len(findings) == 1
    assert findings[0].theme == Theme.PROPERTY_MISSING
    assert findings[0].error_type == ErrorType.PROPERTY_MISSING
    assert findings[0].theme != Theme.NAMING_SPACE


def test_duplicate_identifier_is_property_invalid():
    els = [
        {"uuid": "D1", "type": "IfcDoor", "property_sets": [_tag_pset("Pset_DoorCommon", "T1")]},
        {"uuid": "D2", "type": "IfcDoor", "property_sets": [_tag_pset("Pset_DoorCommon", "T1")]},
    ]
    findings = _audit(els)
    assert len(findings) == 2
    assert all(f.theme == Theme.PROPERTY_INVALID for f in findings)
    assert all(f.error_type == ErrorType.PROPERTY_TYPE_INVALID for f in findings)


# ── Classes *Type exclues ─────────────────────────────────────────────────────
def test_type_class_without_identifier_not_flagged():
    # IfcAirTerminalType est une définition de type → aucun finding d'unicité.
    findings = _audit([{"uuid": "T1", "type": "IfcAirTerminalType", "property_sets": []}])
    assert findings == []


def test_physical_terminal_without_identifier_still_flagged():
    findings = _audit([{"uuid": "A1", "type": "IfcAirTerminal", "property_sets": []}])
    assert len(findings) == 1


# ── Pset insensible à la casse ────────────────────────────────────────────────
def test_lowercase_common_pset_identifier_detected():
    # « pset_fancommon » minuscules : identifiant trouvé → aucun finding manquant.
    el = {"uuid": "F1", "type": "IfcFan", "property_sets": [_tag_pset("pset_fancommon", "F-01")]}
    assert _audit([el]) == []


# ── Gating de phase inchangé ──────────────────────────────────────────────────
def test_no_uniqueness_audit_before_dce():
    snap = _snap([{"uuid": "D1", "type": "IfcDoor", "property_sets": []}])
    assert audit_uniqueness(snap, RequirementsCatalog(), BIMPhase.AVP) == []
