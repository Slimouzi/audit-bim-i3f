"""Tests du module ``audit_bim.doe.extractors.excel``."""
from __future__ import annotations

import pytest
import xlsxwriter

from audit_bim.doe.extractors.excel import parse_doe_excel


@pytest.fixture
def synthetic_doe(tmp_path):
    """Crée un DOE Excel de test temporaire."""
    path = tmp_path / "doe.xlsx"
    wb = xlsxwriter.Workbook(str(path))
    ws = wb.add_worksheet("DOE")
    ws.write_row(0, 0, ["UUID", "Nom", "Type", "Pset_3F.Fabricant", "Pset_3F.Reference"])
    ws.write_row(1, 0, ["GUID-A", "Porte A", "Door", "BOSCH", "B-001"])
    ws.write_row(2, 0, ["GUID-B", "Fenêtre B", "Window", "VELUX", "V-042"])
    ws.write_row(3, 0, ["", "INCOMPLET sans props", "", "", ""])  # ne sera pas gardé
    wb.close()
    return path


class TestParseDoeExcel:
    def test_returns_records(self, synthetic_doe):
        records = parse_doe_excel(synthetic_doe)
        assert len(records) == 2  # la 3e ligne sans props est filtrée

    def test_uuid_extracted(self, synthetic_doe):
        records = parse_doe_excel(synthetic_doe)
        assert records[0].uuid_hint == "GUID-A"
        assert records[1].uuid_hint == "GUID-B"

    def test_name_extracted(self, synthetic_doe):
        records = parse_doe_excel(synthetic_doe)
        assert records[0].name_hint == "Porte A"

    def test_type_extracted(self, synthetic_doe):
        records = parse_doe_excel(synthetic_doe)
        assert records[0].type_hint == "Door"

    def test_pset_dot_notation_parsed(self, synthetic_doe):
        records = parse_doe_excel(synthetic_doe)
        assert "Pset_3F" in records[0].properties
        assert records[0].properties["Pset_3F"]["Fabricant"] == "BOSCH"
        assert records[0].properties["Pset_3F"]["Reference"] == "B-001"

    def test_row_index_starts_at_2(self, synthetic_doe):
        # Ligne 1 = en-tête, données commencent ligne 2
        records = parse_doe_excel(synthetic_doe)
        assert records[0].row_index == 2

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_doe_excel(tmp_path / "nonexistent.xlsx")


@pytest.fixture
def doe_with_default_pset(tmp_path):
    """DOE sans convention Pset.Prop → propriétés vont dans Pset_DOE."""
    path = tmp_path / "doe2.xlsx"
    wb = xlsxwriter.Workbook(str(path))
    ws = wb.add_worksheet()
    ws.write_row(0, 0, ["UUID", "Nom", "Marque commerciale"])
    ws.write_row(1, 0, ["GUID-X", "Élément X", "LEGRAND"])
    wb.close()
    return path


def test_default_pset_used(doe_with_default_pset):
    records = parse_doe_excel(doe_with_default_pset)
    assert len(records) == 1
    # "Marque commerciale" sans convention → Pset_DOE
    assert "Pset_DOE" in records[0].properties
    assert records[0].properties["Pset_DOE"]["Marque commerciale"] == "LEGRAND"
