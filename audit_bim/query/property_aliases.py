"""Ré-export : résolveur d'alias sémantiques (package ``bim-query``).

L'implémentation vit désormais dans **``bim-query``**. Ce module ré-exporte les
symboles derrière le chemin historique ``audit_bim.query.property_aliases``.
Comportement inchangé.
"""

from __future__ import annotations

from bim_query.property_aliases import (
    ACOUSTIC_ALIASES,
    DIMENSION_ALIASES,
    FIRE_RATING_ALIASES,
    MAINTENANCE_ID_ALIASES,
    MANUFACTURER_ALIASES,
    MATERIAL_ALIASES,
    REFERENCE_ALIASES,
    SERIAL_NUMBER_ALIASES,
    TAG_ALIASES,
    MatchedValue,
    find_attribute_value,
    find_material_value,
    find_property_value,
    find_quantity_value,
    normalize_key,
    resolve_requested_field,
)

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
