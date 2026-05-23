"""Agent Smart Views — vues 3D natives BIMData (panneau « Smart Views »).

Une Smart View est une vue 3D simple sur la maquette : un nom + un coloring
d'éléments. Elle est rangée dans le panneau dédié du viewer BIMData (et non
dans les BCF Issues). C'est l'outil de **navigation** par excellence — pas
de workflow d'issue, pas d'assignation, pas de statut.

Stockage : même endpoint BCF FullTopic, mais avec ``format =
"bimdata-smartview"``. Le payload est volontairement **minimal** (aligné sur
ce que produit l'UI viewer) : ``title`` + ``models`` + ``format`` +
``viewpoints[0].components.coloring``. Tout autre champ (topic_type,
status, priority, description, labels, selection, visibility) fait
disparaître la Smart View du panneau dédié.

Pour des *issues à résoudre* avec workflow (assignation, statut,
commentaires, description), préférer l'agent ``audit_bim.bcf``.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from ..audit.engine import AuditResult
from ..audit.findings import Finding, Severity, Theme
from ..extraction.client import BIMDataClient
from ..reporting.theming import THEME_COLORS


def _build_full_topic(
    theme: Theme,
    items: list[Finding],
    *,
    phase: str,
    model_id: Optional[int | str],
    prefix: str,
    element_by_uuid: dict | None = None,
) -> dict:
    """Construit un payload Smart View aligné sur celui de l'UI BIMData.

    L'UI envoie un payload **minimal** : ``title`` + ``models`` + ``format`` +
    ``viewpoints[0].components.coloring`` uniquement. Tout champ BCF Issue
    (``topic_type``, ``topic_status``, ``priority``, ``description``,
    ``labels``) ou tout ``selection``/``visibility``/``originating_system`` de
    viewpoint fait disparaître la Smart View du panneau dédié dans le viewer.

    Le nom Revit (``originating_system`` côté composant) et l'ID modèle
    (``authoring_tool_id``) sont alignés sur ce que produit Revit/IFC pour
    cohérence avec ce qu'attend l'UI.
    """
    uuids: list[str] = []
    seen: set[str] = set()
    for f in items:
        if not f.element_uuid or f.element_uuid in seen:
            continue
        seen.add(f.element_uuid)
        uuids.append(f.element_uuid)

    color_hex = THEME_COLORS.get(theme.value, "888888")
    color = f"#{color_hex}"

    mid_int: Optional[int] = None
    if model_id is not None:
        try:
            mid_int = int(model_id)
        except (TypeError, ValueError):
            mid_int = None

    def _component(u: str) -> dict:
        comp = {"ifc_guid": u, "originating_system": _element_name(element_by_uuid, u)}
        if mid_int is not None:
            comp["authoring_tool_id"] = mid_int
        return comp

    components_list = [_component(u) for u in uuids]

    viewpoint = {
        "components": {
            "coloring": [{"color": color, "components": components_list}],
        },
    }

    payload = {
        "title": f"{prefix}{theme.value}",
        "viewpoints": [viewpoint],
        "format": "bimdata-smartview",
    }
    if mid_int is not None:
        payload["models"] = [mid_int]
    return payload


def _element_name(element_by_uuid: dict | None, uuid: str) -> str:
    """Retourne le nom Revit/CAO d'un élément depuis le snapshot, ou ``""``."""
    if not element_by_uuid:
        return ""
    el = element_by_uuid.get(uuid) or {}
    return (
        el.get("name")
        or el.get("object_type")
        or el.get("longname")
        or ""
    )


def _build_overview_topic(
    by_theme: dict[Theme, list[Finding]],
    *,
    phase: str,
    model_id: Optional[int | str],
    prefix: str,
    element_by_uuid: dict | None = None,
) -> dict:
    """Topic « Vue d'ensemble » : 1 seul viewpoint avec coloring multi-thèmes.

    Tous les UUIDs en erreur sont sélectionnés. Le coloring contient une
    entrée par thème (chacune sa couleur de la palette THEME_COLORS), ce qui
    permet de voir d'un coup la cartographie des anomalies sur la maquette,
    en ouvrant un seul topic.
    """
    # Union ordonnée des UUIDs + index par thème (couleur)
    all_uuids: list[str] = []
    seen: set[str] = set()
    coloring_groups: list[dict] = []

    # Trie les thèmes par nb décroissant pour stabilité visuelle
    sorted_themes = sorted(
        by_theme.items(), key=lambda kv: -len(kv[1])
    )

    mid_int: Optional[int] = None
    if model_id is not None:
        try:
            mid_int = int(model_id)
        except (TypeError, ValueError):
            mid_int = None

    def _component(u: str) -> dict:
        comp = {"ifc_guid": u, "originating_system": _element_name(element_by_uuid, u)}
        if mid_int is not None:
            comp["authoring_tool_id"] = mid_int
        return comp

    for theme, items in sorted_themes:
        theme_uuids = []
        seen_theme: set[str] = set()
        for f in items:
            if not f.element_uuid or f.element_uuid in seen_theme:
                continue
            seen_theme.add(f.element_uuid)
            theme_uuids.append(f.element_uuid)
            if f.element_uuid not in seen:
                seen.add(f.element_uuid)
                all_uuids.append(f.element_uuid)
        if not theme_uuids:
            continue
        # Couleur RGB simple (sans alpha) — format observé côté UI : '#RRGGBB'
        color = "#" + THEME_COLORS.get(theme.value, "888888")
        coloring_groups.append({
            "color": color,
            "components": [_component(u) for u in theme_uuids],
        })

    # Payload minimal aligné UI : pas de selection, pas de description,
    # pas de labels, pas de viewpoint.originating_system.
    viewpoint = {"components": {"coloring": coloring_groups}}

    payload = {
        "title": f"{prefix}Vue d'ensemble",
        "viewpoints": [viewpoint],
        "format": "bimdata-smartview",
    }
    if model_id is not None:
        try:
            payload["models"] = [int(model_id)]
        except (TypeError, ValueError):
            pass
    return payload


def build_smartview_payloads(
    result: AuditResult,
    *,
    prefix: str = "I3F Audit — ",
    model_id: Optional[int | str] = None,
    include_overview: bool = True,
) -> list[dict]:
    """Produit les payloads BCF FullTopic.

    Args:
        result: résultat d'audit.
        prefix: préfixe des titres ("I3F Audit — ").
        model_id: id du modèle à attacher dans chaque viewpoint.
        include_overview: si ``True`` (défaut), ajoute en tête un topic
            « Vue d'ensemble » qui sélectionne tous les UUIDs en erreur,
            colorés par thème — pratique pour avoir la cartographie complète
            d'un coup, avant de creuser dans chaque topic thématique.

    Returns:
        Liste de payloads : [overview, theme1, theme2, ...].
    """
    by_theme: dict[Theme, list[Finding]] = defaultdict(list)
    for f in result.findings:
        if not f.element_uuid:
            continue
        by_theme[f.theme].append(f)

    # Snapshot disponible pour récupérer le nom Revit de chaque UUID, à
    # passer dans 'originating_system' du composant du coloring (aligné UI).
    element_by_uuid = getattr(result.snapshot, "element_by_uuid", None) or {}

    payloads: list[dict] = []
    if include_overview and by_theme:
        payloads.append(
            _build_overview_topic(
                by_theme,
                phase=result.phase.value,
                model_id=model_id,
                prefix=prefix,
                element_by_uuid=element_by_uuid,
            )
        )

    for theme, items in by_theme.items():
        if not items:
            continue
        payloads.append(
            _build_full_topic(
                theme,
                items,
                phase=result.phase.value,
                model_id=model_id,
                prefix=prefix,
                element_by_uuid=element_by_uuid,
            )
        )
    return payloads


def push_smart_views(
    result: AuditResult,
    client: BIMDataClient,
    *,
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
) -> list[dict]:
    """Crée (ou simule) les BCF Topics d'audit.

    Args:
        result: résultat d'audit.
        client: client BIMData authentifié.
        prefix: préfixe du titre des topics.
        dry_run: si ``True``, ne fait *pas* le POST et renvoie les payloads.

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
