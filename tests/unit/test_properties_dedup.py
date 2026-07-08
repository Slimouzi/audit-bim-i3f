"""Medium (audit profond 2ᵉ passe) — dédup parent/sous-classe dans
``audit_properties``.

Une même exigence listée sur la classe générique du CCH (``IfcWall``) **et** sur
une sous-classe (``IfcWallStandardCase``) faisait auditer deux fois un élément
``IfcWallStandardCase`` → deux findings **strictement identiques**. On garde le
premier.
"""

from __future__ import annotations

from audit_bim.audit.rules.properties import audit_properties
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import BIMPhase, PropertySpec, RequirementsCatalog


def _spec(ifc_class: str) -> PropertySpec:
    return PropertySpec(
        theme="Architecture",
        objet="Mur",
        ifc_class=ifc_class,
        property_name="Est extérieur",
        pset_or_attribute="Pset_WallCommon/IsExternal",
        kind="property",
        required_phases=[BIMPhase.AVP],
    )


def _wall_snapshot(wall_type: str) -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[{"uuid": "W1", "type": wall_type, "name": "Mur", "property_sets": []}],
    ).index()


def test_parent_and_subclass_spec_yields_single_finding():
    cat = RequirementsCatalog(properties=[_spec("IfcWall"), _spec("IfcWallStandardCase")])
    snap = _wall_snapshot("IfcWallStandardCase")
    findings = audit_properties(snap, cat, BIMPhase.AVP)
    assert len(findings) == 1
    assert findings[0].field_path == "IfcWallStandardCase.Pset_WallCommon.IsExternal"


def test_single_spec_still_one_finding():
    cat = RequirementsCatalog(properties=[_spec("IfcWall")])
    snap = _wall_snapshot("IfcWallStandardCase")
    assert len(audit_properties(snap, cat, BIMPhase.AVP)) == 1


def test_distinct_properties_not_deduped():
    # Deux exigences DIFFÉRENTES sur le même mur → deux findings (field_path distincts).
    cat = RequirementsCatalog(
        properties=[
            _spec("IfcWall"),
            PropertySpec(
                theme="Architecture",
                objet="Mur",
                ifc_class="IfcWall",
                property_name="Surface",
                pset_or_attribute="Pset_WallCommon/NetArea",
                kind="property",
                required_phases=[BIMPhase.AVP],
            ),
        ]
    )
    snap = _wall_snapshot("IfcWall")
    paths = {f.field_path for f in audit_properties(snap, cat, BIMPhase.AVP)}
    assert paths == {
        "IfcWall.Pset_WallCommon.IsExternal",
        "IfcWall.Pset_WallCommon.NetArea",
    }
