"""``ProjectAddress`` — adresse postale brute du projet (avant validation BAN).

Type **partagé** entre ``doe`` (extraction depuis le DOE) et ``enrichment``
(résolution IFC + géocodage). Il vit dans ``domain/`` — la couche basse que les
deux connaissent — pour casser le cycle ``doe ↔ enrichment`` : ``doe`` importe ce
type depuis ``domain`` (jamais depuis ``enrichment``), la seule dépendance
restante ``enrichment → doe`` (fonction d'extraction) devient unidirectionnelle.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProjectAddress(BaseModel):
    """Adresse postale brute extraite du modèle (avant validation BAN).

    Attributes:
        source: D'où vient l'adresse (IFC Building, IFC Site, DOE,
            ou surcharge utilisateur).
        address_lines: Lignes d'adresse libres (n° + voie, etc.).
        postal_code: Code postal.
        town: Commune.
        region: Région / département (si renseigné dans l'IFC).
        country: Pays.
    """

    source: Literal["ifc_building", "ifc_site", "doe", "override"] = "ifc_building"
    address_lines: list[str] = Field(default_factory=list)
    postal_code: str | None = None
    town: str | None = None
    region: str | None = None
    country: str | None = None

    def to_query(self) -> str:
        """Compose la chaîne ``q=`` à envoyer à BAN."""
        parts = list(self.address_lines)
        if self.postal_code:
            parts.append(self.postal_code)
        if self.town:
            parts.append(self.town)
        return " ".join(p.strip() for p in parts if p and p.strip())
