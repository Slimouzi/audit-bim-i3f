"""Modèles de données de l'agent DOE → IFC.

DOE (Dossier des Ouvrages Exécutés) : ensemble des documents remis en fin
de chantier décrivant chaque équipement réellement installé. L'agent
convertit chaque ligne DOE en ``DoeRecord``, la rapproche d'un élément IFC
du modèle (``Match``), puis enrichit la maquette BIMData.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class DoeRecord(BaseModel):
    """Un enregistrement DOE (typiquement une ligne d'un tableau Excel ou
    PDF) décrivant un équipement avec ses propriétés.
    """

    source: str = Field(..., description="Chemin du fichier source.")
    row_index: int = Field(..., description="Numéro de ligne (Excel) ou de page (PDF).")

    # Indices d'identification — au moins un de ces champs devrait être
    # renseigné pour permettre le matching.
    uuid_hint: Optional[str] = Field(
        None, description="GlobalId IFC si déjà connu (matching exact)."
    )
    tag_hint: Optional[str] = Field(
        None, description="Tag / Mark / numéro équipement (matching exact)."
    )
    name_hint: Optional[str] = Field(
        None, description="Libellé équipement (matching fuzzy)."
    )
    type_hint: Optional[str] = Field(
        None,
        description="Type métier (« CTA », « Pompe », « Porte coupe-feu »).",
    )
    storey_hint: Optional[str] = Field(
        None, description="Étage de localisation (ex: « 1ER ETAGE »)."
    )
    zone_hint: Optional[str] = Field(
        None, description="Zone / local de localisation (ex: « 7427L-1101 »)."
    )

    # Propriétés à appliquer
    properties: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Propriétés organisées par Pset : "
            "``{'Pset_3F': {'Fabricant': 'BOSCH', 'Reference': 'X42'}}``."
        ),
    )

    raw_row: dict = Field(
        default_factory=dict,
        description="Ligne brute du document source (debug).",
    )


class Match(BaseModel):
    """Résultat du matching d'un ``DoeRecord`` à un élément IFC."""

    record: DoeRecord
    ifc_uuid: Optional[str] = Field(
        None, description="UUID IFC matché (None si pas de match retenu)."
    )
    ifc_type: Optional[str] = None
    ifc_name: Optional[str] = None
    confidence: float = Field(
        0.0, description="Confiance du matching (0..1)."
    )
    strategy: Optional[str] = Field(
        None,
        description="Stratégie qui a fait le match : guid / tag / name / localisation.",
    )
    candidates: list[dict] = Field(
        default_factory=list,
        description=(
            "Liste des autres candidats plausibles (en cas d'ambiguïté). "
            "Chaque entrée : ``{uuid, type, name, score}``."
        ),
    )
    reason: Optional[str] = Field(
        None, description="Raison du non-match si ``ifc_uuid`` est None."
    )

    def is_matched(self) -> bool:
        return self.ifc_uuid is not None
