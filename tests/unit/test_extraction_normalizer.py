"""Tests du module ``audit_bim.extraction.normalizer``."""

from __future__ import annotations

from audit_bim.extraction.normalizer import (
    classification_codes,
    get_attribute,
    get_property,
    has_classification,
    resolve_value,
)


def _element_with_pset(pset_name, props_dict):
    """Construit un élément BIMData minimal avec un Pset."""
    return {
        "property_sets": [
            {
                "name": pset_name,
                "properties": [
                    {"definition": {"name": k, "value_type": "string"}, "value": v}
                    for k, v in props_dict.items()
                ],
            }
        ],
        "classifications": [],
        "attributes": None,
    }


class TestGetAttribute:
    def test_flat_name(self):
        el = {"name": "Mur 01"}
        assert get_attribute(el, "Name") == "Mur 01"

    def test_flat_longname(self):
        el = {"longname": "CHAMBRE 01"}
        assert get_attribute(el, "LongName") == "CHAMBRE 01"

    def test_missing_returns_none(self):
        el = {}
        assert get_attribute(el, "Tag") is None


class TestGetProperty:
    def test_pset_exact_match(self):
        el = _element_with_pset("Pset_WallCommon", {"IsExternal": True})
        assert get_property(el, "Pset_WallCommon", "IsExternal") is True

    def test_pset_partial_match(self):
        # Tolère "Pset_WallCommon (BL01)"
        el = _element_with_pset("Pset_WallCommon (BL01)", {"FireRating": "60"})
        assert get_property(el, "Pset_WallCommon", "FireRating") == "60"

    def test_missing_returns_none(self):
        el = _element_with_pset("Pset_DoorCommon", {"Tag": "P-001"})
        assert get_property(el, "Pset_WallCommon", "IsExternal") is None


class TestResolveValue:
    def test_native_attribute(self):
        el = {"name": "1802L"}
        assert resolve_value(el, "Name", "Name") == "1802L"

    def test_pset_slash_path(self):
        el = _element_with_pset("Pset_SpaceCommon", {"FloorCovering": "Carrelage"})
        # convention: pset_or_attribute = "Pset_SpaceCommon/FloorCovering", prop_name vide ?
        # En vrai notre code : resolve_value(el, "Pset_SpaceCommon/FloorCovering", "FloorCovering")
        v = resolve_value(el, "Pset_SpaceCommon/FloorCovering", "FloorCovering")
        assert v == "Carrelage"

    def test_pset_separate(self):
        el = _element_with_pset("Pset_3F", {"Indicateur Bas Carbone": True})
        v = resolve_value(el, "Pset_3F", "Indicateur Bas Carbone")
        assert v is True


class TestClassifications:
    def test_has_classification_true(self):
        el = {"classifications": [{"notation": "B2010", "source": "UF"}]}
        assert has_classification(el) is True

    def test_has_classification_false(self):
        el = {"classifications": []}
        assert has_classification(el) is False

    def test_classification_codes(self):
        el = {
            "classifications": [
                {"notation": "B2010", "source": "UF"},
                {"notation": None, "name": "Fallback"},
            ]
        }
        codes = classification_codes(el)
        assert codes == ["B2010", "Fallback"]
