"""Résolution de l'adresse projet à partir d'un ModelSnapshot.

Stratégie en cascade :

1. Surcharge utilisateur (texte libre — peut venir d'un champ DOE).
2. ``IfcBuilding.BuildingAddress`` (premier bâtiment trouvé avec adresse).
3. ``IfcSite.SiteAddress`` (premier site trouvé avec adresse).
4. ``ValueError`` si rien d'exploitable.

Les attributs IFC ``IfcPostalAddress`` sont restitués par BIMData sous
forme de dict ``{AddressLines: [...], PostalCode, Town, Region, Country}``.
"""

from __future__ import annotations

from typing import Any

from .models import ProjectAddress


def _from_postal_dict(d: dict | None, source: str) -> ProjectAddress | None:
    """Convertit un dict ``IfcPostalAddress`` en ``ProjectAddress``.

    Args:
        d: Dict brut renvoyé par BIMData.
        source: Étiquette d'origine (ifc_building / ifc_site).

    Returns:
        ``ProjectAddress`` ou ``None`` si le dict est vide / inutilisable.
    """
    if not isinstance(d, dict):
        return None
    raw_lines = d.get("AddressLines") or []
    if isinstance(raw_lines, str):
        raw_lines = [raw_lines]
    lines = [str(s).strip() for s in raw_lines if s and str(s).strip()]
    addr = ProjectAddress(
        source=source,
        address_lines=lines,
        postal_code=(d.get("PostalCode") or "").strip() or None,
        town=(d.get("Town") or "").strip() or None,
        region=(d.get("Region") or "").strip() or None,
        country=(d.get("Country") or "").strip() or None,
    )
    if not (addr.address_lines or addr.postal_code or addr.town):
        return None
    return addr


def resolve_project_address(
    snapshot: Any,
    *,
    override: str | None = None,
    override_source: str = "override",
) -> ProjectAddress:
    """Cherche l'adresse projet exploitable pour le géocodage.

    Args:
        snapshot: ``ModelSnapshot`` extrait par ``extract_model_snapshot``.
            Doit exposer ``buildings`` et ``sites`` (listes de dicts).
        override: Adresse libre prioritaire. Peut être copiée depuis le
            DOE par le caller — passer ``override_source="doe"`` pour le
            tracer dans le rapport.
        override_source: Étiquette de source à appliquer à ``override``
            (``override`` par défaut, ``doe`` si l'adresse vient du DOE).

    Returns:
        ``ProjectAddress`` prêt à être géocodé.

    Raises:
        ValueError: Si aucune adresse exploitable n'est trouvée.
    """
    if override and override.strip():
        src = override_source if override_source in {"override", "doe"} else "override"
        return ProjectAddress(source=src, address_lines=[override.strip()])

    buildings = getattr(snapshot, "buildings", None) or []
    for b in buildings:
        addr = _from_postal_dict(b.get("BuildingAddress"), "ifc_building")
        if addr:
            return addr

    sites = getattr(snapshot, "sites", None) or []
    for s in sites:
        addr = _from_postal_dict(s.get("SiteAddress"), "ifc_site")
        if addr:
            return addr

    raise ValueError(
        "Aucune adresse exploitable trouvée dans le modèle "
        "(IfcBuilding.BuildingAddress / IfcSite.SiteAddress absents ou vides). "
        "Fournir `address_override` (adresse manuelle ou extraite du DOE)."
    )
