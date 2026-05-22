"""Builder des « Smart Views » d'audit BIM I3F → matérialisées en BCF 2.1.

Côté API BIMData, l'équivalent natif d'une *Smart View* utilisée pour
isoler/colorer des éléments est le couple **BCF Topic + Viewpoint** sur
``/bcf/2.1/projects/{project_id}/full-topic``. C'est aussi le standard
buildingSMART, donc *portable* hors BIMData (lisible par tous les viewers IFC
compatibles BCF 2.1).

Pour chaque thème d'audit ayant des UUIDs en erreur, le builder produit un
*FullTopic* :

- ``title`` : « I3F Audit — <thème> »
- ``description`` : synthèse + référence au CCH
- ``topic_type`` : « Audit BIM » ; ``topic_status`` : « Open »
- ``priority`` : déduite de la sévérité maximale du thème
- ``labels`` : ``["I3F", "audit", "<phase>", "<thème_slug>"]``
- ``viewpoints[0].components`` :
    - ``selection`` : tous les UUIDs concernés
    - ``coloring`` : même liste colorée selon la sévérité maximale du thème
    - ``visibility.default_visibility`` : ``true`` (on garde tout visible)

Mode ``dry_run=True`` par défaut : on renvoie les payloads sans push, ce qui
permet à l'utilisateur de relire la couleur / le libellé avant publication.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from ..audit.engine import AuditResult
from ..audit.findings import Finding, Severity, Theme
from ..extraction.client import BIMDataClient
from ..reporting.theming import SEVERITY_COLORS, THEME_COLORS

ORIGINATING_SYSTEM = "audit-bim-i3f"

# Mapping sévérité BCF — BCF accepte des chaînes libres pour priority
_BCF_PRIORITY = {
    Severity.CRITICAL: "Critical",
    Severity.HIGH: "High",
    Severity.MEDIUM: "Medium",
    Severity.LOW: "Low",
    Severity.INFO: "Information",
}


def _slug(text: str) -> str:
    """Slug compact pour label BCF (sans accents ni espaces multiples)."""
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "theme"


def _hex_alpha(hex6: str, alpha: int = 0x80) -> str:
    """Convertit '#RRGGBB' ou 'RRGGBB' → 'AARRGGBB' (alpha 50 % par défaut).

    BCF 2.1 accepte les deux formats ; on choisit AARRGGBB pour une
    transparence agréable dans le viewer.
    """
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
    for f in items[:3]:
        nm = f.name or f.element_uuid or "?"
        examples.append(f"• {f.ifc_type or '?'} — {nm[:60]}")
    sample = "\n".join(examples)
    ref = items[0].ref_cch if items and items[0].ref_cch else "—"
    return (
        f"Audit BIM I3F — thème « {theme.value} ».\n"
        f"{n} anomalie(s) détectée(s). Référence CCH : {ref}.\n\n"
        f"Échantillon :\n{sample}"
    )


def _build_full_topic(
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

    # Note : ne **pas** mettre 'guid': None — DRF valide ce champ comme
    # 'may not be null' ; on l'omet pour que le serveur en génère un.
    viewpoint = {
        "originating_system": ORIGINATING_SYSTEM,
        "components": {
            "selection": components_list,
            "coloring": [
                {"color": color_bcf, "components": components_list}
            ],
            # Note : on omet 'visibility' — si inclus, BCF/BIMData requiert
            # 'view_setup_hints' qui est rarement utile pour une simple sélection.
            # La valeur par défaut serveur (tout visible) convient.
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
    }
    if model_id is not None:
        try:
            payload["models"] = [int(model_id)]
        except (TypeError, ValueError):
            pass
    return payload


def _build_overview_topic(
    by_theme: dict[Theme, list[Finding]],
    *,
    phase: str,
    model_id: Optional[int | str],
    prefix: str,
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
    total_findings = 0

    # Trie les thèmes par nb décroissant pour stabilité visuelle
    sorted_themes = sorted(
        by_theme.items(), key=lambda kv: -len(kv[1])
    )

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
        f"anomalies au total, réparties sur {sum(1 for _, i in sorted_themes if i)} "
        "thèmes (légende couleur ci-dessous).\n\n"
        "Légende :\n" + "\n".join(legend_lines) +
        "\n\nVoir aussi les topics thématiques pour le détail par catégorie."
    )

    viewpoint = {
        "originating_system": ORIGINATING_SYSTEM,
        "components": {
            "selection": selection,
            "coloring": coloring_groups,
        },
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

    payloads: list[dict] = []
    if include_overview and by_theme:
        payloads.append(
            _build_overview_topic(
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
            _build_full_topic(
                theme,
                items,
                phase=result.phase.value,
                model_id=model_id,
                prefix=prefix,
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
