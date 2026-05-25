"""Client GPU/PLU — Géoportail de l'Urbanisme via apicarto IGN.

Endpoint public ``/api/gpu/zone-urba`` : interroge le zonage des
documents d'urbanisme numérisés (PLU, PLUi, POS) à partir d'une
géométrie GeoJSON.

Doc : https://apicarto.ign.fr/api/doc/gpu
"""

from __future__ import annotations

import json

import requests

from .models import GeocodingResult, PLUZoning

GPU_ZONE_URBA = "https://apicarto.ign.fr/api/gpu/zone-urba"


def lookup_plu(geo: GeocodingResult, *, timeout: float = 8.0) -> list[PLUZoning]:
    """Récupère le zonage PLU applicable au point géocodé.

    Args:
        geo: Géocodage BAN. Sans coordonnées valides, renvoie ``[]``.
        timeout: Timeout HTTP.

    Returns:
        Liste de :class:`PLUZoning`. Vide si la commune n'a pas de PLU
        numérisé dans le GPU.
    """
    if not geo.matched or geo.lat is None or geo.lon is None:
        return []

    geom = {"type": "Point", "coordinates": [geo.lon, geo.lat]}
    try:
        r = requests.get(GPU_ZONE_URBA, params={"geom": json.dumps(geom)}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return []

    out: list[PLUZoning] = []
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        out.append(
            PLUZoning(
                typezone=props.get("typezone"),
                libelle=props.get("libelle") or props.get("libelong"),
                nomfic=props.get("nomfic"),
                commune=props.get("nom_commune") or props.get("commune"),
            )
        )
    return out
