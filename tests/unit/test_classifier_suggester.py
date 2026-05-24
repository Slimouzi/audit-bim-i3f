"""Tests du module ``audit_bim.classifier.suggester``."""
from __future__ import annotations

from audit_bim.classifier.suggester import accepted_codes_for, suggest

# Mapping classe IFC → Pset_*Common standard buildingSMART
# (Pset attaché à la classe *parent*, pas à la sous-classe StandardCase)
_BASE_CLASS_FOR_PSET = {
    "IfcWallStandardCase": "Wall",
    "IfcWallElementedCase": "Wall",
    "IfcWall": "Wall",
    "IfcDoorStandardCase": "Door",
    "IfcDoor": "Door",
    "IfcWindowStandardCase": "Window",
    "IfcWindow": "Window",
    "IfcSlabStandardCase": "Slab",
    "IfcSlab": "Slab",
    "IfcStair": "Stair",
}


def _make_element(ifc_class: str, **kwargs) -> dict:
    """Construit un dict élément BIMData minimal pour les tests."""
    el = {
        "uuid": "TEST-UUID",
        "type": ifc_class,
        "name": kwargs.get("name", ""),
        "object_type": kwargs.get("object_type", ""),
        "longname": kwargs.get("longname", ""),
        "description": "",
        "attributes": None,
        "property_sets": [],
        "classifications": [],
        "layers": [],
        "material_list": [],
    }
    if "is_external" in kwargs:
        base = _BASE_CLASS_FOR_PSET.get(ifc_class, ifc_class[3:])
        el["property_sets"].append({
            "name": f"Pset_{base}Common",
            "properties": [{
                "definition": {"name": "IsExternal", "value_type": "boolean"},
                "value": kwargs["is_external"],
            }],
        })
    if "layer" in kwargs:
        el["layers"] = [{"name": kwargs["layer"]}]
    return el


class TestSuggestByIfcClass:
    def test_wall_external_returns_b2010(self):
        el = _make_element("IfcWallStandardCase", is_external=True)
        sugs = suggest(el)
        assert sugs[0].classification.code == "B2010"
        assert sugs[0].confidence >= 0.5

    def test_wall_internal_returns_c1010(self):
        el = _make_element("IfcWallStandardCase", is_external=False)
        sugs = suggest(el)
        assert sugs[0].classification.code == "C1010"

    def test_door_returns_c1020_default(self):
        el = _make_element("IfcDoor")
        sugs = suggest(el)
        assert sugs[0].classification.code == "C1020"

    def test_window_returns_b2020(self):
        el = _make_element("IfcWindow")
        sugs = suggest(el)
        assert sugs[0].classification.code == "B2020"

    def test_stair_returns_c2010(self):
        el = _make_element("IfcStair")
        sugs = suggest(el)
        assert sugs[0].classification.code == "C2010"

    def test_furnishing_returns_e2010(self):
        el = _make_element("IfcFurnishingElement")
        sugs = suggest(el)
        assert sugs[0].classification.code == "E2010"

    def test_unknown_proxy_no_suggestion(self):
        el = _make_element("IfcBuildingElementProxy", name="machin")
        sugs = suggest(el)
        # Proxy sans keyword reconnu → vide
        assert sugs == []


class TestLayerHint:
    def test_layer_facade_boosts_b2010(self):
        el = _make_element("IfcWallStandardCase", is_external=True, layer="A-WALL-FACADE")
        sugs = suggest(el)
        assert sugs[0].classification.code == "B2010"
        # Doit avoir raison layer
        reasons_text = " ".join(sugs[0].reasons)
        assert "layer" in reasons_text.lower()


class TestAcceptedCodesFor:
    def test_furnishing_accepts_e2010_and_e2020(self):
        accepted = accepted_codes_for("IfcFurnishingElement", "E2010")
        assert "E2010" in accepted
        assert "E2020" in accepted

    def test_wall_accepts_b2010_and_c1010(self):
        accepted = accepted_codes_for("IfcWall", "B2010")
        assert {"B2010", "C1010"}.issubset(accepted)

    def test_unknown_class_just_top(self):
        accepted = accepted_codes_for("IfcUnknown", "X1234")
        assert accepted == {"X1234"}

    def test_top_code_always_included(self):
        accepted = accepted_codes_for("IfcDoor", "B2030")
        assert "B2030" in accepted
