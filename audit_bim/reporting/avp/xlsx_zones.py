"""Export Zones et Espaces (.xlsx) — builder nommé délégant au multi-onglets."""

from __future__ import annotations

from .xlsx_common import _build_multisheet_export_xlsx


def build_zones_xlsx(path, src, meta):
    return _build_multisheet_export_xlsx(
        path, "EXPORT ZONES ET ESPACES", "Export Zones et Espaces", src, meta
    )
