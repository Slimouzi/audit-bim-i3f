"""Ré-export : ``ModelSnapshot`` (contrat ``bim-core``) + ``extract_snapshot``
(noyau lecture ``bimdata-read``).

Chemins d'import historiques préservés
(``from audit_bim.extraction.model_data import ModelSnapshot, extract_snapshot``).
"""

from __future__ import annotations

from bim_core.model_snapshot import ModelSnapshot
from bimdata_read import extract_snapshot

__all__ = ["ModelSnapshot", "extract_snapshot", "assert_snapshot_usable"]

# Statuts de traitement d'un modèle BIMData. Seul ``C`` (Completed) est
# exploitable : les autres n'ont pas (encore) de données d'éléments utilisables.
_MODEL_STATUS_LABELS = {
    "C": "Completed",
    "D": "Deleted",
    "P": "Pending",
    "W": "Waiting",
    "I": "In Process",
    "E": "Error",
}
_MODEL_STATUS_HINT = {
    "D": "modèle supprimé — cible un modèle courant.",
    "E": "traitement IFC en erreur — re-uploader / corriger la maquette.",
    "P": "traitement IFC en cours — réessaie quand status=C (Completed).",
    "W": "traitement IFC en attente — réessaie quand status=C (Completed).",
    "I": "traitement IFC en cours — réessaie quand status=C (Completed).",
}


def assert_snapshot_usable(snap: ModelSnapshot) -> None:
    """Refuse (``ValueError``) un snapshot **inexploitable** (C2).

    Cas où l'infra se déguiserait en métier si on continuait :
    - ``model`` vide → extraction BIMData échouée en amont (token expiré, cible
      injoignable) : l'audit rendrait « pas d'IfcSite/IfcBuilding » (CRITICAL
      spatial) au lieu d'une erreur d'authentification ;
    - ``model.status`` ≠ ``C`` → modèle supprimé / en cours de traitement / en
      erreur : le message nomme la **cause métier** plutôt qu'un snapshot vide ;
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
    status = (snap.model or {}).get("status")
    if status and status != "C":
        label = _MODEL_STATUS_LABELS.get(status, status)
        hint = _MODEL_STATUS_HINT.get(status, "modèle non exploitable pour l'audit.")
        raise ValueError(
            f"REFUS : modèle BIMData non exploitable (status={status!r} = {label}) — "
            f"{hint} Audit interrompu (aucune donnée d'éléments fiable)."
        )
    errors = getattr(snap, "extraction_errors", None)
    if errors:
        raise ValueError(
            "REFUS : snapshot partiel — route(s) BIMData en échec : "
            + " ; ".join(errors)
            + ". Audit interrompu (le rapport serait tronqué)."
        )
