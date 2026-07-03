"""Ré-export des filtres déclaratifs (``ObjectFilter``, ``FindingFilter``,
``SuggestionFilter`` + enums associés), désormais hébergés dans ``bim-core``.

Point d'import historique conservé
(``from audit_bim.domain.filters import ObjectFilter``).
"""

from __future__ import annotations

from bim_core.filters import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    ConfidenceBand,
    FindingFilter,
    ObjectFilter,
    SuggestionFilter,
    SuggestionStatus,
)

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "ConfidenceBand",
    "SuggestionStatus",
    "ObjectFilter",
    "FindingFilter",
    "SuggestionFilter",
]
