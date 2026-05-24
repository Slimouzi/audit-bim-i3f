"""Modèles de l'audit BIM : anomalies, sévérités, thèmes, types d'erreur.

Ce module est la **single source of truth** pour les types Pydantic et Enum
utilisés par :

- le moteur d'audit (``audit_bim.audit.engine`` et règles dans ``rules/``)
- les reporters (Word, XLSX, Smart Views, BCF)
- la persistance JSON (``audit_*_findings.json``)
- le serveur MCP (sérialisation côté outils)

Conception
----------
Une *anomalie* (``Finding``) est unitaire — un seul élément concerné
identifié par son ``element_uuid``. Pour les anomalies projet (« 0
instance d'IfcSite »), ``element_uuid`` est ``None`` et ``ifc_type`` porte
la classe concernée.

Trois axes de classification :

- ``Severity`` — gravité (CRITICAL → INFO)
- ``Theme``    — domaine fonctionnel (1 onglet xlsx + 1 vue par thème)
- ``ErrorType`` — type fin pour le reporting (1 onglet xlsx par type)
"""
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
        """Renvoie les sévérités triées de la plus grave à la moins grave.

        Utilisé pour le tri stable des findings (CRITICAL d'abord) et pour
        déterminer la sévérité « max » d'un thème (= la plus grave).

        Returns:
            Liste ordonnée : ``[CRITICAL, HIGH, MEDIUM, LOW, INFO]``.
        """
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
    """Une anomalie unitaire détectée par l'audit.

    Sérialisable directement en JSON (``model_dump(mode="json")``) pour
    persistance et transport MCP. Chaque champ est typé et documenté pour
    la traçabilité (un finding sans ``ref_cch`` n'est pas opposable au MOA).

    Attributes:
        theme: Domaine d'audit (Hiérarchie spatiale, Nommage Zone, …).
        severity: Gravité (CRITICAL → INFO).
        error_type: Type fin pour groupement en onglet xlsx.
        element_uuid: GlobalId IFC de l'élément en erreur. ``None`` pour
            les anomalies projet (ex: « ≥ 1 IfcSite attendu »).
        ifc_type: Classe IFC réelle de l'élément (peut différer de la
            classe-mère définie au CCH : ``IfcWallStandardCase`` matche
            les exigences de ``IfcWall``).
        name: Nom IFC (``Name`` ou ``LongName``).
        storey: Étage de rattachement si connu.
        zone: Zone (logement) de rattachement si connue.
        expected: Valeur ou règle attendue par le CCH.
        actual: Valeur réellement trouvée. ``None`` = manquant.
        ref_cch: Référence du chapitre du CCH (ex: ``"Chap 6.2"``).
        recommended_action: Action corrective concrète (phrase impérative).
    """

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
        """Libellé court de l'élément pour les listes et le verbeux.

        Format : ``"<IfcClass> — <Name or UUID>"``. Utilisé dans les
        en-têtes de tableau Word et les sorties JSON synthétiques.

        Returns:
            Libellé condensé, par exemple ``"IfcSpace — CHAMBRE 01"``.
        """
        parts = [self.ifc_type or "?", self.name or self.element_uuid or "?"]
        return " — ".join(p for p in parts if p)


def severity_color(sev: Severity) -> str:
    """Code couleur hexadécimal (sans ``#``) par sévérité.

    Délègue à ``audit_bim.reporting.theming.SEVERITY_COLORS`` qui est la
    *single source of truth*. Palette feux tricolores :

    - ``CRITICAL`` → rouge foncé (``8B0000``)
    - ``HIGH``     → rouge       (``DC3545``)
    - ``MEDIUM``   → orange      (``FF8C00``)
    - ``LOW``      → vert        (``28A745``)
    - ``INFO``     → bleu        (``4682B4``)

    Args:
        sev: La sévérité dont on veut la couleur.

    Returns:
        Code hex sur 6 caractères, sans préfixe (ex: ``"DC3545"``).

    Raises:
        KeyError: Si la sévérité n'a pas de couleur définie (jamais en
            usage normal puisque les Enum couvrent toutes les valeurs).
    """
    from ..reporting.theming import SEVERITY_COLORS

    return SEVERITY_COLORS[sev.value]
