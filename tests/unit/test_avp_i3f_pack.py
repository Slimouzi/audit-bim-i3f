"""Tests du pack de livrables AVP I3F (``avp_i3f``).

Sources synthétiques (openpyxl) → génération → relecture. Couvre :
structure d'onglets, ordre des en-têtes, charte BIMData, absence de
l'ancienne charte, principe « ne jamais inventer », sections du consolidé.
"""

from __future__ import annotations

import zipfile

import openpyxl
import pytest
from docx import Document

from audit_bim.reporting.avp_i3f import write_avp_i3f_report_pack
from audit_bim.reporting.avp_sources import AvpSourcePaths
from audit_bim.reporting.pdf_export import docx_to_pdf


def _wb(path, sheet_rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheet_rows.items():
        ws = wb.create_sheet(title=name[:31])
        for r in rows:
            ws.append(r)
    wb.save(str(path))
    return path


@pytest.fixture
def sources(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    enveloppe = _wb(
        src_dir / "env.xlsx",
        {
            "TDB 2022 04.2": [
                ["Composant", "Type", "Étages", "Archicad BQ NetSideArea", "Surface Solibri"],
                ["Mur", "ME_36", "RDC", 313.14, 325.33],
                [],
                [None, None, "ratio FAC/SHAB : ", 0.9567],
                [None, None, "Seuil 3F 2026 : ", 0.9],
                [None, None, "SHAB : ", 2164.98],
            ]
        },
    )
    shab = _wb(
        src_dir / "shab.xlsx",
        {
            "TDB 2022 01.3 - Export Zones": [
                ["Composant", "Nom Zone", "Pièce", "Surface Nette (Qté de Base)", "Étage"],
                ["Zone", "0546L-1101", "CHAMBRE 01", 12.98, "R+1"],
            ]
        },
    )
    zones = _wb(
        src_dir / "zones.xlsx",
        {
            "TDB 2022 01.3 - Export Zones": [
                ["Composant", "Nom Zone", "Pièce (Nombre)", "Surface Nette (Qté de Base)"],
                ["Zone", "0546L-1101", "CHAMBRE 01", 12.98],
            ]
        },
    )
    menuiseries = _wb(
        src_dir / "men.xlsx",
        {
            "TDB 2022 05.1 - Fenêtres": [
                ["Composant", "Type", "Matériau", "Largeur", "Hauteur"],
                ["Fenêtre", "F25", None, 0.6, 1.3],
                [None, "Nombre de types de menuiseries", 1],
            ]
        },
    )
    controle = _wb(
        src_dir / "ctrl.xlsx",
        {
            "Grille de contrôle": [
                [None, "Projet", "Tarare"],
                [None, "ESI", "0546L"],
                [None, "Phase", "AVP"],
                [None, None, None, None, 0, "Non fourni / non trouvé"],
                [None, None, None, None, 2, "Satisfaisant"],
                [
                    "CODE 3F",
                    "POINTS DE CONTROLE",
                    "EXIGENCE CCH BIM 3F",
                    "Outil utilisé",
                    "EVALUATION",
                    "Commentaires CdP Bim",
                ],
                ["1.1", "Conformité plans", "les plans…", "", 0, "non testé"],
                ["4.1", "Présence de zones", "6.1.2", "", 2, ""],
            ],
            "Pièces Nommage": [
                [None, "Nombre de Noms"],
                [None, None, "MN", None, "Conforme", None, "Non Conforme"],
                [None, "Nombre de Noms", 316, 247, 0.7816, 16, 0.0506],
            ],
        },
    )
    return AvpSourcePaths(
        controle=controle,
        shab=shab,
        zones_espaces=zones,
        enveloppe=enveloppe,
        menuiseries=menuiseries,
    )


def _find_row(ws, anchor):
    for r in range(1, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            if ws.cell(r, c).value == anchor:
                return r
    return None


# ── Structure ──────────────────────────────────────────────────────────


def test_pack_generates_six_deliverables(tmp_path, sources):
    pack = write_avp_i3f_report_pack(None, tmp_path / "out", sources=sources, export_pdf=False)
    assert len(pack.paths()) == 6
    for p in pack.paths():
        assert p.exists() and p.stat().st_size > 0


def test_controle_has_expected_sheets(tmp_path, sources):
    pack = write_avp_i3f_report_pack(None, tmp_path / "out", sources=sources, export_pdf=False)
    wb = openpyxl.load_workbook(pack.controle_xlsx)
    assert wb.sheetnames == [
        "Grille de contrôle",
        "Zones Nommage",
        "Pièces Nommage",
        "ARC absence de matériau",
        "Zones ObjectType",
    ]
    wb.close()


def test_export_headers_order_preserved(tmp_path, sources):
    pack = write_avp_i3f_report_pack(None, tmp_path / "out", sources=sources, export_pdf=False)
    wb = openpyxl.load_workbook(pack.enveloppe_xlsx)
    ws = wb.active
    hr = _find_row(ws, "Composant")
    assert hr is not None
    headers = [ws.cell(hr, c).value for c in range(1, 6)]
    assert headers == ["Composant", "Type", "Étages", "Archicad BQ NetSideArea", "Surface Solibri"]
    wb.close()


def test_enveloppe_summary_block(tmp_path, sources):
    pack = write_avp_i3f_report_pack(None, tmp_path / "out", sources=sources, export_pdf=False)
    wb = openpyxl.load_workbook(pack.enveloppe_xlsx)
    ws = wb.active
    r = _find_row(ws, "ratio FAC/SHAB")
    assert r is not None and ws.cell(r, 2).value == pytest.approx(0.9567)
    r2 = _find_row(ws, "Seuil 3F 2026")
    assert r2 is not None and ws.cell(r2, 2).value == pytest.approx(0.9)
    wb.close()


# ── Charte BIMData ───────────────────────────────────────────────────────


def test_bimdata_branding(tmp_path, sources):
    pack = write_avp_i3f_report_pack(None, tmp_path / "out", sources=sources, export_pdf=False)
    wb = openpyxl.load_workbook(pack.enveloppe_xlsx)
    ws = wb.active
    # Bannière BIMDATA.
    assert str(ws["A1"].value).startswith("BIMDATA —")
    # En-tête de table : fond primaire 2F374A, police Roboto.
    hr = _find_row(ws, "Composant")
    cell = ws.cell(hr, 1)
    assert (cell.fill.fgColor.rgb or "").upper().endswith("2F374A")
    assert cell.font.name == "Roboto"
    wb.close()


def test_no_old_charter_in_outputs(tmp_path, sources):
    pack = write_avp_i3f_report_pack(None, tmp_path / "out", sources=sources, export_pdf=False)
    for p in pack.paths():
        with zipfile.ZipFile(p) as z:
            blob = b"".join(z.read(n) for n in z.namelist() if n.endswith((".xml", ".rels")))
        assert b"KORHUS" not in blob.upper(), f"ancienne charte trouvée dans {p.name}"
        assert b"BIMDATA" in blob.upper()


# ── Ne jamais inventer ───────────────────────────────────────────────────


def test_never_invent_without_sources(tmp_path):
    pack = write_avp_i3f_report_pack(None, tmp_path / "out", sources=None, export_pdf=False)
    wb = openpyxl.load_workbook(pack.enveloppe_xlsx)
    ws = wb.active
    seen = {str(c.value) for row in ws.iter_rows() for c in row if isinstance(c.value, str)}
    assert any("Information non disponible dans les documents fournis" in v for v in seen)
    wb.close()


# ── Consolidé ────────────────────────────────────────────────────────────


def test_consolidated_docx_sections(tmp_path, sources):
    pack = write_avp_i3f_report_pack(None, tmp_path / "out", sources=sources, export_pdf=False)
    doc = Document(str(pack.analyse_docx))
    txt = "\n".join(p.text for p in doc.paragraphs)
    for section in (
        "Analyse BIM",
        "1. Synthèse",
        "2. Indicateurs de conformité",
        "3. Écarts",
        "4. Points bloquants",
        "5. Recommandations AMO BIM",
    ):
        assert section in txt, f"section manquante : {section}"


# ── PDF best-effort ──────────────────────────────────────────────────────


def test_pdf_export_none_when_engine_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_BIM_SOFFICE", str(tmp_path / "no-such-soffice"))
    monkeypatch.setattr("shutil.which", lambda name: None)
    docx = tmp_path / "x.docx"
    Document().save(str(docx))
    assert docx_to_pdf(docx) is None
