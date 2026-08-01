"""Export SHAB maquette (.xlsx) — builder nommé délégant au multi-onglets."""

from __future__ import annotations

from .xlsx_common import _build_multisheet_export_xlsx


def build_shab_xlsx(path, src, meta):
    return _build_multisheet_export_xlsx(
        path, "EXPORT SHAB MAQUETTE", "AVP - export SHAB maquette", src, meta
    )
