"""Tools MCP de filtrage / consultation (lecture seule).

Tools enregistrés ici :

- ``filter_bim_objects`` — filtre les composants du snapshot via
  :class:`audit_bim.domain.ObjectFilter`.
- ``list_audit_findings`` — filtre les findings de l'audit en cours
  via :class:`audit_bim.domain.FindingFilter`.
- ``get_object_detail`` — détail d'un élément par UUID (BimObject +
  findings + suggestion).
- ``list_classification_suggestions`` — filtre les entrées du store de
  suggestions via :class:`audit_bim.domain.SuggestionFilter`.
- ``query_bim_data`` — requête tabulaire sémantique sur le snapshot,
  avec projection de N champs métier (matériaux, performance acoustique,
  dimensions, fabricant…).
- ``query_bim_preset`` — variantes pré-configurées pour les cas d'usage
  fréquents (portes acoustique, murs feu/acoustique, équipements
  maintenance).

Aucune écriture, aucun appel API. Le pattern overflow-to-disk
(:func:`payloads.maybe_dump_to_disk`) est appliqué systématiquement.
"""

from __future__ import annotations

from datetime import datetime

from ..audit.findings import ErrorType, Severity, Theme
from ..classifier.suggestion_store import ClassificationSuggestionStore
from ..domain.filters import FindingFilter, ObjectFilter, SuggestionFilter
from ..query.filtering import (
    apply_finding_filter,
    apply_object_filter,
    apply_suggestion_filter,
    object_matches,
)
from ..query.table_query import BimQuery, query_bim_table
from ..query.views import _SPATIAL_CLASSES, bim_object_from_element, iter_bim_objects
from .payloads import ensure_suggestion_store, maybe_dump_to_disk
from .server import mcp
from .session import _State

# ── Presets métier pour query_bim_preset ────────────────────────────────
#
# Volontairement placés en module-level pour être listables / testables
# indépendamment du tool.

QUERY_PRESETS: dict[str, dict] = {
    "doors_acoustic_dimensions": {
        "description": (
            "Portes — matériaux, performance acoustique, dimensions, "
            "résistance au feu, localisation."
        ),
        "filter": {"ifc_types": ["IfcDoor", "IfcDoorStandardCase"]},
        "fields": [
            "uuid",
            "name",
            "object_type",
            "materials",
            "acoustic_performance",
            "height",
            "width",
            "thickness",
            "fire_rating",
            "storey",
            "space",
        ],
    },
    "walls_fire_acoustic": {
        "description": (
            "Murs — matériaux, résistance au feu, performance acoustique, "
            "épaisseur, IsExternal, LoadBearing."
        ),
        "filter": {
            "ifc_types": [
                "IfcWall",
                "IfcWallStandardCase",
                "IfcWallElementedCase",
                "IfcCurtainWall",
            ]
        },
        "fields": [
            "uuid",
            "name",
            "materials",
            "fire_rating",
            "acoustic_performance",
            "thickness",
            "is_external",
            "load_bearing",
            "storey",
        ],
    },
    "equipment_maintenance": {
        "description": (
            "Équipements techniques — fabricant, référence, ID maintenance, "
            "numéro de série, tag, localisation."
        ),
        "filter": {
            # ``ObjectFilter`` matche les types IFC en exact. On liste donc
            # explicitement les classes "parent" abstraites ET les classes
            # concrètes les plus fréquentes en CVC / Plomberie / Électricité.
            # (Limitation connue : un IfcXxxStandardCase non listé sera
            # raté ; à terme, ajouter ``include_ifc_subclasses=True`` à
            # ``ObjectFilter`` pour résoudre via une table IFC4 supertypes.)
            "ifc_types": [
                # Classes parent abstraites
                "IfcDistributionElement",
                "IfcDistributionFlowElement",
                "IfcDistributionControlElement",
                "IfcEnergyConversionDevice",
                "IfcFlowTerminal",
                "IfcFlowController",
                "IfcFlowSegment",
                "IfcFlowFitting",
                "IfcFlowStorageDevice",
                "IfcFlowMovingDevice",
                "IfcFlowTreatmentDevice",
                # CVC — Énergie / chaud / froid
                "IfcBoiler",
                "IfcChiller",
                "IfcCoil",
                "IfcCoolingTower",
                "IfcHeatExchanger",
                "IfcSpaceHeater",
                "IfcUnitaryEquipment",
                "IfcEvaporator",
                "IfcCondenser",
                # CVC — Air
                "IfcAirTerminal",
                "IfcAirTerminalBox",
                "IfcDuctFitting",
                "IfcDuctSegment",
                "IfcDuctSilencer",
                "IfcDamper",
                "IfcFan",
                "IfcFilter",
                # Plomberie / fluide
                "IfcPump",
                "IfcValve",
                "IfcPipeFitting",
                "IfcPipeSegment",
                "IfcSanitaryTerminal",
                "IfcWasteTerminal",
                "IfcStackTerminal",
                "IfcTank",
                # Électricité / éclairage / signal
                "IfcElectricAppliance",
                "IfcElectricDistributionBoard",
                "IfcElectricFlowStorageDevice",
                "IfcElectricGenerator",
                "IfcElectricMotor",
                "IfcLightFixture",
                "IfcLamp",
                "IfcOutlet",
                "IfcSwitchingDevice",
                "IfcCableSegment",
                "IfcCableFitting",
                "IfcCableCarrierSegment",
                "IfcCableCarrierFitting",
                "IfcJunctionBox",
                "IfcProtectiveDevice",
                # Sécurité / détection
                "IfcAlarm",
                "IfcSensor",
                "IfcController",
                "IfcActuator",
                "IfcFireSuppressionTerminal",
                # Transport
                "IfcTransportElement",
            ]
        },
        "fields": [
            "uuid",
            "name",
            "ifc_type",
            "manufacturer",
            "reference",
            "maintenance_id",
            "serial_number",
            "tag",
            "space",
            "zone",
        ],
    },
}


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

    Chaque critère liste = ``OU`` entre valeurs ; critères combinés en
    ``ET`` sur un même finding (un finding a un seul thème / type / sévérité).
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


@mcp.tool()
def filter_bim_objects(
    filter: dict | None = None,
    with_finding_themes: list[str] | None = None,
    with_finding_error_types: list[str] | None = None,
    with_finding_severities: list[str] | None = None,
    include_spatial: bool = False,
    output_path: str | None = None,
) -> dict:
    """Sélectionne les objets BIM (composants) du snapshot actif par filtres.

    Utilise la couche domain ``BimObject`` : indépendant de la
    représentation BIMData brute, partagé avec BCF / Smart Views /
    plans de correction.

    Deux familles de filtres, combinées en **intersection** :

    1. **Structurels** (``filter`` → :class:`audit_bim.domain.ObjectFilter`) :
       ``ifc_types``, ``storey_names``, classification
       (``has_any_classification``, codes…), propriétés
       (``has_property``/``missing_property`` au format ``Pset.Prop``),
       **quantités** (``has_base_quantities`` true/false,
       ``has_quantity``/``missing_quantity`` par nom de BaseQuantity),
       **nommage** (``name_contains``, ``name_regex``), matériaux/layers.
    2. **Pilotés par l'audit** (intersection avec les findings de
       ``run_audit_tool``) : ne garder que les objets portant ≥1 anomalie
       des thèmes / types d'erreur / sévérités donnés. Nécessite un audit
       préalable (``_State.result``). Valeurs validées contre les enums
       moteur ``Theme`` / ``ErrorType`` / ``Severity`` (valeur inconnue →
       ``ValueError``).

    Exemples :

    - Pièces sans quantités : ``filter={"ifc_types":["IfcSpace"],
      "has_base_quantities": false}``.
    - Quantités manquantes **selon le CCH** :
      ``with_finding_error_types=["spatial_missing_quantity"]``.
    - Nommage non conforme : ``with_finding_themes=["Nommage Pièce",
      "Nommage Zone", "Nommage Site / Bâtiment / Étage"]``.

    Args:
        filter: Dict mappé sur ``ObjectFilter`` (tous champs optionnels,
            ``ET`` entre champs, ``OU`` entre valeurs d'une liste).
        with_finding_themes: Valeurs ``Theme.value`` (intersection audit).
        with_finding_error_types: Valeurs ``ErrorType.value``.
        with_finding_severities: Valeurs ``Severity.value``.
        include_spatial: Inclut les éléments spatiaux (``IfcSpace``,
            ``IfcZone``, étages…), exclus par défaut. **Auto-activé** dès
            qu'un ``ifc_types`` spatial est ciblé OU qu'un filtre audit
            (``with_finding_*``) est utilisé — pour ne pas piéger les cas
            spatiaux (ex. quantités SHAB/SU manquantes sur ``IfcSpace``).
            Forcer à ``True`` pour inclure le spatial dans une sélection
            non ciblée.
        output_path: Si fourni (sous ``AUDIT_OUTPUT_DIR``), écrit la
            totalité du résultat en JSON sur disque ; sinon fallback
            automatique disque quand la réponse dépasse 256 KB.

    Returns:
        ``{items, uuids, total, next_offset, limit, offset, items_path?,
        items_truncated?}``.

        - ``total`` = nombre d'objets **après tous les filtres** (structurel
          ∩ audit) mais **avant pagination** — le cardinal réel de la
          sélection.
        - ``items`` = page courante (``limit``/``offset``), au format
          :meth:`BimObject.compact_dict`.
        - ``uuids`` = jeu de sélection **complet** (tous les objets filtrés,
          pas seulement la page), prêt à réutiliser (Smart View / BCF /
          ``get_object_detail``). Si la réponse dépasse la limite inline,
          ``uuids`` est tronqué à un aperçu et l'on expose ``uuids_count`` +
          ``uuids_truncated`` ; le JSON complet (tous les uuids) est dans le
          fichier ``items_path``.
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

    # Auto-include des éléments spatiaux : les exclure silencieusement
    # piégerait les cas spatiaux (ex. `spatial_missing_quantity` sur des
    # IfcSpace). On l'active dès qu'un ifc_type spatial est ciblé OU qu'un
    # filtre audit est utilisé (l'allow-set garde la correction : aucun
    # élément spatial hors sélection n'est sur-renvoyé).
    spatial_targeted = bool(f.ifc_types) and any(t in _SPATIAL_CLASSES for t in f.ifc_types)
    effective_spatial = include_spatial or spatial_targeted or allow is not None

    objs = list(iter_bim_objects(_State.snapshot, include_spatial=effective_spatial))
    if allow is not None:
        objs = [o for o in objs if o.uuid in allow]

    # Page courante (items/total/next_offset) via la fonction canonique…
    matched, total, next_offset = apply_object_filter(objs, f)
    # …et jeu de sélection complet (pré-pagination) pour ``uuids``.
    selection_uuids = [o.uuid for o in objs if object_matches(o, f)]

    payload = {
        "items": [obj.compact_dict() for obj in matched],
        "uuids": selection_uuids,
        "total": total,
        "next_offset": next_offset,
        "limit": f.limit,
        "offset": f.offset,
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return maybe_dump_to_disk(
        payload, output_path=output_path, default_basename=f"filter_bim_objects_{ts}"
    )


@mcp.tool()
def list_audit_findings(
    filter: dict | None = None,
    output_path: str | None = None,
) -> dict:
    """Filtre les anomalies de l'audit en cours sans recalculer l'audit.

    Args:
        filter: Dict mappé sur :class:`audit_bim.domain.FindingFilter`
            (themes / severities / severity_min / error_types / ifc_types
            / element_uuids / require_element_uuid + pagination).
        output_path: Idem ``filter_bim_objects``.

    Returns:
        ``{items, total, next_offset, items_path?, items_truncated?}``.
        Les ``items`` sont les Findings sérialisés en JSON compact.
    """
    _State.ensure_result()
    f = FindingFilter.model_validate(filter or {})

    matched, total, next_offset = apply_finding_filter(_State.result.findings, f)
    payload = {
        "items": [item.model_dump(mode="json") for item in matched],
        "total": total,
        "next_offset": next_offset,
        "limit": f.limit,
        "offset": f.offset,
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return maybe_dump_to_disk(
        payload, output_path=output_path, default_basename=f"list_audit_findings_{ts}"
    )


@mcp.tool()
def get_object_detail(
    uuid: str,
    include_psets: bool = True,
    include_quantities: bool = True,
) -> dict:
    """Renvoie le détail complet d'un objet BIM par UUID IFC.

    Args:
        uuid: GlobalId IFC de l'élément (clé ``uuid`` du snapshot).
        include_psets: Inclure les propriétés Pset complètes
            (``properties``).
        include_quantities: Inclure les BaseQuantities (``base_quantities``).

    Returns:
        Dict :class:`BimObject` complet (ou compact selon les flags) +
        liste éventuelle de findings concernant cet objet + suggestion
        de classification courante si présente dans le store.
    """
    _State.ensure_snapshot()
    element = _State.snapshot.element_by_uuid.get(uuid)
    if element is None:
        raise ValueError(f"UUID inconnu dans le snapshot actif : {uuid!r}")
    obj = bim_object_from_element(element, _State.snapshot)

    data = obj.model_dump(mode="json")
    if not include_psets:
        data.pop("properties", None)
    if not include_quantities:
        data.pop("base_quantities", None)

    # Enrichissement contextuel : findings + suggestion sur cet UUID.
    related_findings: list[dict] = []
    if _State.result is not None:
        related_findings = [
            f.model_dump(mode="json") for f in _State.result.findings if f.element_uuid == uuid
        ]

    suggestion: dict | None = None
    if _State.suggestion_store is not None:
        entry = _State.suggestion_store.get(uuid)
        if entry is not None:
            suggestion = entry.model_dump(mode="json")

    return {
        "object": data,
        "findings": related_findings,
        "n_findings": len(related_findings),
        "suggestion": suggestion,
    }


@mcp.tool()
def list_classification_suggestions(
    filter: dict | None = None,
    populate: bool = True,
    output_path: str | None = None,
) -> dict:
    """Filtre les suggestions de classification stockées (indexées par UUID).

    Lazy-populate : au premier appel sur une session active avec un audit
    en cours, le store est rempli depuis les findings
    ``classification_missing`` / ``classification_invalid``. Les statuts
    non-``proposed`` (accepted / rejected / applied) sont préservés
    entre appels.

    Args:
        filter: Dict mappé sur :class:`audit_bim.domain.SuggestionFilter`
            (codes proposés, niveau 3, confiance min/max, bandes,
            statuts, mismatches uniquement, missing current uniquement).
        populate: Si True (défaut), peuple le store depuis l'audit en
            cours si vide. Mettre à False pour ne consulter que ce qui
            est déjà présent (utile en revue manuelle).
        output_path: Idem ``filter_bim_objects``.

    Returns:
        ``{items, total, next_offset, store_counts: {by_status, by_band,
        by_proposed_level_3}, items_path?, items_truncated?}``.
    """
    if populate:
        ensure_suggestion_store(populate_if_empty=True)
    store = _State.suggestion_store or ClassificationSuggestionStore()

    f = SuggestionFilter.model_validate(filter or {})
    matched, total, next_offset = apply_suggestion_filter(store, f)

    payload = {
        "items": [e.model_dump(mode="json") for e in matched],
        "total": total,
        "next_offset": next_offset,
        "limit": f.limit,
        "offset": f.offset,
        "store_counts": {
            "by_status": store.counts_by_status(),
            "by_band": store.counts_by_band(),
            "by_proposed_level_3": store.counts_by_proposed_level_3(),
            "total": len(store),
        },
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return maybe_dump_to_disk(
        payload,
        output_path=output_path,
        default_basename=f"list_classification_suggestions_{ts}",
    )


# ── query_bim_data + query_bim_preset ────────────────────────────────────


_DEFAULT_QUERY_FIELDS = ["uuid", "ifc_type", "name"]


def _serialize_query_result(result, *, include_cells: bool = False) -> dict:
    """Sérialise un :class:`BimQueryResult` en payload MCP.

    Par défaut on n'expose pas les ``cells`` (qui doublent les valeurs
    avec leurs métadonnées source/matched_key) pour rester compact.
    L'agent qui veut la traçabilité passe ``include_cells=True``.
    """
    rows: list[dict] = []
    for row in result.rows:
        d = dict(row.values)
        d["__uuid"] = row.uuid
        if include_cells:
            d["__cells"] = row.cells
        rows.append(d)
    return {
        "columns": result.columns,
        "rows": rows,
        "total": result.total,
        "next_offset": result.next_offset,
        "warnings": result.warnings,
    }


@mcp.tool()
def query_bim_data(
    filter: dict | None = None,
    fields: list[str] | None = None,
    include_empty: bool = True,
    flatten_lists: bool = False,
    limit: int = 100,
    offset: int = 0,
    output_path: str | None = None,
    include_cells: bool = False,
) -> dict:
    """Requête tabulaire sémantique sur les objets BIM du snapshot actif.

    Permet à un agent IA de poser des questions type :

        « Liste les portes avec leurs matériaux, performance acoustique
        et dimensions. »

    Le résultat est un tableau ``{columns, rows, total, next_offset,
    warnings}`` où chaque ligne contient les valeurs des champs demandés.

    Args:
        filter: Dict mappé sur :class:`audit_bim.domain.ObjectFilter`.
            Ex: ``{"ifc_types": ["IfcDoor"]}``.
        fields: Liste des champs à projeter. Défaut :
            ``["uuid", "ifc_type", "name"]``. Voir
            :data:`audit_bim.query.table_query.KNOWN_FIELDS` pour la liste
            officielle ; n'importe quel ``Pset.Prop`` ou alias projet est
            accepté en fallback.
        include_empty: Si False, n'inclut une ligne que si au moins un
            champ projeté (hors identité) a une valeur non-``None``.
        flatten_lists: Si True, joint les valeurs liste en chaîne
            ``", "`` (utile pour export CSV / agents simples).
        limit / offset: Pagination (limit ≤ 500).
        output_path: Si fourni OU si payload > 256 KB, dump JSON complet
            sur disque (sandbox ``AUDIT_OUTPUT_DIR``) et retour compact.
        include_cells: Si True, inclut ``__cells`` (métadonnées
            source/matched_key par cellule) dans chaque ligne — utile
            pour debug / traçabilité, alourdit le payload.

    Returns:
        Dict ``{columns, rows, total, next_offset, warnings,
        items_path?, items_truncated?}``.
    """
    _State.ensure_snapshot()

    obj_filter = ObjectFilter.model_validate(filter or {})
    # Override pagination de l'ObjectFilter (gérée côté BimQuery).
    obj_filter = obj_filter.model_copy(update={"limit": 500, "offset": 0})

    query = BimQuery(
        object_filter=obj_filter,
        fields=fields if fields else list(_DEFAULT_QUERY_FIELDS),
        include_empty=include_empty,
        flatten_lists=flatten_lists,
        limit=limit,
        offset=offset,
    )
    result = query_bim_table(_State.snapshot, query)
    payload = _serialize_query_result(result, include_cells=include_cells)
    # On expose ``items`` en miroir de ``rows`` pour cohérence avec les
    # autres tools de filtrage (et avec ``maybe_dump_to_disk`` qui
    # cherche ``items`` pour la troncature).
    payload["items"] = payload["rows"]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    compact = maybe_dump_to_disk(
        payload,
        output_path=output_path,
        default_basename=f"query_bim_data_{ts}",
    )
    # ``maybe_dump_to_disk`` ne tronque que la clé ``items`` ; on doit
    # forcer ``rows`` à matcher pour ne PAS exposer le payload complet
    # via la clé spécifique à ``query_bim_data``. Sinon le retour MCP
    # peut dépasser 1 MB malgré ``items_path`` (bug P1 review).
    if compact.get("items_truncated"):
        compact["rows"] = list(compact.get("items") or [])
        compact["rows_truncated"] = True
    return compact


@mcp.tool()
def query_bim_preset(
    preset: str,
    filter: dict | None = None,
    limit: int = 100,
    offset: int = 0,
    output_path: str | None = None,
    include_empty: bool = True,
    flatten_lists: bool = False,
) -> dict:
    """Variantes pré-configurées de :func:`query_bim_data` pour les cas
    d'usage métier fréquents.

    Args:
        preset: Nom du preset. Valeurs admises (cf. :data:`QUERY_PRESETS`) :
            - ``"doors_acoustic_dimensions"`` — portes : matériaux,
              acoustique, dimensions, feu, localisation.
            - ``"walls_fire_acoustic"`` — murs : matériaux, feu,
              acoustique, épaisseur, externe/porteur.
            - ``"equipment_maintenance"`` — équipements : fabricant,
              référence, ID maintenance, série, tag, localisation.
        filter: Filtre additionnel **fusionné** avec le filtre du
            preset (les listes ``ifc_types`` etc. sont remplacées si
            spécifiées ; les autres champs s'ajoutent).
        limit / offset: Pagination.
        output_path: Idem ``query_bim_data``.
        include_empty / flatten_lists: Idem ``query_bim_data``.

    Returns:
        Idem :func:`query_bim_data` + métadonnée ``preset`` dans le retour.
    """
    if preset not in QUERY_PRESETS:
        raise ValueError(f"preset inconnu {preset!r}. Valeurs admises : {sorted(QUERY_PRESETS)}.")
    cfg = QUERY_PRESETS[preset]

    # Fusion filtre preset + filtre utilisateur (user gagne).
    merged_filter = dict(cfg.get("filter") or {})
    if filter:
        merged_filter.update(filter)

    result = query_bim_data(
        filter=merged_filter,
        fields=list(cfg["fields"]),
        include_empty=include_empty,
        flatten_lists=flatten_lists,
        limit=limit,
        offset=offset,
        output_path=output_path,
    )
    result["preset"] = preset
    result["preset_description"] = cfg.get("description", "")
    return result


@mcp.tool()
def list_query_presets() -> dict:
    """Liste les presets disponibles pour :func:`query_bim_preset`."""
    return {
        "presets": [
            {
                "name": name,
                "description": cfg.get("description", ""),
                "default_filter": cfg.get("filter", {}),
                "fields": list(cfg["fields"]),
            }
            for name, cfg in QUERY_PRESETS.items()
        ],
        "total": len(QUERY_PRESETS),
    }
