"""Régression C1 (audit profond 2ᵉ passe) — la quantité de surface d'un ``IfcSpace``
est réellement lue via le locateur composite ``BaseQuantities/NetFloorArea``.

Avant correctif : ``resolve_value(sp, "BaseQuantities", "NetFloorArea")`` (sans ``/``,
sans préfixe ``Pset``) ne matchait aucune étape de routage → ``None`` systématique →
finding ``SPATIAL_MISSING_QUANTITY`` sur **toute** pièce conforme. Seul le cas négatif
était couvert (le corpus du verrou ``field_path`` s'attend au finding pour une pièce
*sans* quantité) ; le cas **positif** manquait et laissait passer le faux positif.
"""

from __future__ import annotations

import pytest

from audit_bim.audit.findings import ErrorType
from audit_bim.audit.rules.spatial import audit_spatial
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import BIMPhase


def _space(uuid: str, *, psets: list[dict]) -> dict:
    return {"uuid": uuid, "type": "IfcSpace", "longname": "CHAMBRE 01", "property_sets": psets}


def _snapshot(space: dict) -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[{"uuid": "S1", "name": "1802L", "type": "IfcSite"}],
        buildings=[{"uuid": "B1", "name": "1802L-A", "type": "IfcBuilding"}],
        storeys=[{"uuid": "F1", "name": "REZ-DE-CHAUSSEE", "type": "IfcBuildingStorey"}],
        spaces=[space],
        zones=[],
        elements=[],
    ).index()


def _quantity_findings(snap: ModelSnapshot, catalog, phase: BIMPhase = BIMPhase.AVP) -> list:
    return [
        f
        for f in audit_spatial(snap, catalog, phase)
        if f.error_type == ErrorType.SPATIAL_MISSING_QUANTITY
    ]


def _basequantities(prop: str, value) -> dict:
    return {
        "name": "BaseQuantities",
        "properties": [{"definition": {"name": prop, "value_type": "real"}, "value": value}],
    }


# ── Positif : la pièce PORTE la quantité → AUCUN finding (régression C1) ───────
def test_space_with_netfloorarea_in_basequantities_emits_no_finding(catalog):
    snap = _snapshot(_space("SP1", psets=[_basequantities("NetFloorArea", 12.5)]))
    assert _quantity_findings(snap, catalog) == []


def test_space_with_archicad_zone_surface_fallback_emits_no_finding(catalog):
    # Repli ArchiCAD (AC_Pset_Marque_de_zone) atteint via le locateur composite.
    snap = _snapshot(
        _space(
            "SP2",
            psets=[
                {
                    "name": "AC_Pset_Marque_de_zone (BL01)",
                    "properties": [
                        {
                            "definition": {"name": "Surface nette mesurée", "value_type": "real"},
                            "value": 9.8,
                        }
                    ],
                }
            ],
        )
    )
    assert _quantity_findings(snap, catalog) == []


# ── Négatif : la pièce N'A PAS la quantité → le finding LÉGITIME est émis ──────
def test_space_without_any_quantity_still_flags(catalog):
    snap = _snapshot(_space("SP3", psets=[]))
    findings = _quantity_findings(snap, catalog)
    assert len(findings) == 1
    assert findings[0].field_path == "IfcSpace.BaseQuantities.NetFloorArea"


def test_space_with_zero_area_still_flags(catalog):
    # Une surface nulle vaut « manquante » (garde ``area in (None, 0, 0.0)``).
    snap = _snapshot(_space("SP4", psets=[_basequantities("NetFloorArea", 0.0)]))
    assert len(_quantity_findings(snap, catalog)) == 1


@pytest.mark.parametrize("phase", [BIMPhase.APS])
def test_no_quantity_audit_before_avp(catalog, phase):
    # La quantité n'est exigée qu'à partir de l'AVP : en APS, aucun finding.
    snap = _snapshot(_space("SP5", psets=[]))
    assert _quantity_findings(snap, catalog, phase) == []
