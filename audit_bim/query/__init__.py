"""Moteur de filtrage local et adaptateurs domaine.

Cette couche est la **seule** à connaître à la fois :

- la structure brute des éléments BIMData (via ``extraction/``) ;
- les modèles domaine (:class:`audit_bim.domain.BimObject` etc.) ;
- les filtres déclaratifs (:class:`audit_bim.domain.ObjectFilter` etc.).

Les tools MCP de filtrage (``filter_bim_objects``, ``list_audit_findings``,
``list_classification_suggestions``) **doivent passer par ces fonctions**
plutôt que de recalculer leur propre vérité — c'est ce qui garantit que
BCF, Smart Views et corrections API consomment exactement le même index.
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
