"""Tests du module ``audit_bim.classifier.catalog``."""

from __future__ import annotations

import pytest

from audit_bim.classifier.catalog import UNIFORMAT, entry, normalize_uniformat_level3


class TestEntry:
    def test_known_code(self):
        e = entry("B2010")
        assert e.code == "B2010"
        assert e.label == "Exterior Walls"
        assert e.system == "UniFormat II"

    def test_unknown_code_label_falls_back(self):
        e = entry("Z9999")
        assert e.code == "Z9999"
        assert e.label == "Z9999"  # même valeur que le code


class TestNormalizeUniformatLevel3:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("E2020200", "E2020"),
            ("E2020", "E2020"),
            ("B 2010", "B2010"),
            ("B-2010-100", "B2010"),
            ("C.3030.50", "C3030"),
            ("e2020.200", "E2020"),
            ("", ""),
            (None, ""),
            ("B", "B"),
            ("B20", "B20"),
        ],
    )
    def test_normalization(self, raw, expected):
        assert normalize_uniformat_level3(raw) == expected


class TestUniformatCatalog:
    def test_essential_codes_present(self):
        # Codes structurants de l'audit BIM
        for code in ("A1010", "B2010", "C1010", "D2010", "E2010"):
            assert code in UNIFORMAT
            assert UNIFORMAT[code]  # label non vide
