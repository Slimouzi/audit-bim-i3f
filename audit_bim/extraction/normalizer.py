"""Helpers de normalisation pour comparer attendu (catalogue) vs réel (modèle).

Les Psets BIMData ont une forme inlinée — on expose des accesseurs utilitaires
qui gomment les variantes (clé absente, valeur ``None``, casse différente…).
"""

from __future__ import annotations

from typing import Any

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

# Attributs de repli : certains outils auteurs (ArchiCAD notamment) placent le
# nom métier dans `Name` alors que le CCH l'attend dans `LongName`. Le repli
# permet de retrouver la donnée ; l'appelant peut signaler le mauvais
# emplacement via `get_attribute_with_fallback(..., report_source=True)`.
ATTRIBUTE_FALLBACKS: dict[str, list[str]] = {
    "longname": ["name"],
}

# Repli quantités : surfaces attendues en BaseQuantities mais souvent
# présentes uniquement dans les psets de marque de zone ArchiCAD.
# (pset_prefix, [propriétés candidates par ordre de préférence])
QUANTITY_FALLBACKS: list[tuple[str, list[str]]] = [
    (
        "AC_Pset_Marque_de_zone",
        [
            # ArchiCAD FR nomme la propriété tantôt « Surface … » tantôt
            # « Superficie … » selon la version / le gabarit. On couvre les
            # deux familles, sinon un « surface manquante » à tort en audit.
            "Surface nette mesurée",
            "Surface mesurée",
            "Surface calculée",
            "Superficie nette mesurée",
            "Superficie mesurée",
            "Superficie calculée",
        ],
    ),
]

_AREA_PROPERTY_TOKENS = ("area", "surface")


def get_quantity_with_fallback(element: dict, pset_name: str, property_name: str) -> Any | None:
    """Comme :func:`get_property`, avec repli ArchiCAD pour les surfaces.

    Si ``BaseQuantities.<prop>`` est absent et que la propriété est une
    surface (Area/Surface), on tente les psets ``AC_Pset_Marque_de_zone_*``
    ('Surface'/'Superficie' nette mesurée / mesurée / calculée).
    """
    v = get_property(element, pset_name, property_name)
    if v is not None:
        return v
    if not any(tok in property_name.lower() for tok in _AREA_PROPERTY_TOKENS):
        return None
    for pset_prefix, candidates in QUANTITY_FALLBACKS:
        for candidate in candidates:
            v = get_property(element, pset_prefix, candidate)
            if v is not None:
                return v
    return None


def get_attribute_with_fallback(
    element: dict, attr_name: str, report_source: bool = False
) -> Any | tuple[Any | None, str | None]:
    """Comme :func:`get_attribute`, avec repli sur les attributs équivalents.

    Args:
        element: élément BIMData dénormalisé.
        attr_name: attribut demandé (``LongName``…).
        report_source: si ``True``, renvoie ``(valeur, attribut_source)`` —
            ``attribut_source`` vaut ``attr_name`` si trouvé directement, le
            nom de l'attribut de repli sinon (``None`` si rien trouvé).

    Returns:
        La valeur (ou le tuple ``(valeur, source)`` si ``report_source``).
    """
    v = get_attribute(element, attr_name)
    if v not in (None, ""):
        return (v, attr_name) if report_source else v
    for fallback in ATTRIBUTE_FALLBACKS.get(attr_name.lower(), []):
        v = get_attribute(element, fallback)
        if v not in (None, ""):
            return (v, fallback) if report_source else v
    return (None, None) if report_source else None


def get_attribute(element: dict, attr_name: str) -> Any | None:
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
    for prop in attrs_pset.get("properties") or []:
        nm = (prop.get("definition") or {}).get("name") or ""
        if nm.lower() == key_lower:
            return prop.get("value")
    # Fallback : certains payloads exposent les attributes en flat
    for k, v in element.items():
        if isinstance(k, str) and k.lower() == key_lower:
            return v
    return None


def get_property(element: dict, pset_name: str, property_name: str) -> Any | None:
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


def material_names(element: dict) -> list[str]:
    """Noms de matériaux d'un élément.

    L'association matériau n'est **pas** un attribut plat : ``bimdata-read`` l'inline
    en ``material_list`` (``[{"material": {"name": …}}]``, repli ``materials``). Sans
    cet accès dédié, un locateur ``IfcMaterial`` ne matche rien dans
    :func:`resolve_value` → 100 % de faux ``PROPERTY_MISSING`` (E3). Même forme que
    les helpers de ``reporting`` (``avp_i3f._material_name``)."""
    out: list[str] = []
    for key in ("material_list", "materials"):
        for item in element.get(key) or []:
            if isinstance(item, str):
                nm = item
            elif isinstance(item, dict):
                nm = (item.get("material") or {}).get("name") or item.get("name")
            else:
                nm = None
            if nm and nm not in out:
                out.append(nm)
    return out


def has_classification(element: dict) -> bool:
    return bool(element.get("classifications"))


def classification_codes(element: dict) -> list[str]:
    return [c.get("notation") or c.get("name") for c in (element.get("classifications") or [])]


def resolve_value(element: dict, pset_or_attribute: str | None, property_name: str) -> Any | None:
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

    # 0a. Locateur « IfcXxx » désignant un attribut natif (IfcName, IfcDescription…) :
    #     le préfixe de classe est un abus fréquent des annexes (V3.7). Sans
    #     normalisation, aucune étape ne matche → 100 % de faux PROPERTY_MISSING (E3).
    if src_lower.startswith("ifc") and src_lower[3:] in NATIVE_IFC_ATTRIBUTES:
        src = src[3:]
        src_lower = src.lower()

    # 0b. Matériau : association inlinée par bimdata-read (material_list), pas un
    #     attribut plat. Résolu à part (E3) — présent → nom(s) ; absent → None
    #     (audit_properties émet alors un PROPERTY_MISSING légitime, pas un faux).
    if src_lower in ("ifcmaterial", "material", "materiau", "materiaux"):
        names = material_names(element)
        return ", ".join(names) if names else None

    # 1. Cas attribut natif (avec repli LongName → Name : certains outils
    #    auteurs remplissent Name là où le CCH attend LongName)
    if src_lower in NATIVE_IFC_ATTRIBUTES:
        return get_attribute_with_fallback(element, src)
    if src_lower in (
        "relatif à la classe ifcname",
        "relatif à la classe ifcdescription",
    ) or src_lower.startswith("relatif à la classe "):
        # « Relatif à la classe IfcXxx » → on tente le nom de la propriété
        # comme attribut natif (Name, Description…).
        return get_attribute(element, property_name)

    # 2. Chemin composite Pset/Property (avec repli ArchiCAD pour les
    #    surfaces BaseQuantities absentes → 'Surface mesurée')
    if "/" in src or "." in src:
        parts = src.replace(".", "/").split("/", 1)
        if len(parts) == 2:
            pset, prop = parts
            if "basequantit" in pset.strip().lower():
                v = get_quantity_with_fallback(element, pset.strip(), prop.strip())
            else:
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
        return get_attribute_with_fallback(element, property_name)

    return None
