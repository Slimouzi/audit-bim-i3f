"""Builder de BCF Topics 2.1 — workflow d'issues d'audit BIM.

Pour chaque thème d'anomalie ayant des UUIDs en erreur, produit un *BCF
FullTopic* avec :

- ``title`` : « I3F Audit — <thème> »
- ``description`` : synthèse + référence CCH + échantillon des anomalies
- ``topic_type`` : « Audit BIM » ; ``topic_status`` : « Open »
- ``priority`` : déduite de la sévérité maximale du thème
- ``labels`` : ``["I3F", "audit", <phase>, <thème_slug>]``
- ``viewpoints[0].components`` :
    - ``selection`` : tous les UUIDs concernés
    - ``coloring`` : même liste colorée selon la couleur du thème

Apparaît dans le panneau **BCF Issues** du viewer (au lieu des Smart
Views). Format buildingSMART standard ; portable hors BIMData.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from ..audit.engine import AuditResult
from ..audit.findings import Finding, Severity, Theme
from ..extraction.client import BIMDataClient
from ..reporting.theming import THEME_COLORS

ORIGINATING_SYSTEM = "audit-bim-i3f"

_BCF_PRIORITY = {
    Severity.CRITICAL: "Critical",
    Severity.HIGH: "High",
    Severity.MEDIUM: "Medium",
    Severity.LOW: "Low",
    Severity.INFO: "Information",
}


def _slug(text: str) -> str:
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "theme"


def _hex_alpha(hex6: str, alpha: int = 0x80) -> str:
    """Convertit ``RRGGBB`` → ``AARRGGBB`` (BCF accepte les deux)."""
    h = hex6.lstrip("#")
    if len(h) == 6:
        return f"{alpha:02X}{h.upper()}"
    if len(h) == 8:
        return h.upper()
    return f"{alpha:02X}888888"


def _max_severity(findings: Iterable[Finding]) -> Severity:
    order = {s: i for i, s in enumerate(Severity.ordered())}
    return min((f.severity for f in findings), key=lambda s: order[s])


def _theme_description(theme: Theme, items: list[Finding]) -> str:
    n = len(items)
    examples = []
    for f in items[:5]:
        nm = f.name or f.element_uuid or "?"
        examples.append(f"• {f.ifc_type or '?'} — {nm[:80]}")
    sample = "\n".join(examples)
    ref = items[0].ref_cch if items and items[0].ref_cch else "—"
    return (
        f"Audit BIM I3F — thème « {theme.value} ».\n"
        f"{n} anomalie(s) détectée(s). Référence CCH : {ref}.\n\n"
        f"Échantillon :\n{sample}"
    )


def _build_bcf_topic(
    theme: Theme,
    items: list[Finding],
    *,
    phase: str,
    model_id: Optional[int | str],
    prefix: str,
) -> dict:
    uuids: list[str] = []
    seen: set[str] = set()
    for f in items:
        if not f.element_uuid or f.element_uuid in seen:
            continue
        seen.add(f.element_uuid)
        uuids.append(f.element_uuid)

    color_hex = THEME_COLORS.get(theme.value, "888888")
    color_bcf = _hex_alpha(color_hex, alpha=0x80)

    max_sev = _max_severity(items)
    priority = _BCF_PRIORITY.get(max_sev, "Medium")

    components_list = [
        {"ifc_guid": u, "originating_system": ORIGINATING_SYSTEM} for u in uuids
    ]

    # Note : on omet ``viewpoint.guid`` (DRF rejette les ``None``) et
    # ``components.visibility`` (qui exige ``view_setup_hints`` si présent).
    viewpoint = {
        "originating_system": ORIGINATING_SYSTEM,
        "components": {
            "selection": components_list,
            "coloring": [{"color": color_bcf, "components": components_list}],
        },
    }
    if model_id is not None:
        try:
            viewpoint["models"] = [int(model_id)]
        except (TypeError, ValueError):
            pass

    payload = {
        "title": f"{prefix}{theme.value}",
        "description": _theme_description(theme, items),
        "topic_type": "Audit BIM",
        "topic_status": "Open",
        "priority": priority,
        "labels": ["I3F", "audit", phase, _slug(theme.value)],
        "viewpoints": [viewpoint],
        # format omis → 'standard' par défaut côté BIMData = BCF Issues.
    }
    if model_id is not None:
        try:
            payload["models"] = [int(model_id)]
        except (TypeError, ValueError):
            pass
    return payload


def _build_overview_bcf_topic(
    by_theme: dict[Theme, list[Finding]],
    *,
    phase: str,
    model_id: Optional[int | str],
    prefix: str,
) -> dict:
    """Topic « Vue d'ensemble » : viewpoint multi-coloring par thème."""
    all_uuids: list[str] = []
    seen: set[str] = set()
    coloring_groups: list[dict] = []
    total_findings = 0

    sorted_themes = sorted(by_theme.items(), key=lambda kv: -len(kv[1]))
    max_sev = Severity.INFO
    sev_order = {s: i for i, s in enumerate(Severity.ordered())}

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
            if sev_order[f.severity] < sev_order[max_sev]:
                max_sev = f.severity
        if not theme_uuids:
            continue
        color_bcf = _hex_alpha(THEME_COLORS.get(theme.value, "888888"), alpha=0x99)
        coloring_groups.append({
            "color": color_bcf,
            "components": [
                {"ifc_guid": u, "originating_system": ORIGINATING_SYSTEM}
                for u in theme_uuids
            ],
        })
        total_findings += len(items)

    selection = [
        {"ifc_guid": u, "originating_system": ORIGINATING_SYSTEM} for u in all_uuids
    ]

    legend_lines = [
        f"• {theme.value} : {len(items)} anomalie(s)"
        for theme, items in sorted_themes
        if items
    ]
    description = (
        f"Audit BIM I3F — Vue d'ensemble (phase {phase}).\n"
        f"{len(all_uuids)} éléments distincts en erreur, {total_findings} "
        f"anomalies au total, réparties sur "
        f"{sum(1 for _, i in sorted_themes if i)} thèmes "
        "(légende couleur ci-dessous).\n\n"
        "Légende :\n" + "\n".join(legend_lines)
    )

    viewpoint = {
        "originating_system": ORIGINATING_SYSTEM,
        "components": {"selection": selection, "coloring": coloring_groups},
    }
    if model_id is not None:
        try:
            viewpoint["models"] = [int(model_id)]
        except (TypeError, ValueError):
            pass

    payload = {
        "title": f"{prefix}Vue d'ensemble",
        "description": description,
        "topic_type": "Audit BIM",
        "topic_status": "Open",
        "priority": _BCF_PRIORITY.get(max_sev, "Medium"),
        "labels": ["I3F", "audit", phase, "vue-ensemble"],
        "viewpoints": [viewpoint],
    }
    if model_id is not None:
        try:
            payload["models"] = [int(model_id)]
        except (TypeError, ValueError):
            pass
    return payload


def build_bcf_payloads(
    result: AuditResult,
    *,
    prefix: str = "I3F Audit — ",
    model_id: Optional[int | str] = None,
    include_overview: bool = True,
) -> list[dict]:
    """Produit la liste des payloads BCF Topics (format ``standard``).

    Args:
        result: résultat d'audit.
        prefix: préfixe des titres.
        model_id: id du modèle à attacher.
        include_overview: True pour ajouter un topic « Vue d'ensemble » en
            tête (cartographie multi-thèmes).
    """
    by_theme: dict[Theme, list[Finding]] = defaultdict(list)
    for f in result.findings:
        if not f.element_uuid:
            continue
        by_theme[f.theme].append(f)

    payloads: list[dict] = []
    if include_overview and by_theme:
        payloads.append(
            _build_overview_bcf_topic(
                by_theme,
                phase=result.phase.value,
                model_id=model_id,
                prefix=prefix,
            )
        )
    for theme, items in by_theme.items():
        if not items:
            continue
        payloads.append(
            _build_bcf_topic(
                theme,
                items,
                phase=result.phase.value,
                model_id=model_id,
                prefix=prefix,
            )
        )
    return payloads


def push_bcf_topics(
    result: AuditResult,
    client: BIMDataClient,
    *,
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
) -> list[dict]:
    """Crée (ou simule) les BCF Topics sur le projet BIMData.

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
