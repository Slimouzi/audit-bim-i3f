"""Tests des lecteurs de sources I3F du pack AVP (``avp_sources``).

Sources synthétiques (openpyxl) reproduisant la structure I3F, pour ne
dépendre d'aucun fichier client dans le dépôt / la CI.
"""

from __future__ import annotations

import openpyxl
import pytest

from audit_bim.reporting import avp_sources as S


def _write(path, sheet_rows: dict[str, list[list]]):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheet_rows.items():
        ws = wb.create_sheet(title=name[:31])
        for r in rows:
            ws.append(r)
    wb.save(str(path))
    return path


def test_read_enveloppe(tmp_path):
    path = _write(
        tmp_path / "env.xlsx",
        {
            "TDB 2022 04.2 - Extraction s": [
                ["Composant", "Type", "Étages", "Archicad BQ NetSideArea", "Surface Solibri"],
                ["Mur", "ME_36", "RDC", 313.14, 325.33],
                ["Mur", "ME_20", "R+1", 100.0, 101.0],
                [],
                [None, None, "Superficie des façades : ", 2071.19, 2084.4],
                [None, None, "SHAB : ", 2164.98],
                [None, None, "ratio FAC/SHAB : ", 0.9567],
                [None, None, "Seuil 3F 2026 : ", 0.9],
            ]
        },
    )
    src = S.read_enveloppe(path)
    assert src.table is not None
    assert src.table.headers[:3] == ["Composant", "Type", "Étages"]
    assert src.table.n_rows == 2  # bloc synthèse exclu de la table
    assert src.ratio_fac_shab == pytest.approx(0.9567)
    assert src.seuil_3f == pytest.approx(0.9)
    assert src.shab == pytest.approx(2164.98)


def test_read_menuiseries(tmp_path):
    path = _write(
        tmp_path / "men.xlsx",
        {
            "TDB 2022 05.1 - Fenêtres Ok": [
                ["Composant", "Type", "Matériau", "BaseQuantities.Width", "Largeur"],
                ["Fenêtre", "F25", None, 0.6, 0.6],
                ["Fenêtre", "F30", None, 0.8, 0.8],
                [None, "Nombre de types de menuiseries", 2],
            ]
        },
    )
    src = S.read_menuiseries(path)
    assert src.table is not None
    assert src.table.n_rows == 2  # ligne « Nombre de types » écartée
    assert src.nombre_types == 2


def test_read_controle_header_legend_grille_stats(tmp_path):
    path = _write(
        tmp_path / "ctrl.xlsx",
        {
            "Grille de contrôle": [
                [],
                [None, "Projet", "Tarare"],
                [None, "ESI", "0546L"],
                [None, "Phase", "AVP"],
                [None, None, None, None, 0, "Non fourni / non trouvé"],
                [None, None, None, None, 1, "Insuffisant"],
                [None, None, None, None, 2, "Satisfaisant"],
                [
                    "CODE 3F",
                    "POINTS DE CONTROLE",
                    "EXIGENCE CCH BIM 3F",
                    "Outil utilisé",
                    "EVALUATION",
                    "Commentaires CdP Bim",
                ],
                ["1.1", "Conformité plans", "les plans…", "", "nc", "non testé"],
                ["4.1", "Présence de zones", "6.1.2", "", 2, ""],
            ],
            "Pièces Nommage": [
                [],
                [None, "0546L"],
                [None, "0546L"],
                [],
                ["onglet", "Pièces Nommage"],
                [None, None, "MN", None, "Conforme", None, "Non Conforme"],
                [None, "Nombre de Noms", 316, 247, 0.7816, 16, 0.0506],
            ],
        },
    )
    src = S.read_controle(path)
    assert src.header.get("projet") == "Tarare"
    assert src.header.get("esi") == "0546L"
    assert src.legend == {0: "Non fourni / non trouvé", 1: "Insuffisant", 2: "Satisfaisant"}
    assert src.grille is not None
    assert src.grille.headers == [
        "CODE 3F",
        "POINTS DE CONTROLE",
        "EXIGENCE CCH BIM 3F",
        "Outil utilisé",
        "EVALUATION",
        "Commentaires CdP Bim",
    ]
    assert src.grille.n_rows == 2
    stats = src.stats.get("Pièces Nommage")
    assert (
        stats and stats["total"] == 316 and stats["conforme"] == 247 and stats["non_conforme"] == 16
    )


def test_missing_sources_stay_none():
    out = S.load_sources(S.AvpSourcePaths())  # aucun chemin fourni
    assert out.controle is None
    assert out.shab is None
    assert out.enveloppe is None
    assert out.menuiseries is None
    assert out.zones_espaces is None
