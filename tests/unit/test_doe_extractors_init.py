"""Tests du point d'entrée unifié ``parse_doe`` (auto-détection format)."""

from __future__ import annotations

import pytest
import xlsxwriter

from audit_bim.doe.extractors import parse_doe


@pytest.fixture
def simple_xlsx(tmp_path):
    path = tmp_path / "doe.xlsx"
    wb = xlsxwriter.Workbook(str(path))
    ws = wb.add_worksheet()
    ws.write_row(0, 0, ["UUID", "Nom", "Pset_3F.Fabricant"])
    ws.write_row(1, 0, ["GUID-X", "Élément X", "BOSCH"])
    wb.close()
    return path


class TestAutoDetection:
    def test_xlsx_routed_to_excel(self, simple_xlsx):
        records = parse_doe(simple_xlsx)
        assert len(records) == 1
        assert records[0].uuid_hint == "GUID-X"

    def test_xlsm_extension_supported(self, tmp_path):
        # Les .xlsm sont traités comme des .xlsx (même format ZIP)
        path = tmp_path / "doe.xlsm"
        wb = xlsxwriter.Workbook(str(path))
        wb.add_worksheet().write_row(0, 0, ["UUID", "Pset_3F.X"])
        wb.add_worksheet().write_row(1, 0, ["A", "B"])
        wb.close()
        # Smoke test : ne crashe pas
        parse_doe(path)

    def test_unsupported_extension_raises(self, tmp_path):
        path = tmp_path / "doe.txt"
        path.write_text("not a real DOE file")
        with pytest.raises(ValueError, match="non supporté"):
            parse_doe(path)
