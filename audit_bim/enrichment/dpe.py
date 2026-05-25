"""Client Diagnostic de Performance Énergétique ADEME.

Dataset interrogé : ``dpe-v2-logements-existants`` (DPE v2, en vigueur
depuis le 1er juillet 2021). API Data Fair de l'ADEME, publique :
https://data.ademe.fr/datasets/dpe-v2-logements-existants

Recherche par rayon géographique autour du point BAN — l'adresse
inscrite sur le DPE n'étant pas toujours parfaitement normalisée, la
recherche spatiale donne de meilleurs résultats qu'une recherche textuelle.
"""

from __future__ import annotations

from typing import Any

import requests

from .models import DPERecord, GeocodingResult

DPE_URL = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe-v2-logements-existants/lines"


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def lookup_dpe(
    geo: GeocodingResult,
    *,
    max_results: int = 10,
    radius_m: int = 50,
    timeout: float = 8.0,
) -> list[DPERecord]:
    """Cherche les DPE déclarés à proximité immédiate du point géocodé.

    Args:
        geo: Sortie de :func:`audit_bim.enrichment.ban.geocode_address`.
            ``matched=False`` ou coordonnées manquantes → renvoie ``[]``.
        max_results: Nombre maximal de DPE retournés (tri décroissant par
            date d'établissement).
        radius_m: Rayon de recherche autour du point (mètres).
        timeout: Timeout HTTP.

    Returns:
        Liste de :class:`DPERecord`. Vide si la commune ou le bâtiment
        n'a pas de DPE déclaré dans le rayon donné.
    """
    if not geo.matched or geo.lat is None or geo.lon is None:
        return []

    params = {
        "size": max_results,
        "geo_distance": f"{geo.lon}:{geo.lat}:{radius_m}m",
        "sort": "-date_etablissement_dpe",
    }
    try:
        r = requests.get(DPE_URL, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return []

    out: list[DPERecord] = []
    for row in data.get("results") or []:
        out.append(
            DPERecord(
                numero_dpe=row.get("n_dpe") or row.get("numero_dpe"),
                date_etablissement=row.get("date_etablissement_dpe"),
                etiquette_dpe=row.get("etiquette_dpe"),
                etiquette_ges=row.get("etiquette_ges"),
                consommation_kwh_m2_an=_safe_float(
                    row.get("conso_5_usages_par_m2_ep") or row.get("conso_ep_m2")
                ),
                emission_ges_kg_co2_m2_an=_safe_float(
                    row.get("emission_ges_5_usages_par_m2") or row.get("emission_ges_m2")
                ),
                type_batiment=row.get("type_batiment"),
                annee_construction=_safe_int(row.get("annee_construction")),
                surface_habitable=_safe_float(row.get("surface_habitable_logement")),
                adresse_brut=row.get("adresse_brut") or row.get("adresse_ban"),
            )
        )
    return out
