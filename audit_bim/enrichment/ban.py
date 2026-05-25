"""Client Base Adresse Nationale — géocodage et validation d'adresse.

API publique data.gouv.fr (sans authentification) :
https://adresse.data.gouv.fr/api-doc/adresse
"""

from __future__ import annotations

import requests

from .models import GeocodingResult, ProjectAddress

BAN_URL = "https://api-adresse.data.gouv.fr/search/"


def geocode_address(
    address: ProjectAddress,
    *,
    limit: int = 1,
    timeout: float = 5.0,
) -> GeocodingResult:
    """Interroge BAN pour valider/normaliser une adresse projet.

    Args:
        address: Adresse extraite du modèle ou fournie par l'utilisateur.
        limit: Nombre de résultats demandés à BAN (on ne garde que le premier).
        timeout: Timeout HTTP en secondes.

    Returns:
        ``GeocodingResult`` avec ``matched=False`` si :

        - la requête est vide,
        - BAN ne renvoie aucun résultat,
        - une erreur HTTP / JSON survient (capturée silencieusement,
          l'erreur est tracée dans ``raw["error"]``).
    """
    q = address.to_query()
    if not q:
        return GeocodingResult(matched=False)

    try:
        r = requests.get(BAN_URL, params={"q": q, "limit": limit}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        return GeocodingResult(matched=False, raw={"error": str(e)})

    features = data.get("features") or []
    if not features:
        return GeocodingResult(matched=False)

    f = features[0]
    props = f.get("properties") or {}
    geom = f.get("geometry") or {}
    coords = geom.get("coordinates") or []
    lon = coords[0] if len(coords) > 0 else None
    lat = coords[1] if len(coords) > 1 else None

    return GeocodingResult(
        matched=True,
        score=float(props.get("score") or 0.0),
        label=props.get("label"),
        citycode=props.get("citycode"),
        postcode=props.get("postcode"),
        type=props.get("type"),
        lon=lon,
        lat=lat,
        raw=props,
    )
