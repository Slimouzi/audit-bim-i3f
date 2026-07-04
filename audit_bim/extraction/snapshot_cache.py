"""Ré-export : cache local du ``ModelSnapshot`` (noyau lecture ``bimdata-read``).

Chemin d'import historique préservé
(``from audit_bim.extraction.snapshot_cache import cached_extract_snapshot``).
La logique (clé de cache, sérialisation gzip versionnée, extraction avec repli)
vit désormais dans ``bimdata_read.cache``.
"""

from __future__ import annotations

from bimdata_read.cache import (
    _CACHE_SCHEMA_VERSION,
    _cache_key,
    _cache_path,
    cached_extract_snapshot,
    load_snapshot_from_cache,
    save_snapshot_to_cache,
)

__all__ = [
    "cached_extract_snapshot",
    "load_snapshot_from_cache",
    "save_snapshot_to_cache",
    "_cache_key",
    "_cache_path",
    "_CACHE_SCHEMA_VERSION",
]
