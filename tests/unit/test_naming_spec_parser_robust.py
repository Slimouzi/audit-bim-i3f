"""Medium (audit profond 2ᵉ passe) — robustesse du parseur zones/pièces
(``naming_spec_parser``) :

- **en-tête tolérant** : un intitulé légèrement différent (accents, « des/de »
  variables) ne doit plus faire rater le tableau (→ listes vides → contrôles
  d'audit silencieusement désactivés) ;
- **cellules mergées PP/PC** : openpyxl ne renvoie la valeur que sur la cellule
  d'ancrage du merge ; la localisation est reportée sur les lignes suivantes au
  lieu de retomber à tort sur « PP » (zones) ou de perdre la ligne (pièces).
"""

from __future__ import annotations

import openpyxl
import pytest

from audit_bim.requirements.naming_spec_parser import parse_naming_spec


def _write(ws, row: int, values: dict[int, object]) -> None:
    for col, val in values.items():
        ws.cell(row=row, column=col + 1, value=val)  # openpyxl 1-based


def _make_xlsx(tmp_path, header: str):
    """Feuille zones/pièces : en-tête ``header`` puis 2 zones + 2 pièces dont la
    colonne PP/PC n'est renseignée que sur la 1re ligne (simule un merge)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "6,3,2 zones et pieces"
    _write(ws, 1, {0: header})
    # cols zones : A=name B=type C=loc D=def ; pièces : F=name G=type H=loc I=def
    _write(
        ws, 2, {0: "1802L-1", 1: "Zone Logement T2", 2: "PC", 5: "CHAMBRE", 6: "Chambre", 7: "PP"}
    )
    _write(ws, 3, {0: "1802L-2", 1: "Zone Logement T3", 5: "CUISINE", 6: "Cuisine"})  # loc mergée
    path = tmp_path / "naming.xlsx"
    wb.save(path)
    return path


@pytest.mark.parametrize(
    "header",
    [
        "Liste des types de zones",  # canonique
        "Liste des types zones",  # « de » manquant
        "Liste des types de zônes",  # accent parasite
    ],
)
def test_tolerant_header_detects_table(tmp_path, header):
    _, _, zones, rooms = parse_naming_spec(_make_xlsx(tmp_path, header))
    assert {z.type_label for z in zones} == {"Zone Logement T2", "Zone Logement T3"}
    assert {r.name for r in rooms} == {"CHAMBRE", "CUISINE"}


def test_unrelated_header_does_not_match(tmp_path):
    # Un intitulé sans les 3 tokens ne doit pas activer le tableau.
    _, _, zones, rooms = parse_naming_spec(_make_xlsx(tmp_path, "Bloc de commentaires divers"))
    assert zones == []
    assert rooms == []


def test_merged_localisation_is_forward_filled(tmp_path):
    _, _, zones, rooms = parse_naming_spec(_make_xlsx(tmp_path, "Liste des types de zones"))
    # Zone 2 hérite du PC de la zone 1 (colonne mergée) au lieu du défaut PP.
    by_type = {z.type_label: z.localisation for z in zones}
    assert by_type["Zone Logement T2"] == "PC"
    assert by_type["Zone Logement T3"] == "PC"
    # Pièce 2 hérite du PP de la pièce 1 (au lieu d'être perdue).
    by_room = {r.name: r.localisation for r in rooms}
    assert by_room["CHAMBRE"] == "PP"
    assert by_room["CUISINE"] == "PP"
