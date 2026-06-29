"""Résolution de sélection d'objets BIM partagée par les tools MCP.

Centralise la logique commune à ``filter_bim_objects``,
``show_filtered_objects_in_viewer`` et ``prepare_smart_view_from_filter_plan`` :
parse du :class:`ObjectFilter`, intersection optionnelle avec les findings de
l'audit (``with_finding_*``), auto-inclusion du spatial, et calcul du jeu de
sélection complet (pré-pagination) + de la page courante.

Aucune écriture, aucun appel API : tout se fait sur le snapshot/résultat de la
session active (:data:`_State`).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..audit.findings import ErrorType, Severity, Theme
from ..domain.bim_object import BimObject
from ..domain.filters import ObjectFilter
from ..query.filtering import apply_object_filter, object_matches
from ..query.views import _SPATIAL_CLASSES, iter_bim_objects
from .session import _State


@dataclass
class ObjectSelection:
    """Résultat d'une résolution de sélection d'objets BIM.

    Attributes:
        objects: Jeu de sélection **complet** (tous les objets filtrés,
            pré-pagination) — base des ``uuids`` et des actions viewer/Smart View.
        page: Page courante (``limit``/``offset`` de ``filter``) — ce que
            ``filter_bim_objects`` expose dans ``items``.
        uuids: UUID du jeu complet, prêts à réutiliser (viewer / Smart View / BCF).
        total: Cardinal du jeu complet (post-filtres, pré-pagination).
        next_offset: Offset de la page suivante, ou ``None`` si dernière page.
        filter: :class:`ObjectFilter` effectivement appliqué (avec ses
            ``limit``/``offset``).
    """

    objects: list[BimObject]
    page: list[BimObject]
    uuids: list[str]
    total: int
    next_offset: int | None
    filter: ObjectFilter


def _validate_finding_enum(values: list[str] | None, enum_cls, label: str) -> None:
    """Refuse toute valeur hors de l'enum moteur (Theme/ErrorType/Severity)."""
    if not values:
        return
    valid = {m.value for m in enum_cls}
    bad = [v for v in values if v not in valid]
    if bad:
        raise ValueError(f"{label} invalide(s) : {bad}. Valeurs admises : {sorted(valid)}.")


def _finding_allowset(
    result,
    *,
    themes: list[str] | None,
    error_types: list[str] | None,
    severities: list[str] | None,
) -> set[str]:
    """UUID des éléments portant ≥1 finding satisfaisant TOUS les critères.

    Chaque critère liste = ``OU`` entre valeurs ; critères combinés en ``ET``
    sur un même finding (un finding a un seul thème / type / sévérité).
    """
    allow: set[str] = set()
    for fnd in result.findings:
        if not fnd.element_uuid:
            continue
        if themes is not None and fnd.theme.value not in themes:
            continue
        if error_types is not None and fnd.error_type.value not in error_types:
            continue
        if severities is not None and fnd.severity.value not in severities:
            continue
        allow.add(fnd.element_uuid)
    return allow


def resolve_object_selection(
    filter: dict | None = None,
    *,
    with_finding_themes: list[str] | None = None,
    with_finding_error_types: list[str] | None = None,
    with_finding_severities: list[str] | None = None,
    include_spatial: bool = False,
) -> ObjectSelection:
    """Résout la sélection d'objets BIM du snapshot actif.

    Deux familles de filtres en **intersection** : structurels (``filter`` →
    :class:`ObjectFilter`) et pilotés par l'audit (``with_finding_*`` →
    intersection avec les findings de ``_State.result``, validés contre les
    enums moteur). Auto-inclusion des éléments spatiaux dès qu'un ``ifc_types``
    spatial est ciblé OU qu'un filtre audit est utilisé.

    Voir :func:`audit_bim.mcp.tools_query.filter_bim_objects` pour le détail
    sémantique des champs.

    Raises:
        RuntimeError: si aucun snapshot actif (ou aucun résultat d'audit quand
            ``with_finding_*`` est fourni).
        ValueError: si une valeur ``with_finding_*`` est hors enum moteur.
    """
    _State.ensure_snapshot()
    f = ObjectFilter.model_validate(filter or {})

    allow: set[str] | None = None
    if with_finding_themes or with_finding_error_types or with_finding_severities:
        _validate_finding_enum(with_finding_themes, Theme, "with_finding_themes")
        _validate_finding_enum(with_finding_error_types, ErrorType, "with_finding_error_types")
        _validate_finding_enum(with_finding_severities, Severity, "with_finding_severities")
        _State.ensure_result()
        allow = _finding_allowset(
            _State.result,
            themes=with_finding_themes,
            error_types=with_finding_error_types,
            severities=with_finding_severities,
        )

    spatial_targeted = bool(f.ifc_types) and any(t in _SPATIAL_CLASSES for t in f.ifc_types)
    effective_spatial = include_spatial or spatial_targeted or allow is not None

    objs = list(iter_bim_objects(_State.snapshot, include_spatial=effective_spatial))
    if allow is not None:
        objs = [o for o in objs if o.uuid in allow]

    # Page courante (items/total/next_offset) via la fonction canonique…
    page, total, next_offset = apply_object_filter(objs, f)
    # …et jeu de sélection complet (pré-pagination), même prédicat.
    full = [o for o in objs if object_matches(o, f)]

    return ObjectSelection(
        objects=full,
        page=page,
        uuids=[o.uuid for o in full],
        total=total,
        next_offset=next_offset,
        filter=f,
    )
