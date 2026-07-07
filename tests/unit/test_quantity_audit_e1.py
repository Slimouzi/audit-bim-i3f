"""E1 (audit profond 2ᵉ passe) — les exigences ``kind="quantity"`` du format CCH
2026 sont réellement auditées par ``audit_properties`` (source **unique** des
quantités), et ``audit_spatial`` ne conserve son contrôle IfcSpace câblé qu'en
**repli** (catalogue sans exigence quantité → ancien format V3.x).

Décision CTO : « spatial cède à properties » — pas de double comptage de la même
surface manquante.
"""

from __future__ import annotations

from audit_bim.audit.findings import ErrorType, Theme
from audit_bim.audit.rules.properties import audit_properties
from audit_bim.audit.rules.spatial import audit_spatial
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import BIMPhase, PropertySpec, RequirementsCatalog


def _catalog_with_quantities() -> RequirementsCatalog:
    return RequirementsCatalog(
        properties=[
            PropertySpec(
                theme="Quantités",
                objet="Pièce",
                ifc_class="IfcSpace",
                property_name="Surface nette",
                pset_or_attribute="BaseQuantities/NetArea",
                kind="quantity",
                required_phases=[BIMPhase.AVP, BIMPhase.PRO],
            ),
            PropertySpec(
                theme="Architecture",
                objet="Mur",
                ifc_class="IfcWall",
                property_name="Surface nette",
                pset_or_attribute="BaseQuantities/NetSideArea",
                kind="quantity",
                required_phases=[BIMPhase.AVP],
            ),
        ]
    )


def _catalog_old_format() -> RequirementsCatalog:
    # Ancien format : aucune exigence kind="quantity".
    return RequirementsCatalog(
        properties=[
            PropertySpec(
                theme="Générale",
                objet="Mur",
                ifc_class="IfcWall",
                property_name="Est extérieur",
                pset_or_attribute="Pset_WallCommon/IsExternal",
                kind="property",
                required_phases=[BIMPhase.AVP],
            )
        ]
    )


def _snap(space_psets, wall_psets) -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[{"uuid": "S1", "name": "1802L", "type": "IfcSite"}],
        buildings=[{"uuid": "B1", "name": "1802L-A", "type": "IfcBuilding"}],
        storeys=[{"uuid": "F1", "name": "REZ-DE-CHAUSSEE", "type": "IfcBuildingStorey"}],
        spaces=[
            {"uuid": "SP1", "longname": "CHAMBRE", "type": "IfcSpace", "property_sets": space_psets}
        ],
        zones=[],
        elements=[{"uuid": "W1", "name": "Mur", "type": "IfcWall", "property_sets": wall_psets}],
    ).index()


def _basequantities(name: str, value) -> dict:
    return {
        "name": "BaseQuantities",
        "properties": [{"definition": {"name": name, "value_type": "real"}, "value": value}],
    }


# ── E1 : les quantités du catalogue sont auditées par properties ──────────────
def test_properties_audits_catalog_quantities_for_all_classes():
    cat = _catalog_with_quantities()
    snap = _snap(space_psets=[], wall_psets=[])  # ni surface pièce ni surface mur
    findings = audit_properties(snap, cat, BIMPhase.AVP)
    qty = [f for f in findings if f.error_type == ErrorType.SPATIAL_MISSING_QUANTITY]
    paths = {f.field_path for f in qty}
    assert paths == {"IfcSpace.BaseQuantities.NetArea", "IfcWall.BaseQuantities.NetSideArea"}
    assert all(f.theme == Theme.QUANTITY for f in qty)


def test_present_quantity_emits_nothing():
    cat = _catalog_with_quantities()
    snap = _snap(
        space_psets=[_basequantities("NetArea", 12.5)],
        wall_psets=[_basequantities("NetSideArea", 8.0)],
    )
    findings = audit_properties(snap, cat, BIMPhase.AVP)
    assert [f for f in findings if f.error_type == ErrorType.SPATIAL_MISSING_QUANTITY] == []


# ── Pas de double comptage : spatial se tait quand le catalogue couvre l'espace ─
def test_spatial_yields_to_properties_when_catalog_has_space_quantity():
    cat = _catalog_with_quantities()
    snap = _snap(space_psets=[], wall_psets=[])
    spatial_qty = [
        f
        for f in audit_spatial(snap, cat, BIMPhase.AVP)
        if f.error_type == ErrorType.SPATIAL_MISSING_QUANTITY
    ]
    assert spatial_qty == []  # audit_properties en est désormais la source unique


# ── Repli préservé : ancien format (sans exigence quantité) ───────────────────
def test_spatial_fallback_still_fires_for_old_format_catalog():
    cat = _catalog_old_format()
    snap = _snap(space_psets=[], wall_psets=[])
    spatial_qty = [
        f
        for f in audit_spatial(snap, cat, BIMPhase.AVP)
        if f.error_type == ErrorType.SPATIAL_MISSING_QUANTITY
    ]
    assert len(spatial_qty) == 1  # repli câblé conservé
    # et properties n'invente pas de quantité (aucune exigence quantity)
    props_qty = [
        f
        for f in audit_properties(snap, cat, BIMPhase.AVP)
        if f.error_type == ErrorType.SPATIAL_MISSING_QUANTITY
    ]
    assert props_qty == []
