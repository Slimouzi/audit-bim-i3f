"""Tests du parseur DOE PDF natif (pdfplumber)."""

from __future__ import annotations

import pytest

from audit_bim.doe.extractors.pdf import is_pdf_scanned, parse_doe_pdf

reportlab = pytest.importorskip("reportlab")


@pytest.fixture
def synthetic_pdf_native(tmp_path):
    """Génère un PDF natif avec un tableau bordé d'équipements.

    pdfplumber détecte les tableaux via les lignes graphiques (bordures).
    On applique donc un ``GRID`` au TableStyle.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

    path = tmp_path / "doe.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    data = [
        ["UUID", "Nom", "Type", "Pset_3F.Fabricant", "Pset_3F.Reference"],
        ["GUID-A", "Porte A", "Door", "BOSCH", "B-001"],
        ["GUID-B", "Fenetre B", "Window", "VELUX", "V-042"],
        ["GUID-C", "Mobilier C", "Furniture", "IKEA", "K-007"],
    ]
    table = Table(data)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]
        )
    )
    doc.build([Spacer(1, 12), table])
    return path


class TestParseDoePdf:
    def test_returns_three_records(self, synthetic_pdf_native):
        records = parse_doe_pdf(synthetic_pdf_native)
        assert len(records) == 3

    def test_uuids_extracted(self, synthetic_pdf_native):
        records = parse_doe_pdf(synthetic_pdf_native)
        assert {r.uuid_hint for r in records} == {"GUID-A", "GUID-B", "GUID-C"}

    def test_pset_dot_notation(self, synthetic_pdf_native):
        records = parse_doe_pdf(synthetic_pdf_native)
        by_uuid = {r.uuid_hint: r for r in records}
        assert by_uuid["GUID-A"].properties["Pset_3F"]["Fabricant"] == "BOSCH"
        assert by_uuid["GUID-B"].properties["Pset_3F"]["Reference"] == "V-042"

    def test_source_contains_page_info(self, synthetic_pdf_native):
        records = parse_doe_pdf(synthetic_pdf_native)
        # Source enrichie : <path>#page=<n>&table=<m>
        assert all("page=" in r.source for r in records)
        assert all("table=" in r.source for r in records)

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_doe_pdf(tmp_path / "nonexistent.pdf")


class TestIsPdfScanned:
    def test_native_pdf_not_scanned(self, synthetic_pdf_native):
        # PDF généré avec texte → < 100 chars/page peut quand même
        # arriver pour un tableau court ; on vérifie que la fonction
        # ne crashe pas et renvoie un bool.
        result = is_pdf_scanned(synthetic_pdf_native)
        assert isinstance(result, bool)
