"""Builder de BCF Topics — **façade** au-dessus du package ``bim-publication``.

La construction pure des payloads BCF vit désormais dans
``bim_publication.bcf`` (dépend de ``bim-core`` + ``bim-query``, sans réseau).
Ce module conserve la **signature historique** ``build_bcf_payloads(result)`` en
adaptant l'``AuditResult`` audit-bim vers l'entrée primitive du package
(``findings`` + ``phase``). ``push_bcf_topics`` (chemin legacy avec client
BIMData) reste ici — il relève de l'écriture distante, hors package.
"""

from __future__ import annotations

import bim_publication as _pub

from ..audit.engine import AuditResult
from ..extraction.client import BIMDataClient


def build_bcf_payloads(
    result: AuditResult,
    *,
    prefix: str = "I3F Audit — ",
    model_id: int | str | None = None,
    include_overview: bool = True,
) -> list[dict]:
    """Produit les payloads BCF Topics (délégué à ``bim_publication``).

    Adapte l'``AuditResult`` vers l'entrée primitive du package
    (``findings`` + ``phase``). Payloads **identiques** à l'implémentation
    historique (corps extrait verbatim).
    """
    return _pub.build_bcf_payloads(
        result.findings,
        phase=result.phase.value,
        prefix=prefix,
        model_id=model_id,
        include_overview=include_overview,
    )


def push_bcf_topics(
    result: AuditResult,
    client: BIMDataClient,
    *,
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
) -> list[dict]:
    """Crée (ou simule) les BCF Topics sur le projet BIMData.

    Chemin **legacy** (écriture directe sans plan scellé). Le pattern
    recommandé est ``prepare_bcf`` → ``save_plan`` → ``apply_bcf``.

    Args:
        result: résultat d'audit.
        client: client BIMData authentifié.
        prefix: préfixe du titre des topics.
        dry_run: si ``True``, renvoie les payloads sans POST.

    Returns:
        Liste ``[{payload, response | error, dry_run}]``.
    """
    payloads = build_bcf_payloads(result, prefix=prefix, model_id=client.model_id)
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


__all__ = ["build_bcf_payloads", "push_bcf_topics"]
