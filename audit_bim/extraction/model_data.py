"""Ré-export : ``ModelSnapshot`` (contrat ``bim-core``) + ``extract_snapshot``
(noyau lecture ``bimdata-read``).

Chemins d'import historiques préservés
(``from audit_bim.extraction.model_data import ModelSnapshot, extract_snapshot``).
"""

from __future__ import annotations

from bim_core.model_snapshot import ModelSnapshot
from bimdata_read import extract_snapshot

__all__ = ["ModelSnapshot", "extract_snapshot", "assert_snapshot_usable"]


def assert_snapshot_usable(snap: ModelSnapshot) -> None:
    """Refuse (``ValueError``) un snapshot **inexploitable** (C2).

    Deux cas où l'infra se déguiserait en métier si on continuait :
    - ``model`` vide → extraction BIMData échouée en amont (token expiré, cible
      injoignable) : l'audit rendrait « pas d'IfcSite/IfcBuilding » (CRITICAL
      spatial) au lieu d'une erreur d'authentification ;
    - ``extraction_errors`` non vide → snapshot **partiel** (une route a échoué,
      cf. ``bimdata_read.extract_snapshot``) : le verdict porterait sur des
      données tronquées.
    """
    if not snap.model:
        raise ValueError(
            "REFUS : snapshot vide (aucune donnée `model`) — extraction BIMData "
            "échouée (token expiré ? cible injoignable ?). Audit interrompu plutôt "
            "que de rendre un rapport faussement « modèle vide »."
        )
    errors = getattr(snap, "extraction_errors", None)
    if errors:
        raise ValueError(
            "REFUS : snapshot partiel — route(s) BIMData en échec : "
            + " ; ".join(errors)
            + ". Audit interrompu (le rapport serait tronqué)."
        )
