"""Adaptateurs ``ModelSnapshot`` → :class:`BimObject` (lecture seule).

Conception
----------

- Les :class:`BimObject` sont générés **lazy** depuis le snapshot ;
  on ne matérialise pas une liste de 1500 objets en mémoire à
  chaque appel — :func:`iter_bim_objects` retourne un générateur.
- La résolution spatiale (storey/space/zone) passe par
  ``structure_tree`` : un index UUID-élément → UUID-étage est construit
  une fois et caché sur le snapshot (attribut dynamique).
- Les classifications existantes sont lues depuis la clé
  ``classifications`` ou ``classification`` de l'élément si présente.
  Le snapshot peut ne pas les contenir (l'extraction actuelle ne les
  fetch pas toujours) — ``classifications=[]`` est alors le défaut.

Aucune modification du :class:`ModelSnapshot` original n'est faite.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from ..domain.bim_object import BimObject, ClassificationRef
from ..extraction.model_data import ModelSnapshot

# Cache des index spatiaux par snapshot (id() → mapping)
_SPATIAL_INDEX_ATTR = "_audit_bim_spatial_index"

# Classes spatiales hors filtrage objets (les BimObjects sont les
# *components* — pas les Site/Building/Storey/Space/Zone eux-mêmes).
_SPATIAL_CLASSES = {
    "IfcSite",
    "IfcBuilding",
    "IfcBuildingStorey",
    "IfcSpace",
    "IfcZone",
}


def _build_spatial_index(snapshot: ModelSnapshot) -> dict[str, dict[str, str | None]]:
    """Construit l'index UUID → {storey_uuid, storey_name, space_uuid,
    space_name, zone_uuid, zone_name} depuis ``structure_tree``.

    L'arbre BIMData a la forme :
    ``[{uuid, type, name, children: [...]}]`` — récursif.
    """
    out: dict[str, dict[str, str | None]] = {}

    def visit(
        node: dict,
        storey_uuid: str | None,
        storey_name: str | None,
        space_uuid: str | None,
        space_name: str | None,
        zone_uuid: str | None,
        zone_name: str | None,
    ) -> None:
        ntype = node.get("type")
        nuuid = node.get("uuid")
        nname = node.get("name") or node.get("long_name")

        # Mise à jour du contexte spatial selon le type du noeud courant.
        if ntype == "IfcBuildingStorey":
            storey_uuid, storey_name = nuuid, nname
        elif ntype == "IfcSpace":
            space_uuid, space_name = nuuid, nname
        elif ntype == "IfcZone":
            zone_uuid, zone_name = nuuid, nname

        if nuuid and ntype not in _SPATIAL_CLASSES:
            # On indexe les composants (pas les containers eux-mêmes).
            out[nuuid] = {
                "storey_uuid": storey_uuid,
                "storey_name": storey_name,
                "space_uuid": space_uuid,
                "space_name": space_name,
                "zone_uuid": zone_uuid,
                "zone_name": zone_name,
            }

        for child in node.get("children") or []:
            visit(
                child,
                storey_uuid,
                storey_name,
                space_uuid,
                space_name,
                zone_uuid,
                zone_name,
            )

    for root in snapshot.structure_tree or []:
        visit(root, None, None, None, None, None, None)
    return out


def _spatial_for(snapshot: ModelSnapshot, uuid: str) -> dict[str, str | None]:
    cache = getattr(snapshot, _SPATIAL_INDEX_ATTR, None)
    if cache is None:
        cache = _build_spatial_index(snapshot)
        # Attribut dynamique sur le dataclass (mutation autorisée car
        # ModelSnapshot n'est pas frozen).
        try:
            setattr(snapshot, _SPATIAL_INDEX_ATTR, cache)
        except (AttributeError, TypeError):
            # Si le snapshot est immuable d'une façon ou d'une autre,
            # on calcule sans cache (coûteux mais correct).
            pass
    return cache.get(uuid, {})


def _extract_properties(element: dict) -> dict[str, Any]:
    """Aplatit les Psets en dict ``{"PsetName.PropName": value}``.

    Skip les Pset techniques 'BaseQuantities' / 'Qto_*' (extraits
    séparément dans ``_extract_base_quantities``).
    """
    out: dict[str, Any] = {}
    for pset in element.get("property_sets") or []:
        pname = pset.get("name") or ""
        if not pname:
            continue
        lname = pname.lower()
        if lname.startswith("basequantities") or lname.startswith("qto_"):
            continue
        for prop in pset.get("properties") or []:
            defn = prop.get("definition") or {}
            pn = defn.get("name")
            if not pn:
                continue
            out[f"{pname}.{pn}"] = prop.get("value")
    return out


def _extract_base_quantities(element: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for pset in element.get("property_sets") or []:
        pname = (pset.get("name") or "").lower()
        if not (pname.startswith("basequantities") or pname.startswith("qto_")):
            continue
        for prop in pset.get("properties") or []:
            defn = prop.get("definition") or {}
            pn = defn.get("name")
            val = prop.get("value")
            if pn and isinstance(val, (int, float)):
                out[pn] = float(val)
    return out


def _extract_classifications(element: dict) -> list[ClassificationRef]:
    """Lit les classifications associées à un élément (si présentes).

    BIMData peut exposer les classifications sous différentes clés selon
    la version d'API. On gère :

    - ``element["classifications"]``: liste de dicts ``{name, identifier,
      reference_id, source}``
    - ``element["classification"]``: variante singulier
    """
    raws: Iterable[dict] = element.get("classifications") or element.get("classification") or []
    if isinstance(raws, dict):
        raws = [raws]
    out: list[ClassificationRef] = []
    for raw in raws:
        if not isinstance(raw, dict):
            continue
        code = raw.get("identifier") or raw.get("code") or raw.get("notation")
        if not code:
            continue
        label = raw.get("name") or raw.get("label") or raw.get("title")
        system = raw.get("source") or raw.get("system")
        out.append(ClassificationRef(code=str(code), label=label, system=system))
    return out


def _extract_pset_bool(element: dict, prop_name: str) -> bool | None:
    """Cherche une propriété booléenne dans tous les Psets ``*Common``."""
    target = prop_name.lower()
    for pset in element.get("property_sets") or []:
        pname = (pset.get("name") or "").lower()
        if not pname.endswith("common"):
            continue
        for prop in pset.get("properties") or []:
            defn = prop.get("definition") or {}
            if (defn.get("name") or "").lower() == target:
                v = prop.get("value")
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    lv = v.strip().lower()
                    if lv in ("true", "1", "yes", "oui"):
                        return True
                    if lv in ("false", "0", "no", "non"):
                        return False
    return None


def _unique_strings(items: Iterable[Any] | None) -> list[str]:
    seen: list[str] = []
    if not items:
        return seen
    for it in items:
        if isinstance(it, dict):
            it = it.get("name") or it.get("label")
        if not isinstance(it, str):
            continue
        s = it.strip()
        if s and s not in seen:
            seen.append(s)
    return seen


def bim_object_from_element(element: dict, snapshot: ModelSnapshot) -> BimObject:
    """Construit un :class:`BimObject` à partir d'un élément BIMData.

    Args:
        element: Élément BIMData dénormalisé (issu de ``/element/raw``).
        snapshot: Snapshot complet (pour résolution spatiale).
    """
    uuid = element.get("uuid") or element.get("globalid") or ""
    spatial = _spatial_for(snapshot, uuid) if uuid else {}

    return BimObject(
        uuid=uuid,
        ifc_type=element.get("type"),
        name=element.get("name"),
        long_name=element.get("long_name") or element.get("longname"),
        object_type=element.get("object_type") or element.get("objecttype"),
        predefined_type=element.get("predefined_type") or element.get("predefinedtype"),
        description=element.get("description"),
        storey_uuid=spatial.get("storey_uuid"),
        storey_name=spatial.get("storey_name"),
        zone_uuid=spatial.get("zone_uuid"),
        zone_name=spatial.get("zone_name"),
        space_uuid=spatial.get("space_uuid"),
        space_name=spatial.get("space_name"),
        is_external=_extract_pset_bool(element, "IsExternal"),
        load_bearing=_extract_pset_bool(element, "LoadBearing"),
        layers=_unique_strings(element.get("layers")),
        materials=_unique_strings(element.get("materials")),
        classifications=_extract_classifications(element),
        properties=_extract_properties(element),
        base_quantities=_extract_base_quantities(element),
        source="bimdata",
    )


def iter_bim_objects(
    snapshot: ModelSnapshot, *, include_spatial: bool = False
) -> Iterator[BimObject]:
    """Itère les :class:`BimObject` d'un snapshot.

    Args:
        snapshot: Photo du modèle.
        include_spatial: Si True, inclut aussi les éléments des classes
            spatiales (``IfcSite``, ``IfcBuilding``, ``IfcBuildingStorey``,
            ``IfcSpace``, ``IfcZone``). Par défaut on les exclut — un
            audit "objets" porte sur les composants.
    """
    for el in snapshot.elements:
        if not include_spatial and el.get("type") in _SPATIAL_CLASSES:
            continue
        yield bim_object_from_element(el, snapshot)
    if include_spatial:
        for kind, items in (
            ("IfcSite", snapshot.sites),
            ("IfcBuilding", snapshot.buildings),
            ("IfcBuildingStorey", snapshot.storeys),
            ("IfcSpace", snapshot.spaces),
            ("IfcZone", snapshot.zones),
        ):
            for it in items:
                yield bim_object_from_element({**it, "type": kind}, snapshot)
