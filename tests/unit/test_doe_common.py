"""Tests des helpers partagés des extracteurs DOE."""

from __future__ import annotations

import pytest

from audit_bim.doe.extractors._common import (
    DEFAULT_PSET,
    detect_header,
    find_header_row,
    normalize_header_text,
    row_to_record,
)


class TestNormalizeHeaderText:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("UUID", "uuid"),
            ("  Étage  ", "etage"),
            ("Désignation", "designation"),
            ("Pièce", "piece"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalization(self, raw, expected):
        assert normalize_header_text(raw) == expected


class TestDetectHeader:
    @pytest.mark.parametrize(
        "value,expected_slot",
        [
            ("UUID", "uuid"),
            ("uuid", "uuid"),
            ("GlobalId", "uuid"),
            ("Tag", "tag"),
            ("Mark", "tag"),
            ("Numéro", "tag"),
            ("Nom", "name"),
            ("Désignation", "name"),
            ("Type", "type"),
            ("Étage", "storey"),
            ("Niveau", "storey"),
            ("Zone", "zone"),
        ],
    )
    def test_known_alias(self, value, expected_slot):
        slot, pset_prop = detect_header(value)
        assert slot == expected_slot
        assert pset_prop is None

    def test_pset_dot_notation(self):
        slot, pset_prop = detect_header("Pset_3F.Fabricant")
        assert slot is None
        assert pset_prop == ("Pset_3F", "Fabricant")

    def test_pset_slash_notation(self):
        slot, pset_prop = detect_header("Pset_WallCommon/IsExternal")
        assert slot is None
        assert pset_prop == ("Pset_WallCommon", "IsExternal")

    def test_unknown_falls_back_to_default_pset(self):
        slot, pset_prop = detect_header("Référence commerciale")
        assert slot is None
        assert pset_prop == (DEFAULT_PSET, "Référence commerciale")

    def test_empty_returns_none(self):
        assert detect_header("") == (None, None)
        assert detect_header(None) == (None, None)


class TestRowToRecord:
    def test_minimal_record(self):
        headers = ["UUID", "Nom", "Pset_3F.Fabricant"]
        row = ["GUID-1", "Porte 01", "BOSCH"]
        col_map = [detect_header(h) for h in headers]
        rec = row_to_record(headers, row, col_map, source="x.xlsx", row_index=2)
        assert rec is not None
        assert rec.uuid_hint == "GUID-1"
        assert rec.name_hint == "Porte 01"
        assert rec.properties == {"Pset_3F": {"Fabricant": "BOSCH"}}
        assert rec.source == "x.xlsx"
        assert rec.row_index == 2

    def test_row_without_identifier_filtered(self):
        headers = ["Pset_3F.Fabricant"]
        row = ["BOSCH"]
        col_map = [detect_header(h) for h in headers]
        rec = row_to_record(headers, row, col_map, source="x.xlsx", row_index=3)
        assert rec is None

    def test_row_without_property_filtered(self):
        headers = ["UUID"]
        row = ["GUID-1"]
        col_map = [detect_header(h) for h in headers]
        rec = row_to_record(headers, row, col_map, source="x.xlsx", row_index=3)
        assert rec is None

    def test_empty_row_filtered(self):
        headers = ["UUID", "Nom"]
        row = [None, ""]
        col_map = [detect_header(h) for h in headers]
        rec = row_to_record(headers, row, col_map, source="x.xlsx", row_index=3)
        assert rec is None


class TestFindHeaderRow:
    def test_first_row_two_cells(self):
        rows = [["UUID", "Nom"], ["a", "b"]]
        assert find_header_row(rows) == 0

    def test_blank_lines_skipped(self):
        rows = [[None, None], ["", ""], ["UUID", "Nom", "Type"], ["a", "b", "c"]]
        assert find_header_row(rows) == 2

    def test_returns_none_if_no_header(self):
        rows = [[None], [""], [None, None]]
        assert find_header_row(rows) is None

    def test_max_scan_limit(self):
        # En-tête au-delà du max_scan → None
        rows = [[None, None]] * 15 + [["UUID", "Nom"]]
        assert find_header_row(rows, max_scan=10) is None
