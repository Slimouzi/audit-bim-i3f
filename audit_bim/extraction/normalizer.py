"""Helpers de normalisation pour comparer attendu (catalogue) vs réel (modèle).

Les Psets BIMData ont une forme inlinée — on expose des accesseurs utilitaires
qui gomment les variantes (clé absente, valeur ``None``, casse différente…).
"""
from __future__ import annotations

from typing import Any, Optional

# Attributs IFC natifs (qui ne sont PAS dans des Psets mais dans `attributes`)
NATIVE_IFC_ATTRIBUTES = {
    "name",
    "longname",
    "description",
    "objecttype",
    "globalid",
    "tag",
    "predefinedtype",
    "latitude",
    "longitude",
    "refelevation",
    "elevation",
}


def get_attribute(element: dict, attr_name: str) -> Optional[Any]:
    """Récupère un attribut IFC natif d'un élément (Name, LongName, …).

    On accepte plusieurs sources (clé flat à la racine, ou Pset ``Attributes``).
    """
    if not attr_name:
        return None
    key_lower = attr_name.lower()
    flat_aliases = {
        "name": "name",
        "longname": "longname",
        "objecttype": "object_type",
        "description": "description",
    }
    if key_lower in flat_aliases:
        v = element.get(flat_aliases[key_lower])
        if v not in (None, ""):
            return v
    attrs_pset = element.get("attributes") or {}
    for prop in (attrs_pset.get("properties") or []):
        nm = (prop.get("definition") or {}).get("name") or ""
        if nm.lower() == key_lower:
            return prop.get("value")
    # Fallback : certains payloads exposent les attributes en flat
    for k, v in element.items():
        if isinstance(k, str) and k.lower() == key_lower:
            return v
    return None


def get_property(
    element: dict, pset_name: str, property_name: str
) -> Optional[Any]:
    """Récupère la valeur d'une propriété ``Pset.PropertyName`` d'un élément.

    Args:
        element: élément BIMData dénormalisé.
        pset_name: nom du property set (``Pset_SpaceCommon``…). Une sous-chaîne
            est tolérée pour absorber les suffixes (« Pset_SpaceCommon (BL01) »).
        property_name: nom de la propriété (``GrossFloorArea``, ``FloorCovering``…).
    """
    if not pset_name or not property_name:
        return None
    p_lower = pset_name.lower()
    name_lower = property_name.lower()
    for pset in element.get("property_sets") or []:
        pn = (pset.get("name") or "").lower()
        if p_lower not in pn:
            continue
        for prop in pset.get("properties") or []:
            nm = (prop.get("definition") or {}).get("name") or ""
            if nm.lower() == name_lower:
                return prop.get("value")
    return None


def has_classification(element: dict) -> bool:
    return bool(element.get("classifications"))


def classification_codes(element: dict) -> list[str]:
    return [c.get("notation") or c.get("name") for c in (element.get("classifications") or [])]


def resolve_value(
    element: dict, pset_or_attribute: Optional[str], property_name: str
) -> Optional[Any]:
    """Tente plusieurs heuristiques pour retrouver une valeur attendue.

    Les annexes I3F mélangent dans la même colonne :
    - des **Psets** (``Pset_SpaceCommon``, ``Pset_3F``…),
    - des **attributs IFC natifs** (``Name``, ``LongName``, ``ObjectType``,
      ``Latitude``…),
    - des chemins composites (``Pset_SpaceCommon/HandicapAccessible``,
      ``BaseQuantites/NetFloorArea``).

    On *parse* l'expression et on essaie successivement :
    1. attribut natif si le nom appartient à ``NATIVE_IFC_ATTRIBUTES`` ;
    2. ``Pset.Property`` si le chemin contient ``/`` ou ``.`` ;
    3. ``pset_or_attribute`` comme Pset + ``property_name`` comme propriété ;
    4. fallback : ``property_name`` comme attribut natif.
    """
    src = (pset_or_attribute or "").strip()
    src_lower = src.lower()

    # 1. Cas attribut natif
    if src_lower in NATIVE_IFC_ATTRIBUTES:
        return get_attribute(element, src)
    if (
        src_lower in ("relatif à la classe ifcname", "relatif à la classe ifcdescription")
        or src_lower.startswith("relatif à la classe ")
    ):
        # « Relatif à la classe IfcXxx » → on tente le nom de la propriété
        # comme attribut natif (Name, Description…).
        return get_attribute(element, property_name)

    # 2. Chemin composite Pset/Property
    if "/" in src or "." in src:
        parts = src.replace(".", "/").split("/", 1)
        if len(parts) == 2:
            pset, prop = parts
            v = get_property(element, pset.strip(), prop.strip())
            if v is not None:
                return v

    # 3. Pset = src, prop = property_name
    if src.lower().startswith("pset"):
        v = get_property(element, src, property_name)
        if v is not None:
            return v

    # 4. Fallback attribut natif sur property_name
    pn_lower = property_name.lower()
    if pn_lower in NATIVE_IFC_ATTRIBUTES:
        return get_attribute(element, property_name)

    return None
