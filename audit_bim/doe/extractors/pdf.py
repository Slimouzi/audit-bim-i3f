"""Extracteur DOE PDF natif — pdfplumber + extraction de tableaux.

Couvre les PDF générés par export logiciel (texte sélectionnable). Pour
les PDF scannés (images), voir :mod:`audit_bim.doe.extractors.ocr`.

Algorithme :

1. Pour chaque page, extrait tous les tableaux via :meth:`pdfplumber.Page.extract_tables`.
2. Pour chaque tableau ayant ≥ 2 lignes, repère la ligne d'en-tête et
   convertit les lignes suivantes en :class:`DoeRecord` (helpers
   communs avec l'extracteur Excel).

Conventions d'en-têtes identiques à l'extracteur Excel — la
sémantique du document DOE est la même quelle que soit la source.
"""

from __future__ import annotations

from pathlib import Path

from ..models import DoeRecord
from ._common import detect_header, find_header_row, row_to_record


def parse_doe_pdf(pdf_path: str | Path) -> list[DoeRecord]:
    """Parse un PDF natif et extrait les DoeRecord depuis ses tableaux.

    Args:
        pdf_path: Chemin (str ou Path) vers le fichier PDF.

    Returns:
        Liste de ``DoeRecord``, tous tableaux et toutes pages
        confondues, dans l'ordre du document.

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
        ImportError: Si ``pdfplumber`` n'est pas installé.

    Note:
        Pour les PDF scannés (sans texte natif), cette fonction renvoie
        une liste vide. Utiliser :func:`audit_bim.doe.extractors.ocr.parse_doe_pdf_ocr`
        à la place, ou la fonction unifiée
        :func:`audit_bim.doe.extractors.parse_doe` qui auto-détecte.
    """
    import pdfplumber

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(path)

    records: list[DoeRecord] = []
    with pdfplumber.open(str(path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            for tbl_idx, table in enumerate(tables, start=1):
                if not table or len(table) < 2:
                    continue
                header_idx = find_header_row(table)
                if header_idx is None:
                    continue
                headers = list(table[header_idx])
                col_map = [detect_header(h) for h in headers]
                for row_i, row in enumerate(
                    table[header_idx + 1 :],
                    start=header_idx + 2,
                ):
                    rec = row_to_record(
                        headers,
                        list(row),
                        col_map,
                        # Source enrichie : page + table (utile pour debug)
                        source=f"{path}#page={page_num}&table={tbl_idx}",
                        row_index=row_i,
                    )
                    if rec is not None:
                        records.append(rec)
    return records


def is_pdf_scanned(pdf_path: str | Path, min_chars_per_page: int = 100) -> bool:
    """Détecte si un PDF est principalement scanné (peu/pas de texte natif).

    Stratégie pragmatique : si le PDF expose < ``min_chars_per_page``
    caractères par page en moyenne via ``page.extract_text()``, on
    considère qu'il s'agit d'un scan. Robuste aux PDF mixtes (page 1
    texte + autres scannées).

    Args:
        pdf_path: Chemin du PDF à analyser.
        min_chars_per_page: Seuil moyen sous lequel on bascule en OCR.
            Défaut 100 (un tableau natif fait typiquement ≥ 500 chars/page).

    Returns:
        ``True`` si OCR recommandé, ``False`` si le texte natif suffit.

    Raises:
        ImportError: Si ``pdfplumber`` n'est pas installé.
    """
    import pdfplumber

    with pdfplumber.open(str(pdf_path)) as pdf:
        n_pages = len(pdf.pages) or 1
        total_chars = sum(len(p.extract_text() or "") for p in pdf.pages)
    return total_chars < n_pages * min_chars_per_page
