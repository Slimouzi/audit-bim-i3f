"""Modèles décrivant les exigences extraites du cahier des charges I3F.

Vocabulaire CCH BIM I3F :
- *Objet* : entité métier (Projet, Site, Bâtiment, Étage, Zone, Pièce, Équipement…).
- *Classe IFC* : classe `Ifc*` correspondante (IfcProject, IfcSpace, …).
- *Pset* : property set IFC (Pset_SpaceCommon, Pset_3F…). Peut aussi être un
  attribut natif (`Name`, `LongName`, `ObjectType`, `Latitude`…).
- *Phase BIM* : niveau de livraison (APS, AVP, PRO, DCE, EXE, DOE, GESTION).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class BIMPhase(str, Enum):
    """Phase BIM du livrable, dans l'ordre du cycle projet I3F."""

    APS = "APS"
    AVP = "AVP"
    PRO = "PRO"
    DCE = "DCE"
    EXE = "EXE"
    DOE = "DOE"
    GESTION = "GESTION"

    @classmethod
    def ordered(cls) -> list[BIMPhase]:
        return [cls.APS, cls.AVP, cls.PRO, cls.DCE, cls.EXE, cls.DOE, cls.GESTION]


class PropertySpec(BaseModel):
    """Exigence sur une propriété (Pset ou attribut natif) d'un objet IFC.

    Une ligne de l'annexe « Spécification des données » → un PropertySpec.
    """

    theme: str = Field(..., description="Thème CCH (Générale, Cloisons, CVC…)")
    objet: str = Field(..., description="Libellé métier (Projet, Bâtiment, Zone…)")
    ifc_class: str = Field(..., description="Classe IFC (IfcProject, IfcSpace…)")
    property_name: str = Field(..., description="Nom de la propriété ou du document")
    pset_or_attribute: str | None = Field(
        None,
        description=(
            "Pset porteur (Pset_SpaceCommon…), nom d'attribut natif (Name, "
            "LongName, ObjectType…), ou nom de document attendu."
        ),
    )
    kind: str = Field(
        "property",
        description="property | document | quantity (BaseQuantities)",
    )
    required_phases: list[BIMPhase] = Field(
        default_factory=list,
        description="Phases BIM où la donnée est exigée.",
    )
    comment: str | None = None
    usage_3f: str | None = Field(
        None, description="Précision usage 3F (colonne O de l'annexe)."
    )
    ref_cch: str | None = Field(
        None, description="Référence CCH (ex: 'Chap 6.2')."
    )

    def required_at(self, phase: BIMPhase) -> bool:
        """Indique si l'exigence s'applique à la phase donnée."""
        return phase in self.required_phases


class NamingRule(BaseModel):
    """Règle de nommage pour un type d'objet IFC.

    Une règle peut combiner :
    - un *pattern* regex à respecter (ex: ``r"^[0-9]{4}[LP]$"`` pour le site),
    - une *liste fermée* de valeurs admises (ex: liste des noms d'étages).
    """

    objet: str
    ifc_class: str
    ifc_attribute: str = Field(
        ..., description="Attribut IFC ciblé (Name, LongName, ObjectType…)."
    )
    pattern: str | None = Field(
        None,
        description="Regex Python à respecter (None si pas de contrainte).",
    )
    allowed_values: list[str] = Field(
        default_factory=list,
        description="Liste fermée de valeurs admises (vide = liste ouverte).",
    )
    case_sensitive: bool = True
    max_length: int | None = None
    comment: str | None = None
    ref_cch: str | None = None


class RoomSpec(BaseModel):
    """Catalogue des noms de pièces I3F avec leur typologie et type de surface."""

    name: str = Field(..., description="Nom IfcSpace/LongName attendu (majuscules)")
    type_label: str | None = Field(None, description="Type de pièce (Chambre, Cuisine…)")
    localisation: str = Field("PP", description="PP (partie privative) | PC (partie commune)")
    surface_type: str | None = Field(None, description="SHAB | SU | autre")
    definition: str | None = None


class ZoneSpec(BaseModel):
    """Catalogue des noms et types de zones I3F."""

    name: str | None = Field(
        None, description="Nom typique (ex: 'XXXXL-YYYY', BUREAUX, COMMERCES…)"
    )
    type_label: str = Field(..., description="IfcZone/ObjectType attendu")
    localisation: str = Field("PP", description="PP | PC")
    definition: str | None = None


class StoreyName(BaseModel):
    """Élément de la liste des noms d'étages admis (REZ-DE-CHAUSSEE, 1ER ETAGE…)."""

    name: str
    pattern: str | None = None  # ex: TOITURE ([0-9]+)?


class RequirementsCatalog(BaseModel):
    """Agrégation de toutes les exigences MOA extraites des 3 documents."""

    cch_version: str | None = None
    cch_source_pdf: str | None = None
    data_spec_source: str | None = None
    naming_spec_source: str | None = None

    properties: list[PropertySpec] = Field(default_factory=list)
    naming_rules: list[NamingRule] = Field(default_factory=list)
    storey_names: list[StoreyName] = Field(default_factory=list)
    zone_specs: list[ZoneSpec] = Field(default_factory=list)
    room_specs: list[RoomSpec] = Field(default_factory=list)

    def properties_for(
        self, ifc_class: str, phase: BIMPhase
    ) -> list[PropertySpec]:
        """Renvoie les exigences applicables à une classe IFC à une phase donnée."""
        return [
            p
            for p in self.properties
            if p.ifc_class.lower() == ifc_class.lower() and p.required_at(phase)
        ]

    def naming_rule_for(
        self, ifc_class: str, attribute: str
    ) -> NamingRule | None:
        """Cherche la règle de nommage pour `(classe IFC, attribut)`."""
        for r in self.naming_rules:
            if (
                r.ifc_class.lower() == ifc_class.lower()
                and r.ifc_attribute.lower() == attribute.lower()
            ):
                return r
        return None

    def summary(self) -> dict:
        """Résumé compact pour exposition via le MCP."""
        themes = sorted({p.theme for p in self.properties if p.theme})
        ifc_classes = sorted({p.ifc_class for p in self.properties if p.ifc_class})
        return {
            "cch_version": self.cch_version,
            "n_properties": len(self.properties),
            "n_naming_rules": len(self.naming_rules),
            "n_storey_names": len(self.storey_names),
            "n_zone_specs": len(self.zone_specs),
            "n_room_specs": len(self.room_specs),
            "themes": themes,
            "ifc_classes_covered": ifc_classes,
        }
