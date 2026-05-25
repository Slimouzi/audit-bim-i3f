"""Client Géorisques — aléas naturels et technologiques.

API publique : https://www.georisques.gouv.fr/doc-api

On agrège plusieurs endpoints (un par famille de risque) en
tolérant les erreurs individuellement : un endpoint qui échoue ou
qui renvoie un schéma inattendu est simplement ignoré, le rapport
final reste partiel mais exploitable.
"""

from __future__ import annotations

from typing import Any

import requests

from .models import GeocodingResult, GeoriskItem, GeoriskReport

GR_BASE = "https://www.georisques.gouv.fr/api/v1"


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# Endpoints interrogés. Format : (path, type_label).
# On reste sur les endpoints "synthèse" qui acceptent code_insee + latlon.
_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("/gaspar/risques", "risque_naturel"),
    ("/installations_classees", "icpe"),
    ("/mvt", "mouvement_terrain"),
)


def _extract_item(row: dict, kind: str) -> GeoriskItem:
    """Adapte un row Géorisques (schéma variable) en :class:`GeoriskItem`."""
    libelle = (
        row.get("libelle_risque_long")
        or row.get("libelle_risque")
        or row.get("libelle_court")
        or row.get("nom_etablissement")
        or row.get("libelle")
        or str(row.get("type") or "")
        or None
    )
    niveau = row.get("niveau_alea") or row.get("niveau") or row.get("regime")
    return GeoriskItem(
        type=kind,
        libelle=libelle,
        niveau=str(niveau) if niveau is not None else None,
        distance_m=_safe_float(row.get("distance")),
    )


def lookup_georisques(
    geo: GeocodingResult,
    *,
    radius_m: int = 1000,
    timeout: float = 8.0,
    max_per_endpoint: int = 20,
) -> GeoriskReport:
    """Compile un rapport multi-aléas autour du point géocodé.

    Args:
        geo: Géocodage BAN. ``citycode`` et coordonnées requis.
        radius_m: Rayon de recherche autour du point (mètres).
        timeout: Timeout HTTP par endpoint.
        max_per_endpoint: Plafond d'items extraits par endpoint pour
            éviter de saturer la sortie MCP.

    Returns:
        :class:`GeoriskReport` agrégé. Vide si géocodage incomplet.
    """
    if not geo.matched or geo.citycode is None or geo.lat is None or geo.lon is None:
        return GeoriskReport()

    latlon = f"{geo.lat},{geo.lon}"
    params = {
        "code_insee": geo.citycode,
        "latlon": latlon,
        "rayon": radius_m,
        "page": 1,
        "page_size": max_per_endpoint,
    }

    items: list[GeoriskItem] = []
    for path, kind in _ENDPOINTS:
        try:
            r = requests.get(GR_BASE + path, params=params, timeout=timeout)
            if r.status_code != 200:
                continue
            data = r.json()
        except (requests.RequestException, ValueError):
            continue
        rows = data.get("data") or data.get("results") or []
        for row in rows[:max_per_endpoint]:
            if isinstance(row, dict):
                items.append(_extract_item(row, kind))

    return GeoriskReport(items=items, nb_aleas=len(items))
