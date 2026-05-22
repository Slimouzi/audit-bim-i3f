"""Modèle de Finding (anomalie d'audit BIM) et taxonomie associée."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Sévérité d'une anomalie.

    - ``CRITICAL`` : empêche un livrable BIM d'être conforme à la phase.
    - ``HIGH``     : anomalie majeure (donnée structurante manquante).
    - ``MEDIUM``   : donnée requise par le CCH manquante / non conforme.
    - ``LOW``      : qualité de donnée (format, casse, valeurs hors liste).
    - ``INFO``     : signalement contextuel sans gravité.
    """

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @classmethod
    def ordered(cls) -> list["Severity"]:
        return [cls.CRITICAL, cls.HIGH, cls.MEDIUM, cls.LOW, cls.INFO]


class Theme(str, Enum):
    """Thème d'audit (1 onglet xlsx + 1 smart view par thème)."""

    SPATIAL_HIERARCHY = "Hiérarchie spatiale"
    NAMING_SITE_BAT_ETAGE = "Nommage Site / Bâtiment / Étage"
    NAMING_ZONE = "Nommage Zone"
    NAMING_SPACE = "Nommage Pièce"
    PROPERTY_MISSING = "Propriété manquante"
    PROPERTY_INVALID = "Propriété invalide"
    CLASSIFICATION = "Classification IFC"
    QUANTITY = "Quantités (surfaces, volumes)"
    DOCUMENT = "Document attendu"


class ErrorType(str, Enum):
    """Type fin d'erreur (regroupement plus granulaire pour le reporting)."""

    NAMING_MISSING = "naming_missing"
    NAMING_INVALID_FORMAT = "naming_invalid_format"
    NAMING_NOT_IN_LIST = "naming_not_in_list"
    NAMING_TOO_LONG = "naming_too_long"
    PROPERTY_MISSING = "property_missing"
    PROPERTY_EMPTY = "property_empty"
    PROPERTY_TYPE_INVALID = "property_type_invalid"
    CLASSIFICATION_MISSING = "classification_missing"
    CLASSIFICATION_INVALID = "classification_invalid"
    SPATIAL_ORPHAN = "spatial_orphan"
    SPATIAL_MISSING_QUANTITY = "spatial_missing_quantity"
    DOCUMENT_MISSING = "document_missing"


class Finding(BaseModel):
    """Une anomalie unitaire détectée par l'audit."""

    theme: Theme
    severity: Severity
    error_type: ErrorType

    element_uuid: Optional[str] = Field(
        None, description="UUID/GlobalId IFC de l'objet en erreur (None si erreur projet)."
    )
    ifc_type: Optional[str] = Field(
        None, description="Classe IFC (IfcSpace, IfcBuilding, …)."
    )
    name: Optional[str] = None
    storey: Optional[str] = Field(None, description="Étage de rattachement si connu.")
    zone: Optional[str] = Field(None, description="Zone (logement) de rattachement si connue.")

    expected: Optional[Any] = Field(None, description="Valeur ou règle attendue.")
    actual: Optional[Any] = Field(None, description="Valeur réellement trouvée (None si manquant).")

    ref_cch: Optional[str] = Field(None, description="Référence du chapitre du CCH.")
    recommended_action: Optional[str] = Field(
        None, description="Action concrète à effectuer pour corriger."
    )

    def short_label(self) -> str:
        parts = [self.ifc_type or "?", self.name or self.element_uuid or "?"]
        return " — ".join(p for p in parts if p)


def severity_color(sev: Severity) -> str:
    """Code couleur hex (sans #) par sévérité — utilisé par les reporters."""
    return {
        Severity.CRITICAL: "B22222",
        Severity.HIGH: "D2691E",
        Severity.MEDIUM: "DAA520",
        Severity.LOW: "6B8E23",
        Severity.INFO: "4682B4",
    }[sev]
