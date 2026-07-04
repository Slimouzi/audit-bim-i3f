"""Ré-export : ``ModelSnapshot`` (contrat ``bim-core``) + ``extract_snapshot``
(noyau lecture ``bimdata-read``).

Chemins d'import historiques préservés
(``from audit_bim.extraction.model_data import ModelSnapshot, extract_snapshot``).
"""

from __future__ import annotations

from bim_core.model_snapshot import ModelSnapshot
from bimdata_read import extract_snapshot

__all__ = ["ModelSnapshot", "extract_snapshot"]
