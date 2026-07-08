"""Lot 5 (audit profond 2ᵉ passe) — un xlsx corrompu produit une erreur claire.

``openpyxl.load_workbook`` sur un fichier tronqué/non-zip lève un ``BadZipFile``
brut, peu parlant côté client. On le convertit en ``ValueError`` métier.
"""

from __future__ import annotations

import pytest

from audit_bim.classifier.xlsx_reader import read_classifications_from_xlsx


def test_corrupt_xlsx_raises_clear_error(tmp_path):
    bad = tmp_path / "corrompu.xlsx"
    bad.write_bytes(b"ceci n'est pas un classeur xlsx")
    with pytest.raises(ValueError, match="corrompu"):
        read_classifications_from_xlsx(bad)


def test_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_classifications_from_xlsx(tmp_path / "absent.xlsx")
