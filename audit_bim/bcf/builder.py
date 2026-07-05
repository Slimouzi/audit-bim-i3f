"""Builder de BCF Topics — **façade** au-dessus du package ``bim-publication``.

La construction pure des payloads BCF vit dans ``bim_publication.bcf`` (dépend de
``bim-core`` + ``bim-query``, sans réseau). Ce module conserve la **signature
historique** ``build_bcf_payloads(result)`` en adaptant l'``AuditResult`` audit-bim
vers l'entrée primitive du package (``findings`` + ``phase``).

Depuis la v0.5.0, le chemin d'écriture directe ``push_bcf_topics`` a été
**supprimé** : toute publication passe par ``prepare_bcf`` → ``save_plan`` →
``apply_bcf`` (workflow prepare → review → apply, cf. preuve A1).
"""

from __future__ import annotations

import bim_publication as _pub

from ..audit.engine import AuditResult


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


__all__ = ["build_bcf_payloads"]
