"""Builder Smart Views — **façade** au-dessus du package ``bim-publication``.

La construction pure des payloads Smart View vit dans
``bim_publication.smartview``. Ce module conserve la **signature historique**
``build_smartview_payloads(result)`` en adaptant l'``AuditResult`` (findings +
phase + ``element_by_uuid`` du snapshot) ; ``build_smartview_payload_from_uuids``
est ré-exporté tel quel (déjà sans ``AuditResult``).

Depuis la v0.5.0, le chemin d'écriture directe ``push_smart_views`` a été
**supprimé** : toute publication passe par ``prepare_smart_views`` →
``save_plan`` → ``apply_smart_views`` (workflow prepare → review → apply).
"""

from __future__ import annotations

import bim_publication as _pub
from bim_publication import build_smartview_payload_from_uuids  # noqa: F401 — ré-export direct

from ..audit.engine import AuditResult


def build_smartview_payloads(
    result: AuditResult,
    *,
    prefix: str = "I3F Audit — ",
    model_id: int | str | None = None,
    include_overview: bool = True,
) -> list[dict]:
    """Produit les payloads Smart View (délégué à ``bim_publication``).

    Adapte l'``AuditResult`` : ``findings`` + ``phase`` + l'index
    ``element_by_uuid`` du snapshot (noms Revit/CAO). Payloads **identiques**
    à l'implémentation historique.
    """
    element_by_uuid = getattr(result.snapshot, "element_by_uuid", None) or {}
    return _pub.build_smartview_payloads(
        result.findings,
        phase=result.phase.value,
        prefix=prefix,
        model_id=model_id,
        include_overview=include_overview,
        element_by_uuid=element_by_uuid,
    )


__all__ = [
    "build_smartview_payloads",
    "build_smartview_payload_from_uuids",
]
