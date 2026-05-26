"""Résolveur d'alias sémantiques pour les propriétés BIM.

Permet à un agent IA (ou un AMO) de demander des concepts métier
(« performance acoustique », « largeur », « fabricant ») sans connaître
le nom exact de la propriété IFC / Pset.

Stratégie de matching
---------------------

1. **Exact** (insensible à la casse) sur le nom complet ``Pset.Prop``.
2. **Suffixe** : un alias court comme ``"AcousticRating"`` matche
   ``"Pset_DoorCommon.AcousticRating"`` (≈ Revit/ArchiCAD style).
3. **Fallback hiérarchique** : on essaie d'abord les ``properties``
   (Psets), puis ``base_quantities`` (BaseQuantities IFC), puis les
   attributs natifs (``ObjectType``, ``PredefinedType``).
4. **Multi-langue** : noms français reconnus en parallèle des noms
   IFC officiels.

Conception
----------

Aucun side-effect, fonctions pures. Aucune dépendance MCP. Utilisable
hors `tools_query` (par ex. dans un futur outil CLI).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.bim_object import BimObject

# ── Tables d'alias ───────────────────────────────────────────────────────


ACOUSTIC_ALIASES: list[str] = [
    "Rw",
    "AcousticRating",
    "SoundReductionIndex",
    "IndiceAffaiblissementAcoustique",
    "PerformanceAcoustique",
    "IsolementAcoustique",
    "Pset_DoorCommon.AcousticRating",
    "Pset_WallCommon.AcousticRating",
    "Pset_SlabCommon.AcousticRating",
    "Pset_WindowCommon.AcousticRating",
]

FIRE_RATING_ALIASES: list[str] = [
    "FireRating",
    "DegreReactionFeu",
    "DegreCoupeFeu",
    "ResistanceAuFeu",
    "Pset_DoorCommon.FireRating",
    "Pset_WallCommon.FireRating",
    "Pset_SlabCommon.FireRating",
]

DIMENSION_ALIASES: dict[str, list[str]] = {
    "height": ["Height", "OverallHeight", "Hauteur", "BaseQuantities.Height"],
    "width": ["Width", "OverallWidth", "Largeur", "BaseQuantities.Width"],
    "thickness": [
        "Thickness",
        "Epaisseur",
        "Pset_DoorCommon.Thickness",
        "Pset_WallCommon.Thickness",
    ],
    "area": [
        "NetArea",
        "GrossArea",
        "Area",
        "NetSideArea",
        "Surface",
        "BaseQuantities.NetArea",
    ],
    "volume": [
        "NetVolume",
        "GrossVolume",
        "Volume",
        "BaseQuantities.NetVolume",
    ],
    "perimeter": ["Perimeter", "Perimetre", "GrossPerimeter"],
    "length": ["Length", "Longueur", "BaseQuantities.Length"],
}

MATERIAL_ALIASES: list[str] = [
    "Material",
    "MaterialName",
    "Materiau",
    "Matériau",
    "Pset_MaterialCommon.Material",
    "Pset_MaterialCommon.MaterialName",
]

MANUFACTURER_ALIASES: list[str] = [
    "Manufacturer",
    "Fabricant",
    "Marque",
    "Brand",
    "Pset_ManufacturerTypeInformation.Manufacturer",
    "Pset_3F.Fabricant",
]

REFERENCE_ALIASES: list[str] = [
    "Reference",
    "ModelReference",
    "ArticleNumber",
    "ProductReference",
    "Référence",
    "Pset_3F.Reference",
    "Pset_ManufacturerTypeInformation.ModelLabel",
]

TAG_ALIASES: list[str] = [
    "Tag",
    "Mark",
    "Repere",
    "Repère",
    "Identifiant",
]

MAINTENANCE_ID_ALIASES: list[str] = [
    "MaintenanceID",
    "AssetID",
    "EquipmentID",
    "IdGmao",
    "GMAO_ID",
    "Pset_3F.MaintenanceID",
]

SERIAL_NUMBER_ALIASES: list[str] = [
    "SerialNumber",
    "NumeroSerie",
    "Pset_ManufacturerTypeInformation.SerialNumber",
    "Pset_3F.SerialNumber",
]


# ── Résultat de résolution ──────────────────────────────────────────────


@dataclass(frozen=True)
class MatchedValue:
    """Résultat d'une résolution d'alias.

    Attributes:
        value: Valeur trouvée (peut être ``bool / int / float / str /
            list``).
        source: D'où vient la valeur. Valeurs :
            - ``"property"`` : Pset (ex. ``Pset_DoorCommon.AcousticRating``)
            - ``"quantity"`` : BaseQuantity IFC (``Height`` etc.)
            - ``"attribute"`` : attribut natif (``ObjectType``, ``Name``)
            - ``"material"`` : extrait de ``materials``
            - ``"layer"`` : extrait de ``layers``
            - ``"classification"`` : code de classification
            - ``"missing"`` : pas trouvé (``value`` = ``None``)
        matched_key: Clé exacte qui a matché (utile pour debug et
            traçabilité ; vide si source = "missing").
    """

    value: Any
    source: str
    matched_key: str = ""


# ── Helpers de normalisation ────────────────────────────────────────────


def normalize_key(value: str) -> str:
    """Normalise une chaîne pour matching : lowercase + strip.

    Pas de normalisation Unicode agressive — on garde les accents
    (les noms français comme ``Matériau`` doivent matcher tel quel).
    """
    return (value or "").strip().lower()


def _matches_alias(key: str, alias: str) -> bool:
    """Compare ``key`` (la clé d'une propriété, ex. ``Pset_DoorCommon.AcousticRating``)
    à ``alias`` (court ou complet, ex. ``AcousticRating`` ou
    ``Pset_DoorCommon.AcousticRating``).

    Match si :
    - ``key == alias`` (insensible à la casse)
    - ``key`` se termine par ``"." + alias`` (insensible à la casse)
    """
    k = normalize_key(key)
    a = normalize_key(alias)
    if not a:
        return False
    if k == a:
        return True
    # Suffixe : `Pset_DoorCommon.AcousticRating` matche `AcousticRating`
    return k.endswith("." + a)


# ── Résolveurs ──────────────────────────────────────────────────────────


def find_property_value(obj: BimObject, aliases: list[str]) -> MatchedValue | None:
    """Cherche la 1ère valeur correspondant à un alias dans ``obj.properties``.

    Args:
        obj: BimObject.
        aliases: Liste ordonnée d'alias (le 1er match gagne).

    Returns:
        ``MatchedValue`` si trouvé, ``None`` sinon. Une valeur vide
        (``None`` / chaîne vide) est traitée comme "non trouvée".
    """
    for alias in aliases:
        for key, val in obj.properties.items():
            if not _matches_alias(key, alias):
                continue
            if val is None:
                continue
            if isinstance(val, str) and not val.strip():
                continue
            return MatchedValue(value=val, source="property", matched_key=key)
    return None


def find_quantity_value(obj: BimObject, aliases: list[str]) -> MatchedValue | None:
    """Cherche dans ``obj.base_quantities`` (avec normalisation du préfixe
    ``BaseQuantities.``).
    """
    for alias in aliases:
        a = normalize_key(alias)
        # Strip préfixe BaseQuantities. si présent
        if a.startswith("basequantities."):
            a = a[len("basequantities.") :]
        for key, val in obj.base_quantities.items():
            if normalize_key(key) == a:
                return MatchedValue(value=val, source="quantity", matched_key=key)
    return None


def find_attribute_value(obj: BimObject, aliases: list[str]) -> MatchedValue | None:
    """Cherche dans les attributs natifs du BimObject (champs Pydantic).

    Couvre ``name``, ``long_name``, ``object_type``, ``predefined_type``,
    ``description``, ``tag`` (via attribut ``Tag`` du BimObject si présent),
    etc.
    """
    # Mapping alias → attribut Pydantic du BimObject
    attr_map = {
        "name": "name",
        "longname": "long_name",
        "long_name": "long_name",
        "objecttype": "object_type",
        "object_type": "object_type",
        "type": "object_type",
        "predefinedtype": "predefined_type",
        "predefined_type": "predefined_type",
        "description": "description",
        "ifc_type": "ifc_type",
        "ifctype": "ifc_type",
    }
    for alias in aliases:
        attr_name = attr_map.get(normalize_key(alias))
        if not attr_name:
            continue
        v = getattr(obj, attr_name, None)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return MatchedValue(value=v, source="attribute", matched_key=attr_name)
    return None


def find_material_value(obj: BimObject) -> MatchedValue | None:
    """Renvoie la liste dédupliquée des matériaux (via
    :meth:`BimObject.materials_summary`)."""
    materials = obj.materials_summary()
    if not materials:
        return None
    return MatchedValue(value=materials, source="material", matched_key="materials")


# ── Résolveur principal ─────────────────────────────────────────────────


# Mapping field → aliases (utilisé par ``resolve_requested_field``)
_FIELD_RESOLVERS: dict[str, list[str]] = {
    "acoustic_performance": ACOUSTIC_ALIASES,
    "acoustic": ACOUSTIC_ALIASES,
    "fire_rating": FIRE_RATING_ALIASES,
    "fire": FIRE_RATING_ALIASES,
    "manufacturer": MANUFACTURER_ALIASES,
    "reference": REFERENCE_ALIASES,
    "tag": TAG_ALIASES,
    "maintenance_id": MAINTENANCE_ID_ALIASES,
    "serial_number": SERIAL_NUMBER_ALIASES,
}


def resolve_requested_field(obj: BimObject, field: str) -> dict[str, Any]:
    """Résolveur de haut niveau pour un champ demandé par l'utilisateur.

    Gère les champs :

    - **Identité / attributs** : ``uuid``, ``ifc_type``, ``name``,
      ``long_name``, ``object_type``, ``predefined_type``, ``description``.
    - **Spatial** : ``storey``, ``space``, ``zone``.
    - **Classifications** : ``classification`` (1er code), ``classification_level_3``.
    - **Matériaux / calques** : ``materials``, ``layers``.
    - **Dimensions** : ``height``, ``width``, ``thickness``, ``area``,
      ``volume``, ``perimeter``, ``length`` (via BaseQuantities puis
      fallback Pset).
    - **Booléens IFC** : ``is_external``, ``load_bearing``.
    - **Sémantique** : ``acoustic_performance``, ``fire_rating``,
      ``manufacturer``, ``reference``, ``tag``, ``maintenance_id``,
      ``serial_number``.
    - **Carte des dimensions** : ``dimensions`` (dict de 5 valeurs).

    Tout autre nom est essayé dynamiquement comme un alias de propriété
    (utile pour les Pset projet : ``Pset_3F.Lot``).

    Returns:
        Dict ``{"value": ..., "source": ..., "matched_key": ...}``.
        ``source`` vaut ``"missing"`` quand rien n'est trouvé.
    """
    field_key = normalize_key(field)

    # 1. Attributs directs du BimObject ────────────────────────────────────
    direct_attr = {
        "uuid": "uuid",
        "ifc_type": "ifc_type",
        "name": "name",
        "long_name": "long_name",
        "object_type": "object_type",
        "predefined_type": "predefined_type",
        "description": "description",
        "storey": "storey_name",
        "storey_name": "storey_name",
        "space": "space_name",
        "space_name": "space_name",
        "zone": "zone_name",
        "zone_name": "zone_name",
        "is_external": "is_external",
        "load_bearing": "load_bearing",
        "source": "source",
    }
    if field_key in direct_attr:
        v = getattr(obj, direct_attr[field_key], None)
        return _result(v, "attribute" if v is not None else "missing", direct_attr[field_key])

    # 2. Listes (materials / layers / classifications) ────────────────────
    if field_key == "materials":
        materials = obj.materials_summary()
        return _result(materials or None, "material" if materials else "missing", "materials")
    if field_key == "layers":
        return _result(obj.layers or None, "layer" if obj.layers else "missing", "layers")
    if field_key == "classification":
        codes = obj.classification_codes()
        return _result(
            codes[0] if codes else None,
            "classification" if codes else "missing",
            "classifications[0].code",
        )
    if field_key == "classification_level_3":
        if obj.classifications:
            l3 = obj.classifications[0].level_3
            return _result(l3 if l3 else None, "classification", "classifications[0].level_3")
        return _result(None, "missing", "")
    if field_key == "classifications":
        # Liste de dicts {code, label, system}
        if obj.classifications:
            return _result(
                [
                    {"code": c.code, "label": c.label, "system": c.system}
                    for c in obj.classifications
                ],
                "classification",
                "classifications",
            )
        return _result(None, "missing", "")

    # 3. Dimensions composées (`dimensions` retourne le dict complet) ─────
    if field_key == "dimensions":
        dims = obj.dimensions_summary()
        if any(v is not None for v in dims.values()):
            return _result(dims, "quantity", "BaseQuantities")
        return _result(None, "missing", "")

    # 4. Dimensions individuelles (height / width / …) ────────────────────
    if field_key in DIMENSION_ALIASES:
        aliases = DIMENSION_ALIASES[field_key]
        # On essaie d'abord les quantities puis les properties
        for resolver in (find_quantity_value, find_property_value):
            mv = resolver(obj, aliases)
            if mv is not None:
                return _result(mv.value, mv.source, mv.matched_key)
        return _result(None, "missing", "")

    # 5. Champs sémantiques (acoustique, feu, fabricant, …) ───────────────
    if field_key in _FIELD_RESOLVERS:
        aliases = _FIELD_RESOLVERS[field_key]
        # property first (typiquement Pset), puis quantity, puis attribute
        for resolver in (find_property_value, find_quantity_value):
            mv = resolver(obj, aliases)
            if mv is not None:
                return _result(mv.value, mv.source, mv.matched_key)
        return _result(None, "missing", "")

    # 6. Fallback dynamique : on essaie le champ tel quel comme alias
    # de propriété (utile pour ``Pset_3F.Lot``, ``Pset_3F.Local``, etc.).
    mv = find_property_value(obj, [field])
    if mv is not None:
        return _result(mv.value, mv.source, mv.matched_key)
    # Puis quantity
    mv = find_quantity_value(obj, [field])
    if mv is not None:
        return _result(mv.value, mv.source, mv.matched_key)
    # Puis attribut
    mv = find_attribute_value(obj, [field])
    if mv is not None:
        return _result(mv.value, mv.source, mv.matched_key)

    return _result(None, "missing", "")


def _result(value: Any, source: str, matched_key: str) -> dict[str, Any]:
    """Forme standardisée du retour de :func:`resolve_requested_field`."""
    return {"value": value, "source": source, "matched_key": matched_key}


__all__ = [
    "ACOUSTIC_ALIASES",
    "FIRE_RATING_ALIASES",
    "DIMENSION_ALIASES",
    "MATERIAL_ALIASES",
    "MANUFACTURER_ALIASES",
    "REFERENCE_ALIASES",
    "TAG_ALIASES",
    "MAINTENANCE_ID_ALIASES",
    "SERIAL_NUMBER_ALIASES",
    "MatchedValue",
    "normalize_key",
    "find_property_value",
    "find_quantity_value",
    "find_attribute_value",
    "find_material_value",
    "resolve_requested_field",
]
