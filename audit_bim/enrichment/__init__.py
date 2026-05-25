"""Enrichissement de la maquette par les open data publiques françaises.

Pipeline : adresse projet (IFC ou DOE) → BAN (validation/géocodage) →
DPE ADEME + PLU GPU + Géorisques → :class:`EnrichmentReport` agrégé.

Toutes les APIs sont publiques, sans authentification.

Pour la **découverte ad-hoc** de jeux de données data.gouv.fr (au-delà
des 4 sources branchées ici), brancher le serveur officiel
``datagouv-mcp`` côté client Claude/ChatGPT :

::

    claude mcp add --transport http datagouv https://mcp.data.gouv.fr/mcp
"""

from .address import resolve_project_address
from .ban import geocode_address
from .dpe import lookup_dpe
from .enricher import enrich_with_public_data
from .georisques import lookup_georisques
from .models import (
    DPERecord,
    EnrichmentReport,
    GeocodingResult,
    GeoriskItem,
    GeoriskReport,
    PLUZoning,
    ProjectAddress,
)
from .plu import lookup_plu

__all__ = [
    "DPERecord",
    "EnrichmentReport",
    "GeocodingResult",
    "GeoriskItem",
    "GeoriskReport",
    "PLUZoning",
    "ProjectAddress",
    "enrich_with_public_data",
    "geocode_address",
    "lookup_dpe",
    "lookup_georisques",
    "lookup_plu",
    "resolve_project_address",
]
