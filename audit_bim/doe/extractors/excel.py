"""Extracteur DOE Excel — convertit un xlsx d'équipements en ``DoeRecord``.

Conventions souples (cf. :mod:`audit_bim.doe.extractors._common`) :

- En-têtes connues : ``UUID`` / ``Tag`` / ``Mark`` / ``Nom`` / ``Type`` /
  ``Étage`` / ``Zone`` (insensible à la casse, tolérant aux accents).
- En-têtes propriétés : ``Pset_3F.Fabricant`` ou ``Pset_3F/Fabricant``
  pour cibler un Pset précis. Sinon, la propriété va dans ``Pset_DOE`` par
  défaut.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl

from ...requirements._openpyxl_compat import patch_openpyxl
from ..models import DoeRecord
from ._common import detect_header, find_header_row, row_to_record

patch_openpyxl()


def parse_doe_excel(xlsx_path: str | Path) -> list[DoeRecord]:
    """Parse un fichier DOE Excel multi-feuilles.

    Algorithme par feuille :

    1. Cherche la **ligne d'en-tête** (1ère ligne ≥ 2 cellules non vides
       parmi les 10 premières).
    2. Mappe chaque colonne via :func:`detect_header`.
    3. Pour chaque ligne suivante, construit un :class:`DoeRecord` via
       :func:`row_to_record` (qui filtre les lignes sans identifiant ou
       sans propriété).

    Args:
        xlsx_path: Chemin (str ou Path) vers le fichier xlsx du DOE.

    Returns:
        Liste de ``DoeRecord``, toutes feuilles confondues, dans l'ordre
        du classeur.

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
    """
    path = Path(xlsx_path)
    if not path.exists():
        raise FileNotFoundError(path)

    wb = openpyxl.load_workbook(path, data_only=True)
    records: list[DoeRecord] = []
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue
            header_idx = find_header_row(rows)
            if header_idx is None:
                continue
            headers = list(rows[header_idx])
            col_map = [detect_header(h) for h in headers]
            for row_i, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
                rec = row_to_record(
                    headers,
                    list(row),
                    col_map,
                    source=str(path),
                    row_index=row_i,
                )
                if rec is not None:
                    records.append(rec)
    finally:
        wb.close()
    return records
