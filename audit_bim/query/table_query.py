"""Ré-export : moteur de requête tabulaire (package ``bim-query``).

L'implémentation vit désormais dans **``bim-query``**. Ce module ré-exporte les
symboles derrière le chemin historique ``audit_bim.query.table_query`` —
consommé par ``mcp/tools_query.py``. Comportement inchangé.
"""

from __future__ import annotations

from bim_query.table_query import (
    KNOWN_FIELDS,
    BimQuery,
    BimQueryResult,
    BimQueryRow,
    query_bim_table,
)

__all__ = [
    "KNOWN_FIELDS",
    "BimQuery",
    "BimQueryRow",
    "BimQueryResult",
    "query_bim_table",
]
