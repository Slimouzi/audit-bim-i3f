"""Filtres déclaratifs sur :class:`BimObject`, ``Finding`` et suggestions.

Chaque filtre est un modèle Pydantic v2 — il peut donc être :

- construit côté tool MCP à partir d'un dict JSON (validation automatique),
- sérialisé pour journalisation (``model_dump_json``),
- combiné avec d'autres filtres en intersection (« ET » implicite entre
  champs, « OU » entre listes d'un même champ).

Les filtres ne contiennent **aucune logique d'application** : ils
décrivent uniquement les critères. Le moteur d'application vit dans
:mod:`audit_bim.query.filtering`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Constantes communes ──────────────────────────────────────────────────

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


class ConfidenceBand(str, Enum):
    """Bandes de confiance pour les suggestions de classification.

    Calibrées sur les pondérations du suggester (``W_IFC_CLASS=0.50``,
    ``W_LAYER=0.20`` …) :

    - ``HIGH`` ≥ 0.85 : 3+ signaux concordants, application quasi sûre.
    - ``MEDIUM`` ∈ [0.55, 0.85[ : 2 signaux, à valider par AMO BIM.
    - ``LOW`` < 0.55 : classe IFC seule ou signal faible.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_score(cls, score: float) -> ConfidenceBand:
        """Mappe un score 0..1 sur une bande."""
        if score >= 0.85:
            return cls.HIGH
        if score >= 0.55:
            return cls.MEDIUM
        return cls.LOW


class SuggestionStatus(str, Enum):
    """Statut d'une suggestion dans le :class:`ClassificationSuggestionStore`.

    Cycle de vie :
    ``proposed`` → ``accepted`` (par AMO) → ``applied`` (poussée API),
    ou ``proposed`` → ``rejected``.
    """

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    APPLIED = "applied"


# ── ObjectFilter ─────────────────────────────────────────────────────────


class ObjectFilter(BaseModel):
    """Filtre déclaratif sur :class:`BimObject`.

    Combinaison ET implicite entre champs ; pour les champs liste
    (``ifc_types``, ``storey_names`` …), OU implicite entre valeurs.

    Exemples
    --------

    « Tous les IfcWall sans classification » ::

        ObjectFilter(ifc_types=["IfcWall", "IfcWallStandardCase"],
                     has_any_classification=False)

    « Tous les éléments d'un étage donné dont une propriété est absente » ::

        ObjectFilter(storey_names=["R+1"],
                     missing_property="Pset_WallCommon.FireRating")

    « Tous les éléments avec classification UniFormat existante » ::

        ObjectFilter(classification_system="uniformat",
                     has_any_classification=True)
    """

    model_config = ConfigDict(extra="forbid")

    # Identité
    uuids: list[str] | None = Field(None, description="Liste de UUID IFC à inclure (OU implicite).")

    # Classe IFC
    ifc_types: list[str] | None = Field(
        None,
        description="Classes IFC à inclure (matching exact, OU implicite).",
    )

    # Rattachement spatial
    storey_names: list[str] | None = None
    storey_uuids: list[str] | None = None
    zone_names: list[str] | None = None
    zone_uuids: list[str] | None = None
    space_names: list[str] | None = None
    space_uuids: list[str] | None = None

    # Attributs structurants
    is_external: bool | None = None
    load_bearing: bool | None = None

    # Classifications actuelles (sur le BimObject)
    classification_system: str | None = Field(
        None,
        description=(
            "Système à considérer pour `has_any_classification`, "
            "`current_classification_codes` et `current_level_3`."
        ),
    )
    has_any_classification: bool | None = Field(
        None,
        description=(
            "True = filtrer les objets qui ONT au moins une classification "
            "(éventuellement restreinte par `classification_system`). False = "
            "filtrer ceux qui n'en ont aucune. None = pas de contrainte."
        ),
    )
    current_classification_codes: list[str] | None = Field(
        None,
        description="Codes de classification actuels à matcher (OU implicite).",
    )
    current_level_3: list[str] | None = Field(
        None,
        description="Codes niveau 3 (5 premiers caractères normalisés).",
    )

    # Propriétés (Pset.Prop)
    has_property: str | None = Field(
        None,
        description="Clé `Pset.Prop` qui doit être présente ET non vide.",
    )
    missing_property: str | None = Field(
        None,
        description="Clé `Pset.Prop` qui doit être absente ou vide.",
    )

    # Matériaux / layers
    layer_contains: str | None = Field(
        None,
        description="Sous-chaîne à matcher dans n'importe quel layer (insensible à la casse).",
    )
    material_contains: str | None = Field(
        None,
        description="Sous-chaîne à matcher dans n'importe quel matériau (insensible à la casse).",
    )

    # Source
    source: str | None = Field(
        None,
        description="Origine du BimObject (`bimdata`, `doe`, `ifc` …).",
    )

    # Pagination
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    offset: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _check_mutually_exclusive(self) -> ObjectFilter:
        if self.has_property and self.missing_property:
            same = self.has_property.lower() == self.missing_property.lower()
            if same:
                raise ValueError("has_property et missing_property pointent sur la même clé.")
        return self


# ── FindingFilter ────────────────────────────────────────────────────────


class FindingFilter(BaseModel):
    """Filtre déclaratif sur les ``Finding`` d'un ``AuditResult``."""

    model_config = ConfigDict(extra="forbid")

    themes: list[str] | None = Field(
        None,
        description="Valeurs Theme.value (ex: 'Nommage Pièce', 'Classification IFC').",
    )
    severities: list[str] | None = Field(
        None,
        description="Valeurs Severity.value (CRITICAL|HIGH|MEDIUM|LOW|INFO).",
    )
    severity_min: str | None = Field(
        None,
        description="Sévérité minimale (inclusive). Retourne les findings "
        "≥ ce seuil dans l'ordre CRITICAL > HIGH > MEDIUM > LOW > INFO.",
    )
    error_types: list[str] | None = Field(
        None, description="Valeurs ErrorType.value (ex: 'classification_missing')."
    )
    ifc_types: list[str] | None = None
    element_uuids: list[str] | None = None

    # Anomalies projet vs anomalies d'élément
    require_element_uuid: bool | None = Field(
        None,
        description=(
            "True = exclure les anomalies projet (sans element_uuid). "
            "False = ne retourner QUE les anomalies projet."
        ),
    )

    # Pagination
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    offset: int = Field(0, ge=0)


# ── SuggestionFilter ─────────────────────────────────────────────────────


class SuggestionFilter(BaseModel):
    """Filtre déclaratif sur les entrées du :class:`ClassificationSuggestionStore`.

    Permet d'exprimer :

    - « tous les objets sans classification mais avec proposition confiance ≥ 0.85 »
    - « tous les E2020200 ramenés au niveau 3 E2020 »
    - « tous les IfcWall proposés B2010 »
    - « toutes les suggestions acceptées »
    """

    model_config = ConfigDict(extra="forbid")

    element_uuids: list[str] | None = None
    ifc_types: list[str] | None = None

    proposed_codes: list[str] | None = Field(
        None,
        description="Codes proposés (matching exact, OU implicite).",
    )
    proposed_level_3: list[str] | None = Field(
        None,
        description="Niveaux 3 proposés (UniFormat 5 premiers caractères).",
    )

    min_confidence: float | None = Field(None, ge=0.0, le=1.0)
    max_confidence: float | None = Field(None, ge=0.0, le=1.0)
    confidence_bands: list[ConfidenceBand] | None = None

    statuses: list[SuggestionStatus] | None = None

    # Écart entre classification actuelle et proposée
    only_mismatches: bool | None = Field(
        None,
        description="True = seules les suggestions où current ≠ proposed "
        "(en niveau 3). False = seules celles qui matchent.",
    )
    only_missing_current: bool | None = Field(
        None,
        description="True = seules les suggestions où l'élément n'a pas "
        "de classification actuelle.",
    )

    sources: list[str] | None = Field(
        None,
        description="Origine de la suggestion (`audit`, `xlsx_review`, `manual`, `doe`).",
    )

    # Pagination
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    offset: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _check_confidence_range(self) -> SuggestionFilter:
        if (
            self.min_confidence is not None
            and self.max_confidence is not None
            and self.min_confidence > self.max_confidence
        ):
            raise ValueError("min_confidence > max_confidence")
        return self
