"""Builder « export plancher » (.xlsx) — multi-onglets (dalles IfcSlab)."""

from __future__ import annotations

from pathlib import Path

from .xlsx_common import _build_multisheet_export_xlsx


def _build_plancher_xlsx(path, sources, meta) -> Path:
    """Export plancher (dalles ``IfcSlab``) — **multi-onglets** comme SHAB/Zones.

    Reproduit **tous** les onglets de la source I3F (« … Dalles Ok », « Planchers »
    avec totaux/écarts) ; repli maquette (un seul onglet « Planchers ») câblé par
    l'orchestrateur. Aucune valeur inventée : onglet source vide préservé tel quel.
    """
    return _build_multisheet_export_xlsx(
        path,
        "EXPORT PLANCHER",
        "Export plancher",
        (sources.plancher if sources else None),
        meta,
    )
