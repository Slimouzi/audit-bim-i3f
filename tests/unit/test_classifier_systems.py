"""Tests du module ``audit_bim.classifier.systems``."""

from __future__ import annotations

import pytest

from audit_bim.classifier.catalog import entry
from audit_bim.classifier.systems import SYSTEMS, get_system, translate


class TestGetSystem:
    @pytest.mark.parametrize(
        "alias,expected_label",
        [
            ("UniFormat II", "UniFormat II"),
            ("uniformat", "UniFormat II"),
            ("uf", "UniFormat II"),
            ("uf ii", "UniFormat II"),
            ("Omniclass", "Omniclass Table 22 (Work Results)"),
            ("omniclass", "Omniclass Table 22 (Work Results)"),
            ("CCS", "CCS (Cuneco Classification System)"),
            ("3F", "Table 3F interne"),
        ],
    )
    def test_resolves_aliases(self, alias, expected_label):
        assert get_system(alias).label == expected_label

    def test_none_defaults_to_uniformat(self):
        assert get_system(None).label == "UniFormat II"

    def test_empty_defaults_to_uniformat(self):
        assert get_system("").label == "UniFormat II"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="inconnu"):
            get_system("nonexistent-system")


class TestTranslate:
    def test_uniformat_passes_through(self):
        uf = entry("B2010")
        result = translate(uf, get_system("UniFormat II"))
        assert result.code == "B2010"

    def test_uf_to_omniclass(self):
        uf = entry("B2010")  # Exterior Walls
        omni = translate(uf, get_system("Omniclass"))
        assert omni.system == "Omniclass Table 22"
        assert omni.code.startswith("21-")  # convention Omniclass Table 22

    def test_uf_unknown_code_in_omniclass_falls_back(self):
        # Z9999 n'a pas de mapping → on garde le code UF avec label « sans correspondance »
        uf = entry("Z9999")
        omni = translate(uf, get_system("Omniclass"))
        assert "sans correspondance" in omni.system.lower()


class TestSystemsRegistry:
    def test_four_systems_registered(self):
        assert len(SYSTEMS) == 4
        assert "UniFormat II" in SYSTEMS
        assert "Omniclass" in SYSTEMS
        assert "CCS" in SYSTEMS
        assert "3F" in SYSTEMS

    def test_omniclass_has_mapper(self):
        assert SYSTEMS["Omniclass"].map_from_uniformat is not None

    def test_ccs_has_no_mapper(self):
        # CCS pas de mapper auto — à fournir par projet
        assert SYSTEMS["CCS"].map_from_uniformat is None
