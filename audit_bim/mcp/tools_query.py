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

from ..classifier.suggestion_store import ClassificationSuggestionStore
from ..domain.filters import FindingFilter, ObjectFilter, SuggestionFilter
from ..query.filtering import (
    apply_finding_filter,
    apply_object_filter,
    apply_suggestion_filter,
)
from ..query.table_query import BimQuery, query_bim_table
from ..query.views import bim_object_from_element, iter_bim_objects
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


@mcp.tool()
def filter_bim_objects(
    filter: dict | None = None,
    output_path: str | None = None,
) -> dict:
    """Filtre les objets BIM (composants) du snapshot actif.

    Utilise la couche domain ``BimObject`` : indépendant de la
    représentation BIMData brute, partagé avec BCF / Smart Views /
    plans de correction.

    Args:
        filter: Dict mappé sur :class:`audit_bim.domain.ObjectFilter`.
            Tous les champs sont optionnels. Combinaison ``ET`` entre
            champs, ``OU`` entre valeurs d'une liste. Voir docstring du
            modèle pour les axes supportés (classification actuelle,
            niveau 3, étage, zone, présence/absence de propriété, etc.).
        output_path: Si fourni (chemin sous ``AUDIT_OUTPUT_DIR``), écrit
            la totalité du résultat en JSON sur disque ; le retour MCP
            ne garde qu'un aperçu. Sinon, fallback automatique disque
            quand la réponse dépasse 256 KB.

    Returns:
        ``{items, total, next_offset, items_path?, items_truncated?}``.
        Les ``items`` sont la version :meth:`BimObject.compact_dict`.
    """
    _State.ensure_snapshot()
    f = ObjectFilter.model_validate(filter or {})

    matched, total, next_offset = apply_object_filter(iter_bim_objects(_State.snapshot), f)
    payload = {
        "items": [obj.compact_dict() for obj in matched],
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
