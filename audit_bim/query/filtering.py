"""Ré-export : application des filtres déclaratifs (package ``bim-query``).

L'implémentation vit désormais dans **``bim-query``** (couche requête read-only,
dépend de ``bim-core`` uniquement). Ce module ré-exporte les mêmes symboles
derrière le chemin historique ``audit_bim.query.filtering`` — aucun call-site à
réécrire (``mcp/selection.py``, ``actions/*_planner.py``), comportement et
erreurs observables **inchangés**.

La *source* des suggestions (``ClassificationSuggestionStore``) reste côté
``audit-bim-i3f`` ; ``apply_suggestion_filter`` (bim-query) l'accepte via
duck-typing structurel (``.all()``).
"""

from __future__ import annotations

from bim_query.filtering import (
    ConfidenceBand,
    SuggestionStatus,
    apply_finding_filter,
    apply_object_filter,
    apply_suggestion_filter,
    finding_matches,
    object_matches,
    suggestion_matches,
)

__all__ = [
    "apply_object_filter",
    "apply_finding_filter",
    "apply_suggestion_filter",
    "object_matches",
    "finding_matches",
    "suggestion_matches",
    "ConfidenceBand",
    "SuggestionStatus",
]
