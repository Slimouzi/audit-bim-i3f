"""Modèles Pydantic du module d'enrichissement open data.

Toutes les structures intermédiaires de la chaîne
**adresse projet → BAN → (DPE / PLU / Géorisques) → rapport agrégé**
sont définies ici pour la sérialisation MCP / JSON.
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


class GeocodingResult(BaseModel):
    """Résultat de validation BAN (Base Adresse Nationale).

    Attributes:
        matched: ``True`` si BAN a renvoyé au moins un résultat exploitable.
        score: Score de confiance BAN entre 0 et 1.
        label: Adresse normalisée renvoyée par BAN.
        citycode: Code INSEE commune (5 caractères, ex ``75056``).
        postcode: Code postal normalisé.
        type: ``housenumber`` / ``street`` / ``locality`` / ``municipality``.
        lon, lat: Coordonnées WGS84.
        raw: Dictionnaire ``properties`` brut renvoyé par BAN (pour debug).
    """

    matched: bool
    score: float = 0.0
    label: str | None = None
    citycode: str | None = None
    postcode: str | None = None
    type: str | None = None
    lon: float | None = None
    lat: float | None = None
    raw: dict | None = None


class DPERecord(BaseModel):
    """Enregistrement DPE (Diagnostic de Performance Énergétique) ADEME.

    Schéma simplifié des champs les plus utiles pour un AMO BIM ; le
    dataset ADEME complet contient ~150 colonnes.
    """

    numero_dpe: str | None = None
    date_etablissement: str | None = None
    etiquette_dpe: str | None = None  # A à G
    etiquette_ges: str | None = None  # A à G
    consommation_kwh_m2_an: float | None = None
    emission_ges_kg_co2_m2_an: float | None = None
    type_batiment: str | None = None
    annee_construction: int | None = None
    surface_habitable: float | None = None
    adresse_brut: str | None = None


class PLUZoning(BaseModel):
    """Zonage PLU/PLUi (Géoportail de l'Urbanisme via apicarto IGN).

    Attributes:
        typezone: Type de zone (``U``, ``AU``, ``A``, ``N``...).
        libelle: Libellé local de la zone (ex ``UAa1``, ``UC``).
        nomfic: Nom du fichier source du PLU (commune / date approbation).
        commune: Commune d'application.
    """

    typezone: str | None = None
    libelle: str | None = None
    nomfic: str | None = None
    commune: str | None = None


class GeoriskItem(BaseModel):
    """Aléa ou risque identifié à proximité de l'adresse."""

    type: str  # "risque_naturel", "icpe", "mouvement_terrain", ...
    libelle: str | None = None
    niveau: str | None = None
    distance_m: float | None = None


class GeoriskReport(BaseModel):
    """Synthèse Géorisques agrégée sur les endpoints interrogés."""

    items: list[GeoriskItem] = Field(default_factory=list)
    nb_aleas: int = 0


class EnrichmentReport(BaseModel):
    """Rapport complet d'enrichissement par les open data publiques.

    Attributes:
        address: Adresse projet utilisée pour le géocodage.
        geocoding: Résultat BAN — détermine si les autres lookups
            ont été effectués (un géocodage non matché coupe la chaîne).
        dpe_records: Liste des DPE trouvés à proximité (tri décroissant date).
        plu_zones: Zonages PLU applicables au point.
        georisks: Synthèse Géorisques.
        sources_used: Liste des sources effectivement interrogées.
        sources_errors: Erreurs par source (clé = nom de source).
    """

    address: ProjectAddress
    geocoding: GeocodingResult
    dpe_records: list[DPERecord] = Field(default_factory=list)
    plu_zones: list[PLUZoning] = Field(default_factory=list)
    georisks: GeoriskReport = Field(default_factory=GeoriskReport)
    sources_used: list[str] = Field(default_factory=list)
    sources_errors: dict[str, str] = Field(default_factory=dict)
