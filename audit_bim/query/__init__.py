"""Ré-export : moteur de filtrage local et adaptateurs domaine.

L'implémentation vit désormais dans le package **``bim-query``** (couche requête
read-only sur un ``ModelSnapshot`` normalisé, dépend de ``bim-core`` uniquement).
Ce package ``audit_bim.query`` reste une **façade** : mêmes symboles, mêmes
chemins d'import historiques, comportement inchangé. Les tools MCP de filtrage
et les planners ``actions/`` continuent d'importer d'ici.
"""

from __future__ import annotations

from .filtering import (
    apply_finding_filter,
    apply_object_filter,
    apply_suggestion_filter,
)
from .views import bim_object_from_element, iter_bim_objects

__all__ = [
    "iter_bim_objects",
    "bim_object_from_element",
    "apply_object_filter",
    "apply_finding_filter",
    "apply_suggestion_filter",
]
