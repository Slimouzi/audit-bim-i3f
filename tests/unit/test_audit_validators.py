"""Tests du module ``audit_bim.audit.validators``."""
from __future__ import annotations

import pytest

from audit_bim.audit.validators import validate_property_value as v


class TestNumericPositive:
    @pytest.mark.parametrize("value,prop", [
        (2.5, "Surface"),
        (10, "NetSideArea"),
        (0.5, "Height"),
        (100, "Power"),
        (3.14, "Volume"),
    ])
    def test_valid_positive(self, value, prop):
        assert v(value, property_name=prop) is None

    @pytest.mark.parametrize("value,prop", [
        (-1.5, "Surface"),
        (-0.001, "NetSideArea"),
        (-10, "Volume"),
    ])
    def test_invalid_negative(self, value, prop):
        result = v(value, property_name=prop)
        assert result is not None
        assert "négative" in result

    def test_zero_surface_is_invalid(self):
        result = v(0, property_name="NetSideArea")
        assert result is not None
        assert "nulle" in result

    def test_non_numeric_string_invalid(self):
        result = v("abc", property_name="NetFloorArea")
        assert result is not None
        assert "non numérique" in result


class TestBoolean:
    @pytest.mark.parametrize("value", [True, False, "V", "F", "OUI", "NON", "0", "1", "VRAI", "FAUX"])
    def test_valid_bool_representations(self, value):
        assert v(value, property_name="IsExternal") is None

    def test_invalid_string_for_bool(self):
        result = v("X", property_name="IsExternal")
        assert result is not None
        assert "non booléen" in result

    def test_comment_triggers_bool_validation(self):
        # 'Combustible' n'est pas dans _BOOL_KEYS, mais le commentaire dit V/F
        result = v("invalid", property_name="Combustible", comment="Champs : V / F")
        assert result is not None


class TestAlphanumRequired:
    @pytest.mark.parametrize("value", ["BOSCH-X42", "PHILIPS", "ABC123", "réf-001"])
    def test_valid_reference(self, value):
        assert v(value, property_name="Référence commerciale") is None

    @pytest.mark.parametrize("value", ["", "  ", "\t"])
    def test_empty_after_strip_invalid(self, value):
        result = v(value, property_name="Référence commerciale")
        assert result is not None
        assert "vide" in result

    def test_too_short(self):
        result = v("A", property_name="fabricant")
        assert result is not None
        assert "courte" in result

    def test_numeric_tag_accepted(self):
        # Un Tag/Mark numérique reste acceptable
        assert v(12345, property_name="Tag") is None


class TestCoordinates:
    @pytest.mark.parametrize("lat", [-90.0, 0.0, 49.182, 90.0])
    def test_valid_latitude(self, lat):
        assert v(lat, property_name="Latitude") is None

    @pytest.mark.parametrize("lat", [95.0, -91.0, 180.0])
    def test_invalid_latitude_out_of_range(self, lat):
        result = v(lat, property_name="Latitude")
        assert result is not None
        assert "hors plage" in result

    @pytest.mark.parametrize("lon", [-180.0, 0.0, 2.349, 180.0])
    def test_valid_longitude(self, lon):
        assert v(lon, property_name="Longitude") is None

    @pytest.mark.parametrize("lon", [200.0, -181.0, 360.0])
    def test_invalid_longitude_out_of_range(self, lon):
        result = v(lon, property_name="Longitude")
        assert result is not None

    def test_non_numeric_coords(self):
        result = v("ABC", property_name="Latitude")
        assert result is not None
        assert "non numérique" in result


class TestPassthrough:
    """Les propriétés sans heuristique applicable doivent passer."""

    def test_arbitrary_string_ok(self):
        assert v("foo", property_name="Description") is None
        assert v("commentaire libre", property_name="Notes") is None

    def test_none_value_returns_none(self):
        # Absence gérée ailleurs — validate_property_value retourne None
        assert v(None, property_name="Anything") is None
