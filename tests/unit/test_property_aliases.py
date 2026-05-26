"""Tests du résolveur d'alias (``audit_bim.query.property_aliases``)."""

from __future__ import annotations

from audit_bim.domain.bim_object import BimObject, ClassificationRef
from audit_bim.query.property_aliases import (
    ACOUSTIC_ALIASES,
    DIMENSION_ALIASES,
    MANUFACTURER_ALIASES,
    MatchedValue,
    find_attribute_value,
    find_material_value,
    find_property_value,
    find_quantity_value,
    normalize_key,
    resolve_requested_field,
)


def _make_door(**overrides) -> BimObject:
    base = dict(
        uuid="DR1",
        ifc_type="IfcDoor",
        name="Porte palière R+1",
        object_type="Porte CF 30",
        is_external=False,
        materials=["Acier", "Verre feuilleté"],
        layers=["A-DOOR-INT"],
        properties={
            "Pset_DoorCommon.FireRating": "EI30",
            "Pset_DoorCommon.AcousticRating": "Rw=42dB",
            "Pset_DoorCommon.Thickness": 0.05,
            "Pset_3F.Fabricant": "BOSCH",
        },
        base_quantities={
            "Height": 2.04,
            "Width": 0.93,
            "NetArea": 1.90,
        },
    )
    base.update(overrides)
    return BimObject(**base)


# ── normalize_key ───────────────────────────────────────────────────────


class TestNormalizeKey:
    def test_strip_lower(self):
        assert normalize_key("  AcousticRating  ") == "acousticrating"

    def test_empty(self):
        assert normalize_key("") == ""
        assert normalize_key(None) == ""  # type: ignore[arg-type]

    def test_keeps_accents(self):
        # Les accents sont conservés — "Matériau" doit matcher tel quel.
        assert normalize_key("Matériau") == "matériau"


# ── find_property_value ────────────────────────────────────────────────


class TestFindPropertyValue:
    def test_exact_match(self):
        door = _make_door()
        mv = find_property_value(door, ["Pset_DoorCommon.AcousticRating"])
        assert mv is not None
        assert mv.value == "Rw=42dB"
        assert mv.source == "property"
        assert mv.matched_key == "Pset_DoorCommon.AcousticRating"

    def test_suffix_match_short_alias(self):
        """``AcousticRating`` doit matcher ``Pset_DoorCommon.AcousticRating``."""
        door = _make_door()
        mv = find_property_value(door, ["AcousticRating"])
        assert mv is not None
        assert mv.value == "Rw=42dB"
        assert mv.source == "property"

    def test_case_insensitive(self):
        door = _make_door()
        mv = find_property_value(door, ["acousticrating"])
        assert mv is not None
        assert mv.value == "Rw=42dB"

    def test_first_alias_wins(self):
        """Quand plusieurs alias matchent, le 1er dans la liste gagne."""
        door = _make_door()
        # Le 1er alias 'Rw' ne matche pas, le 2e 'AcousticRating' matche.
        mv = find_property_value(door, ACOUSTIC_ALIASES)
        assert mv is not None
        assert "42" in str(mv.value)

    def test_missing_returns_none(self):
        door = _make_door()
        assert find_property_value(door, ["UnknownProperty"]) is None

    def test_empty_value_skipped(self):
        door = _make_door(properties={"Pset_DoorCommon.FireRating": ""})
        assert find_property_value(door, ["FireRating"]) is None


# ── find_quantity_value ────────────────────────────────────────────────


class TestFindQuantityValue:
    def test_height(self):
        door = _make_door()
        mv = find_quantity_value(door, ["Height"])
        assert mv is not None
        assert mv.value == 2.04
        assert mv.source == "quantity"

    def test_basequantities_prefix_normalized(self):
        door = _make_door()
        mv = find_quantity_value(door, ["BaseQuantities.Height"])
        assert mv is not None
        assert mv.value == 2.04

    def test_missing(self):
        door = _make_door()
        assert find_quantity_value(door, ["Perimeter"]) is None


# ── find_attribute_value ───────────────────────────────────────────────


class TestFindAttributeValue:
    def test_name(self):
        door = _make_door()
        mv = find_attribute_value(door, ["name"])
        assert mv is not None
        assert mv.value == "Porte palière R+1"
        assert mv.source == "attribute"

    def test_object_type_alias(self):
        door = _make_door()
        mv = find_attribute_value(door, ["objecttype"])
        assert mv is not None
        assert mv.value == "Porte CF 30"


# ── find_material_value ────────────────────────────────────────────────


class TestFindMaterialValue:
    def test_returns_list(self):
        door = _make_door()
        mv = find_material_value(door)
        assert mv is not None
        assert mv.value == ["Acier", "Verre feuilleté"]
        assert mv.source == "material"

    def test_empty_returns_none(self):
        door = _make_door(materials=[])
        # Pas de pset.material non plus → None
        assert find_material_value(door) is None


# ── resolve_requested_field — champs standards ─────────────────────────


class TestResolveStandard:
    def test_uuid(self):
        door = _make_door()
        r = resolve_requested_field(door, "uuid")
        assert r["value"] == "DR1"
        assert r["source"] == "attribute"

    def test_classification_missing(self):
        door = _make_door()
        r = resolve_requested_field(door, "classification")
        assert r["value"] is None
        assert r["source"] == "missing"

    def test_classification_level_3(self):
        door = _make_door(classifications=[ClassificationRef(code="C1020.10", system="uniformat")])
        r = resolve_requested_field(door, "classification_level_3")
        assert r["value"] == "C1020"
        assert r["source"] == "classification"

    def test_materials(self):
        door = _make_door()
        r = resolve_requested_field(door, "materials")
        assert r["value"] == ["Acier", "Verre feuilleté"]
        assert r["source"] == "material"


class TestResolveDimensions:
    def test_height(self):
        door = _make_door()
        r = resolve_requested_field(door, "height")
        assert r["value"] == 2.04
        assert r["source"] == "quantity"

    def test_thickness_via_property_fallback(self):
        """Thickness est dans le Pset, pas dans BaseQuantities — le
        résolveur doit fallback."""
        door = _make_door()
        r = resolve_requested_field(door, "thickness")
        assert r["value"] == 0.05
        assert r["source"] == "property"
        assert "Thickness" in r["matched_key"]

    def test_dimensions_summary(self):
        door = _make_door()
        r = resolve_requested_field(door, "dimensions")
        assert r["source"] == "quantity"
        d = r["value"]
        assert d["height"] == 2.04
        assert d["width"] == 0.93
        assert d["thickness"] == 0.05


class TestResolveSemantic:
    def test_acoustic_performance(self):
        door = _make_door()
        r = resolve_requested_field(door, "acoustic_performance")
        assert "42" in str(r["value"])
        assert r["source"] == "property"

    def test_fire_rating(self):
        door = _make_door()
        r = resolve_requested_field(door, "fire_rating")
        assert r["value"] == "EI30"
        assert r["source"] == "property"

    def test_manufacturer(self):
        door = _make_door()
        r = resolve_requested_field(door, "manufacturer")
        assert r["value"] == "BOSCH"
        assert r["source"] == "property"


class TestResolveFallbackDynamic:
    def test_dynamic_pset_property(self):
        """Un nom ``Pset_3F.Fabricant`` non listé doit être trouvé en
        fallback dynamique."""
        door = _make_door(properties={"Pset_3F.Lot": "CVC"})
        r = resolve_requested_field(door, "Pset_3F.Lot")
        assert r["value"] == "CVC"
        assert r["source"] == "property"

    def test_unknown_returns_missing(self):
        door = _make_door()
        r = resolve_requested_field(door, "totally_unknown_field")
        assert r["value"] is None
        assert r["source"] == "missing"


# ── Sanity check des tables d'alias ────────────────────────────────────


class TestAliasTables:
    def test_acoustic_aliases_contain_rw(self):
        assert "Rw" in ACOUSTIC_ALIASES
        assert "AcousticRating" in ACOUSTIC_ALIASES

    def test_dimension_aliases_keys(self):
        assert set(DIMENSION_ALIASES.keys()) >= {
            "height",
            "width",
            "thickness",
            "area",
            "volume",
        }

    def test_manufacturer_aliases_french(self):
        assert "Fabricant" in MANUFACTURER_ALIASES


# ── MatchedValue dataclass ─────────────────────────────────────────────


class TestMatchedValue:
    def test_immutable(self):
        import dataclasses

        mv = MatchedValue(value=42, source="quantity", matched_key="Height")
        assert dataclasses.is_dataclass(mv)
        # frozen=True → AttributeError sur assignation
        try:
            mv.value = 99  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            pass
        else:
            raise AssertionError("MatchedValue devrait être frozen")
