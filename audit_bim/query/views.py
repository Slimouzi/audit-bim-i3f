"""Ré-export : adaptateurs ``ModelSnapshot`` → ``BimObject`` (package ``bim-query``).

L'implémentation vit désormais dans **``bim-query``**. Ce module ré-exporte les
symboles derrière le chemin historique ``audit_bim.query.views`` — y compris
``_SPATIAL_CLASSES``, importé par ``mcp/selection.py``. Comportement inchangé,
aucune modification du ``ModelSnapshot`` original.
"""

from __future__ import annotations

from bim_query.views import (
    _SPATIAL_CLASSES,
    bim_object_from_element,
    iter_bim_objects,
)

__all__ = [
    "iter_bim_objects",
    "bim_object_from_element",
    "_SPATIAL_CLASSES",
]
