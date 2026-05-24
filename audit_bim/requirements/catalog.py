"""Agrégateur des 3 parseurs MOA → ``RequirementsCatalog`` unifié.

Politique de fusion :
- Le **xlsx** est la source autoritaire des exigences (priorité).
- Le **PDF** sert de complément (version du CCH, listes manquantes si une
  annexe n'a pas été fournie par le MOA).
"""
from __future__ import annotations

from pathlib import Path

from .data_spec_parser import parse_data_spec
from .models import RequirementsCatalog
from .naming_spec_parser import parse_naming_spec
from .pdf_parser import parse_pdf


def build_catalog(
    cch_pdf: str | Path | None = None,
    data_spec_xlsx: str | Path | None = None,
    naming_spec_xlsx: str | Path | None = None,
) -> RequirementsCatalog:
    """Construit un catalogue à partir des documents disponibles.

    Tous les arguments sont optionnels : un catalogue partiel est produit avec
    ce qui peut être lu. Le minimum exploitable est *un* des trois documents.

    Args:
        cch_pdf: Cahier des charges principal (PDF). Source de la version du CCH
            et fallback pour les listes manquantes.
        data_spec_xlsx: Annexe « Spécification des données ». Source autoritaire
            des PropertySpec (objets × phases BIM).
        naming_spec_xlsx: Annexe « Nommage ». Source autoritaire des règles de
            nommage et listes fermées (étages, zones, pièces).

    Returns:
        Catalogue agrégé.
    """
    catalog = RequirementsCatalog()

    if data_spec_xlsx and Path(data_spec_xlsx).exists():
        catalog.properties = parse_data_spec(data_spec_xlsx)
        catalog.data_spec_source = str(data_spec_xlsx)

    if naming_spec_xlsx and Path(naming_spec_xlsx).exists():
        rules, storeys, zones, rooms = parse_naming_spec(naming_spec_xlsx)
        catalog.naming_rules = rules
        catalog.storey_names = storeys
        catalog.zone_specs = zones
        catalog.room_specs = rooms
        catalog.naming_spec_source = str(naming_spec_xlsx)

    if cch_pdf and Path(cch_pdf).exists():
        pdf = parse_pdf(cch_pdf)
        catalog.cch_version = pdf.get("cch_version") or catalog.cch_version
        catalog.cch_source_pdf = str(cch_pdf)
        # Fallback : complète les listes vides
        if not catalog.storey_names:
            catalog.storey_names = pdf.get("storey_names") or []
        if not catalog.zone_specs:
            catalog.zone_specs = pdf.get("zone_specs") or []
        if not catalog.room_specs:
            catalog.room_specs = pdf.get("room_specs") or []

    return catalog
