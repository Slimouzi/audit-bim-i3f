"""Builder de Smart Views BIMData — 1 vue par thème d'audit.

Convention (ajustable via ``BIMDATA_SMARTVIEW_PATH``) :

    POST {base}/cloud/{cloud_id}/project/{project_id}{BIMDATA_SMARTVIEW_PATH}

Payload supposé :

    {
        "name": "I3F Audit — <thème>",
        "description": "...",
        "model_uuid": "<model_id>",
        "elements": ["<uuid1>", "<uuid2>", ...],   # éléments en erreur
        "color": "#RRGGBB"
    }

L'API exacte peut différer selon le tenant BIMData : on isole la création
dans une seule méthode pour faciliter l'ajustement. Mode ``dry_run`` (par
défaut) qui ne fait que retourner les payloads — pratique pour valider avant
de pousser.
"""
from __future__ import annotations

from typing import Optional

from ..audit.engine import AuditResult
from ..audit.findings import Theme
from ..extraction.client import BIMDataClient
from ..reporting.theming import THEME_COLORS


def _payload_for_theme(
    theme: Theme,
    uuids: list[str],
    *,
    model_id: int | str | None,
    prefix: str,
) -> dict:
    return {
        "name": f"{prefix}{theme.value}",
        "description": (
            "Smart View générée automatiquement par l'audit BIM I3F : "
            f"éléments concernés par le thème « {theme.value} »."
        ),
        "model_uuid": model_id,
        "elements": uuids,
        "color": f"#{THEME_COLORS.get(theme.value, '888888')}",
    }


def build_smartview_payloads(
    result: AuditResult,
    *,
    prefix: str = "I3F Audit — ",
    model_id: int | str | None = None,
) -> list[dict]:
    """Produit la liste des payloads (1 par thème ayant des UUID en erreur)."""
    by_theme: dict[Theme, list[str]] = {}
    for f in result.findings:
        if not f.element_uuid:
            continue
        by_theme.setdefault(f.theme, []).append(f.element_uuid)

    payloads = []
    for theme, uuids in by_theme.items():
        # Déduplication tout en préservant l'ordre d'apparition
        seen, ordered = set(), []
        for u in uuids:
            if u not in seen:
                seen.add(u)
                ordered.append(u)
        if not ordered:
            continue
        payloads.append(_payload_for_theme(theme, ordered, model_id=model_id, prefix=prefix))
    return payloads


def push_smart_views(
    result: AuditResult,
    client: BIMDataClient,
    *,
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
) -> list[dict]:
    """Crée (ou simule) les smart views sur BIMData.

    Args:
        result: résultat d'audit.
        client: client BIMData authentifié.
        prefix: préfixe du nom des vues (utile pour les itérations).
        dry_run: si ``True``, ne fait *pas* l'appel POST et renvoie seulement
            les payloads — usage : revue avant push.

    Returns:
        Liste des résultats (payload + réponse API ou ``None`` si dry_run).
    """
    payloads = build_smartview_payloads(result, prefix=prefix, model_id=client.model_id)
    out: list[dict] = []
    for p in payloads:
        if dry_run:
            out.append({"payload": p, "response": None, "dry_run": True})
            continue
        try:
            resp = client.create_smart_view(p)
            out.append({"payload": p, "response": resp, "dry_run": False})
        except Exception as e:  # pragma: no cover - dépend de l'environnement
            out.append({"payload": p, "error": str(e), "dry_run": False})
    return out
