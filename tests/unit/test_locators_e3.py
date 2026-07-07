"""E3 (audit profond 2ᵉ passe) — locateurs autrefois irrésolubles :

- ``IfcName`` / ``IfcDescription`` : le préfixe de classe (abus fréquent des
  annexes V3.7) empêchait tout matching dans ``resolve_value`` → 100 % de faux
  ``PROPERTY_MISSING``. Désormais normalisés vers l'attribut natif.
- ``IfcMaterial`` : le matériau est une **association** inlinée par bimdata-read
  (``material_list``), pas un attribut plat → jamais résolu → 100 % de faux
  positifs. Désormais résolu depuis ``material_list`` (décision CTO : résoudre
  depuis l'association) ; absent → ``PROPERTY_MISSING`` **légitime**.
"""

from __future__ import annotations

from audit_bim.audit.findings import ErrorType
from audit_bim.audit.rules.properties import audit_properties
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.extraction.normalizer import material_names, resolve_value
from audit_bim.requirements.models import BIMPhase, PropertySpec, RequirementsCatalog


# ── resolve_value : normalisation IfcXxx → attribut natif ─────────────────────
def test_ifcname_locator_resolves_to_name():
    el = {"uuid": "W1", "type": "IfcWall", "name": "Mur 01"}
    assert resolve_value(el, "IfcName", "Name") == "Mur 01"


def test_ifcdescription_locator_resolves():
    el = {"uuid": "W1", "type": "IfcWall", "description": "porteur"}
    assert resolve_value(el, "IfcDescription", "Description") == "porteur"


# ── resolve_value : matériau depuis material_list ─────────────────────────────
def test_material_names_reads_bimdata_form():
    el = {"material_list": [{"material": {"name": "Béton"}}, {"material": {"name": "Acier"}}]}
    assert material_names(el) == ["Béton", "Acier"]


def test_ifcmaterial_locator_resolves_from_material_list():
    el = {"uuid": "W1", "type": "IfcWall", "material_list": [{"material": {"name": "Béton"}}]}
    assert resolve_value(el, "IfcMaterial", "Matériaux") == "Béton"


def test_ifcmaterial_absent_returns_none():
    el = {"uuid": "W1", "type": "IfcWall", "material_list": []}
    assert resolve_value(el, "IfcMaterial", "Matériaux") is None


# ── Intégration audit_properties ──────────────────────────────────────────────
def _catalog_material() -> RequirementsCatalog:
    return RequirementsCatalog(
        properties=[
            PropertySpec(
                theme="Matériaux",
                objet="Mur",
                ifc_class="IfcWall",
                property_name="Matériaux",
                pset_or_attribute="IfcMaterial",
                kind="property",
                required_phases=[BIMPhase.AVP],
            )
        ]
    )


def _snap_wall(material_list) -> ModelSnapshot:
    wall = {"uuid": "W1", "type": "IfcWall", "name": "Mur"}
    if material_list is not None:
        wall["material_list"] = material_list
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[wall],
    ).index()


def _material_missing(snap, cat) -> list:
    return [
        f
        for f in audit_properties(snap, cat, BIMPhase.AVP)
        if f.error_type == ErrorType.PROPERTY_MISSING and f.ifc_type == "IfcWall"
    ]


def test_wall_with_material_not_flagged():
    snap = _snap_wall([{"material": {"name": "Béton"}}])
    assert _material_missing(snap, _catalog_material()) == []


def test_wall_without_material_flagged_legitimately():
    snap = _snap_wall([])
    findings = _material_missing(snap, _catalog_material())
    assert len(findings) == 1
    assert findings[0].field_path == "IfcWall.IfcMaterial"
