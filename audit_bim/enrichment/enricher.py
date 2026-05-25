"""Orchestrator de l'enrichissement maquette → open data publiques.

Pipeline :

::

    snapshot ──► resolve_project_address ──► ProjectAddress
                                                 │
                                                 ▼
                                          geocode_address (BAN)
                                                 │
                              ┌──────────────────┼─────────────────┐
                              ▼                  ▼                 ▼
                       lookup_dpe (ADEME)   lookup_plu (GPU)   lookup_georisques

Si BAN ne valide pas l'adresse (``matched=False``), on s'arrête là —
inutile de bombarder les autres APIs avec un point inconnu.

Erreurs par source : capturées individuellement et exposées dans
``EnrichmentReport.sources_errors`` plutôt que de faire planter
l'ensemble.
"""

from __future__ import annotations

from typing import Any

from .address import resolve_project_address
from .ban import geocode_address
from .dpe import lookup_dpe
from .georisques import lookup_georisques
from .models import EnrichmentReport
from .plu import lookup_plu


def enrich_with_public_data(
    snapshot: Any,
    *,
    address_override: str | None = None,
    address_override_source: str = "override",
    doe_path: str | None = None,
    include_dpe: bool = True,
    include_plu: bool = True,
    include_georisques: bool = True,
    radius_dpe_m: int = 50,
    radius_georisques_m: int = 1000,
) -> EnrichmentReport:
    """Construit un :class:`EnrichmentReport` à partir d'un ``ModelSnapshot``.

    Args:
        snapshot: ``ModelSnapshot`` extrait via ``extract_model_snapshot``.
        address_override: Adresse libre prioritaire sur l'extraction IFC.
            Utile si l'adresse n'est pas renseignée dans la maquette ou
            si l'utilisateur veut surcharger avec une adresse issue du DOE.
        address_override_source: Étiquette à appliquer (``override`` ou
            ``doe``) pour tracer l'origine dans le rapport.
        doe_path: Chemin du fichier DOE (xlsx/pdf/image). Si l'IFC ne
            renseigne pas d'adresse, on tente une auto-extraction sur
            les en-têtes du DOE. Cf.
            :func:`audit_bim.doe.address.extract_address_from_doe`.
        include_dpe / include_plu / include_georisques: switches par source.
        radius_dpe_m: Rayon de recherche DPE autour du point BAN (mètres).
        radius_georisques_m: Rayon de recherche Géorisques (mètres).

    Returns:
        :class:`EnrichmentReport`. Si BAN ne valide pas l'adresse,
        seuls ``address`` et ``geocoding`` sont remplis.
    """
    address = resolve_project_address(
        snapshot,
        override=address_override,
        override_source=address_override_source,
        doe_path=doe_path,
    )
    geo = geocode_address(address)

    report = EnrichmentReport(address=address, geocoding=geo)
    if not geo.matched:
        return report

    report.sources_used.append("ban")

    if include_dpe:
        try:
            report.dpe_records = lookup_dpe(geo, radius_m=radius_dpe_m)
            report.sources_used.append("dpe-ademe")
        except Exception as e:  # noqa: BLE001 — capture défensive HTTP
            report.sources_errors["dpe-ademe"] = str(e)

    if include_plu:
        try:
            report.plu_zones = lookup_plu(geo)
            report.sources_used.append("plu-gpu")
        except Exception as e:  # noqa: BLE001
            report.sources_errors["plu-gpu"] = str(e)

    if include_georisques:
        try:
            report.georisks = lookup_georisques(geo, radius_m=radius_georisques_m)
            report.sources_used.append("georisques")
        except Exception as e:  # noqa: BLE001
            report.sources_errors["georisques"] = str(e)

    return report
