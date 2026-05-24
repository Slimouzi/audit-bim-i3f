"""Extracteurs DOE — point d'entrée unifié avec auto-détection du format.

Exporte la fonction :func:`parse_doe` qui choisit l'extracteur approprié
selon l'extension du fichier et la présence de texte natif (PDF). Pour
appeler un extracteur spécifique, importer directement depuis le
sous-module concerné (``excel``, ``pdf``, ``ocr``).
"""

from __future__ import annotations

from pathlib import Path

from ..models import DoeRecord
from .excel import parse_doe_excel
from .pdf import is_pdf_scanned, parse_doe_pdf

__all__ = [
    "is_pdf_scanned",
    "parse_doe",
    "parse_doe_excel",
    "parse_doe_pdf",
]


_EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
_PDF_EXTENSIONS = {".pdf"}


def parse_doe(
    path: str | Path,
    *,
    ocr_fallback: bool = True,
    ocr_lang: str = "fra",
) -> list[DoeRecord]:
    """Parse un fichier DOE en auto-détectant son format.

    Args:
        path: Chemin (str ou Path) vers le fichier DOE (xlsx, xlsm ou pdf).
        ocr_fallback: Si ``True`` (défaut), bascule sur l'OCR Tesseract
            quand le PDF est détecté comme scanné (peu de texte natif).
            Nécessite l'install ``audit-bim-i3f[ocr]`` ET le binaire
            Tesseract.
        ocr_lang: Langue Tesseract si OCR utilisé (défaut ``"fra"``).

    Returns:
        Liste de :class:`DoeRecord` prête pour le matcher.

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
        ValueError: Si l'extension n'est pas supportée.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in _EXCEL_EXTENSIONS:
        return parse_doe_excel(p)
    if suffix in _PDF_EXTENSIONS:
        if ocr_fallback and is_pdf_scanned(p):
            from .ocr import is_tesseract_available, parse_doe_pdf_ocr

            if is_tesseract_available():
                return parse_doe_pdf_ocr(p, lang=ocr_lang)
            # Tesseract absent → on tente le parseur natif (renverra
            # probablement [] sur un PDF scanné, mais évite un crash).
        return parse_doe_pdf(p)
    raise ValueError(
        f"Format DOE non supporté : {suffix!r} pour {p.name!r}. "
        "Formats acceptés : .xlsx, .xlsm, .pdf."
    )
