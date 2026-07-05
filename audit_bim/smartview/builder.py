"""Builder Smart Views — **façade** au-dessus du package ``bim-publication``.

La construction pure des payloads Smart View vit désormais dans
``bim_publication.smartview``. Ce module conserve la **signature historique**
``build_smartview_payloads(result)`` en adaptant l'``AuditResult`` (findings +
phase + ``element_by_uuid`` du snapshot) ; ``build_smartview_payload_from_uuids``
est ré-exporté tel quel (déjà sans ``AuditResult``). ``push_smart_views`` (chemin
legacy avec client BIMData) reste ici — écriture distante, hors package.
"""

from __future__ import annotations

import bim_publication as _pub
from bim_publication import build_smartview_payload_from_uuids  # noqa: F401 — ré-export direct

from ..audit.engine import AuditResult
from ..extraction.client import BIMDataClient


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


def push_smart_views(
    result: AuditResult,
    client: BIMDataClient,
    *,
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
) -> list[dict]:
    """Crée (ou simule) les Smart Views. Chemin **legacy** (écriture directe) ;
    le pattern recommandé est ``prepare_smart_views`` → ``save_plan`` →
    ``apply_smart_views``.

    Returns:
        Liste de dicts ``{payload, response | error, dry_run}``.
    """
    payloads = build_smartview_payloads(result, prefix=prefix, model_id=client.model_id)
    out: list[dict] = []
    for p in payloads:
        if dry_run:
            out.append({"payload": p, "response": None, "dry_run": True})
            continue
        try:
            resp = client.create_bcf_full_topic(p)
            out.append({"payload": p, "response": resp, "dry_run": False})
        except Exception as e:
            out.append({"payload": p, "error": str(e), "dry_run": False})
    return out


__all__ = [
    "build_smartview_payloads",
    "build_smartview_payload_from_uuids",
    "push_smart_views",
]
