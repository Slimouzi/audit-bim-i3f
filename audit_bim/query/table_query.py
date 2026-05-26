"""Moteur de requête tabulaire sur les :class:`BimObject`.

Permet à un agent IA / AMO de formuler une question type :

    « Liste tous les matériaux des portes, leur performance acoustique
    et leurs dimensions. »

→ Filtrage par ``ObjectFilter`` (``ifc_types=["IfcDoor"]``), puis
projection de N champs sémantiques sur chaque résultat. Le moteur
résout chaque champ via :mod:`property_aliases` et retourne un tableau
``{columns, rows, total, next_offset, warnings}``.

Conception
----------

- **Pas d'I/O** : pas d'appel API BIMData, pas d'écriture disque. Le
  caller (tool MCP) décide de l'export via ``maybe_dump_to_disk``.
- **Pagination côté résultat** : tout est filtré d'abord, puis paginé.
  Cohérent avec ``apply_object_filter``.
- **``flatten_lists``** : permet à un agent qui ne sait pas joindre des
  listes de récupérer les valeurs jointes (``"BOSCH, SIEMENS"``).
- **Warnings explicites** : champs inconnus, valeurs manquantes sur
  beaucoup de lignes, etc. — pour aider l'agent à comprendre la
  qualité des données.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.bim_object import BimObject
from ..domain.filters import DEFAULT_LIMIT, MAX_LIMIT, ObjectFilter
from ..extraction.model_data import ModelSnapshot
from ..query.filtering import object_matches
from ..query.views import iter_bim_objects
from .property_aliases import resolve_requested_field

# ── Modèles ──────────────────────────────────────────────────────────────


# Champs reconnus par le moteur (non exhaustif — n'importe quel nom de
# Pset.Prop ou alias additionnel reste accepté en fallback dynamique).
KNOWN_FIELDS: list[str] = [
    # Identité
    "uuid",
    "ifc_type",
    "name",
    "long_name",
    "object_type",
    "predefined_type",
    "description",
    "source",
    # Classifications
    "classification",
    "classification_level_3",
    "classifications",
    # Spatial
    "storey",
    "space",
    "zone",
    # Listes
    "materials",
    "layers",
    # Booléens IFC
    "is_external",
    "load_bearing",
    # Dimensions (BaseQuantities en priorité, Psets en fallback)
    "dimensions",
    "height",
    "width",
    "thickness",
    "area",
    "volume",
    "perimeter",
    "length",
    # Sémantique métier
    "acoustic_performance",
    "fire_rating",
    "manufacturer",
    "reference",
    "tag",
    "maintenance_id",
    "serial_number",
]


_DEFAULT_FIELDS = ["uuid", "ifc_type", "name"]


class BimQuery(BaseModel):
    """Requête tabulaire sur les ``BimObject`` du snapshot.

    Attributes:
        object_filter: Filtre sur les objets (cf. :class:`ObjectFilter`).
            None = tous les composants.
        fields: Liste ordonnée des champs à projeter. Détermine les
            colonnes de sortie. Défaut : ``["uuid", "ifc_type", "name"]``.
        include_empty: Si False, n'inclut une ligne que si **au moins
            un** champ projeté a une valeur non-``None``. Par défaut
            True (on retourne aussi les lignes "vides" pour permettre à
            l'agent de quantifier les trous).
        flatten_lists: Si True, joint les valeurs liste en chaîne
            ``", "``. Utile quand un export CSV ou un agent simple ne
            peut pas digérer du JSON imbriqué.
        limit / offset: Pagination après filtrage.
    """

    model_config = ConfigDict(extra="forbid")

    object_filter: ObjectFilter | None = None
    fields: list[str] = Field(default_factory=lambda: list(_DEFAULT_FIELDS))
    include_empty: bool = True
    flatten_lists: bool = False
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    offset: int = Field(0, ge=0)


class BimQueryRow(BaseModel):
    """Une ligne du résultat. Format ``{value, source, matched_key}`` par
    cellule pour préserver la traçabilité — mais on expose aussi
    ``values`` (mapping plat ``field → value``) pour la consommation
    naïve."""

    model_config = ConfigDict(extra="ignore")

    uuid: str
    cells: dict[str, dict[str, Any]] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)


class BimQueryResult(BaseModel):
    """Réponse de :func:`query_bim_table`."""

    model_config = ConfigDict(extra="ignore")

    columns: list[str]
    rows: list[BimQueryRow]
    total: int
    next_offset: int | None = None
    warnings: list[str] = Field(default_factory=list)


# ── Fonction principale ─────────────────────────────────────────────────


def _flatten_value(value: Any) -> Any:
    """Joint les listes ``["a", "b"]`` en ``"a, b"`` pour CSV-friendly."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v is not None)
    return value


def _project_row(obj: BimObject, fields: list[str], flatten: bool) -> BimQueryRow:
    cells: dict[str, dict[str, Any]] = {}
    values: dict[str, Any] = {}
    for f in fields:
        resolved = resolve_requested_field(obj, f)
        v = resolved["value"]
        if flatten:
            v = _flatten_value(v)
        cells[f] = resolved
        values[f] = v
    return BimQueryRow(uuid=obj.uuid, cells=cells, values=values)


def _row_has_value(row: BimQueryRow, fields_to_check: list[str]) -> bool:
    """``True`` si au moins un champ projeté a une valeur non-``None``.

    On exclut les champs d'identité de cette vérification (``uuid``,
    ``ifc_type``, ``name``) — sinon ``include_empty=False`` ne filtrerait
    quasi rien, vu que ``uuid`` est toujours présent.
    """
    ident = {"uuid", "ifc_type", "name"}
    for f in fields_to_check:
        if f in ident:
            continue
        v = row.values.get(f)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, list) and not v:
            continue
        if isinstance(v, dict) and all(x is None for x in v.values()):
            continue
        return True
    return False


def query_bim_table(snapshot: ModelSnapshot, query: BimQuery) -> BimQueryResult:
    """Exécute une requête tabulaire sur le snapshot.

    Args:
        snapshot: ``ModelSnapshot`` chargé en session.
        query: ``BimQuery`` validé.

    Returns:
        :class:`BimQueryResult` avec colonnes, lignes, total et
        warnings éventuels.
    """
    fields = list(query.fields) if query.fields else list(_DEFAULT_FIELDS)
    warnings: list[str] = []

    # Détecte les champs inconnus (purement informatif — on les essaie
    # quand même en fallback dynamique).
    for f in fields:
        if f.lower() in {k.lower() for k in KNOWN_FIELDS}:
            continue
        if "." in f:
            # ressemble à un nom de Pset (Pset_3F.Lot) — silence.
            continue
        warnings.append(f"field {f!r} non standard — tenté comme alias dynamique de propriété.")

    # Filtrage objets
    f = query.object_filter
    matched_objects: list[BimObject] = []
    for obj in iter_bim_objects(snapshot):
        if f is None or object_matches(obj, f):
            matched_objects.append(obj)

    # Projection (avant pagination, pour compter le total après
    # include_empty si demandé).
    rows = [_project_row(obj, fields, query.flatten_lists) for obj in matched_objects]
    if not query.include_empty:
        rows = [r for r in rows if _row_has_value(r, fields)]

    total = len(rows)

    # Pagination
    end = query.offset + query.limit
    paginated = rows[query.offset : end]
    next_offset = end if end < total else None

    # Warning qualité : > 80 % de None sur un champ sémantique
    if total > 0:
        for f_name in fields:
            if f_name in {"uuid", "ifc_type", "name"}:
                continue
            n_missing = sum(1 for r in rows if r.cells.get(f_name, {}).get("source") == "missing")
            if n_missing >= max(1, int(0.8 * total)):
                warnings.append(
                    f"{n_missing}/{total} lignes n'ont pas de valeur pour {f_name!r} "
                    "— champ probablement non renseigné dans la maquette."
                )

    return BimQueryResult(
        columns=fields,
        rows=paginated,
        total=total,
        next_offset=next_offset,
        warnings=warnings,
    )


__all__ = [
    "KNOWN_FIELDS",
    "BimQuery",
    "BimQueryRow",
    "BimQueryResult",
    "query_bim_table",
]
