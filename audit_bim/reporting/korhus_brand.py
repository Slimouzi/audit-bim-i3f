"""Shim de compatibilité — la charte est désormais BIMData.

Ce module est conservé pour ne pas casser les imports existants
(``from audit_bim.reporting.korhus_brand import find_logo``). Il
ré-exporte simplement l'API de :mod:`audit_bim.reporting.bimdata_brand`.

À supprimer une fois toutes les intégrations migrées vers
``bimdata_brand``.
"""

from __future__ import annotations

from .bimdata_brand import (
    WORDMARK,
    find_brand_kit_dir,
    find_logo,
)

__all__ = ["WORDMARK", "find_brand_kit_dir", "find_logo"]
