"""Santé d'un instantané BIMData — signaux neutres, partagés par les profils.

Ce module ne juge pas la conformité d'une maquette : il dit si sa **lecture**
s'est bien passée. La distinction est ce qui le rend partageable — un défaut
d'extraction se constate de la même façon quel que soit le référentiel du client.

Le code vient **verbatim** de ``profiles/i3f/tools_session.py``, où il vivait
faute d'un second appelant. Il en a un depuis le profil BIM in Motion, et c'est
la seule raison de l'avoir déplacé : un socle sans deuxième consommateur reste
une hypothèse. Le déplacement ne change pas un caractère de la sortie d'I3F.
"""

from __future__ import annotations

__all__ = ["MODEL_STATUS_LABELS", "snapshot_diagnostics"]

#: Codes de statut de modèle BIMData, tels que renvoyés par l'API.
MODEL_STATUS_LABELS = {
    "C": "Completed",
    "D": "Deleted",
    "P": "Pending",
    "W": "Waiting",
    "I": "In Process",
    "E": "Error",
}


def snapshot_diagnostics(snapshot) -> dict:
    """Expose les signaux de sante du snapshot sans bloquer la connexion."""
    model = snapshot.model or {}
    status = model.get("status")
    errors = list(getattr(snapshot, "extraction_errors", None) or [])
    label = MODEL_STATUS_LABELS.get(status) if status else None

    health = "ok"
    warning = None
    if not model:
        health = "empty_model"
        warning = (
            "Snapshot sans metadonnees model : cible/auth potentiellement invalides "
            "ou extraction BIMData incomplete."
        )
    elif status and status != "C":
        health = "model_not_completed"
        warning = (
            f"Modele BIMData status={status!r}"
            + (f" ({label})" if label else "")
            + " : les donnees d'elements peuvent etre absentes ou instables."
        )
    elif errors:
        health = "partial"
        warning = "Snapshot partiel : une ou plusieurs routes BIMData ont echoue."
    elif not snapshot.elements:
        health = "empty_elements"
        warning = "Snapshot sans elements bruts : verifier que la maquette est bien exploitable."

    return {
        "snapshot_health": health,
        "snapshot_warning": warning,
        "model_status": status,
        "model_status_label": label,
        "n_extraction_errors": len(errors),
        "extraction_errors": errors,
    }
