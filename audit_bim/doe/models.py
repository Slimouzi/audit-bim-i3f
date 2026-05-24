"""Modèles de données de l'agent DOE → IFC.

DOE (Dossier des Ouvrages Exécutés) : ensemble des documents remis en fin
de chantier décrivant chaque équipement réellement installé. L'agent
convertit chaque ligne DOE en ``DoeRecord``, la rapproche d'un élément IFC
du modèle (``Match``), puis enrichit la maquette BIMData.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DoeRecord(BaseModel):
    """Un enregistrement DOE (une ligne tabulaire = un équipement).

    Sert de point pivot entre les extracteurs (Excel, PDF, GED) et le
    matcher. Au moins un des champs ``uuid_hint`` / ``tag_hint`` /
    ``name_hint`` doit être renseigné pour permettre un rapprochement IFC.

    Attributes:
        source: Chemin du fichier source (debug / traçabilité).
        row_index: Numéro de ligne (Excel) ou page (PDF), 1-indexé.
        uuid_hint: GlobalId IFC si déjà connu (matching exact, conf=1.0).
        tag_hint: Tag / Mark / numéro équipement (matching exact, conf=0.9).
        name_hint: Libellé équipement (matching fuzzy via rapidfuzz).
        type_hint: Type métier (« CTA », « Pompe », « Porte coupe-feu »)
            — filtre les candidats fuzzy.
        storey_hint: Étage de localisation (ex: ``"1ER ETAGE"``).
        zone_hint: Zone / local (ex: ``"7427L-1101"``).
        properties: Propriétés à appliquer, structurées par Pset.
        raw_row: Ligne brute du document (utile pour debug et reporting).
    """

    source: str = Field(..., description="Chemin du fichier source.")
    row_index: int = Field(..., description="Numéro de ligne (Excel) ou de page (PDF).")

    # Indices d'identification — au moins un de ces champs devrait être
    # renseigné pour permettre le matching.
    uuid_hint: str | None = Field(
        None, description="GlobalId IFC si déjà connu (matching exact)."
    )
    tag_hint: str | None = Field(
        None, description="Tag / Mark / numéro équipement (matching exact)."
    )
    name_hint: str | None = Field(
        None, description="Libellé équipement (matching fuzzy)."
    )
    type_hint: str | None = Field(
        None,
        description="Type métier (« CTA », « Pompe », « Porte coupe-feu »).",
    )
    storey_hint: str | None = Field(
        None, description="Étage de localisation (ex: « 1ER ETAGE »)."
    )
    zone_hint: str | None = Field(
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
    """Résultat du rapprochement d'un ``DoeRecord`` à un élément IFC.

    Si ``ifc_uuid`` est ``None``, le record n'a pas pu être rapproché —
    soit aucun candidat trouvé (``reason`` documente la cause), soit
    ambiguïté (``candidates`` liste les pistes pour décision humaine).

    Attributes:
        record: Le DoeRecord d'origine (référence forte).
        ifc_uuid: GlobalId IFC matché. ``None`` si aucun match retenu.
        ifc_type: Classe IFC du match (ex: ``"IfcWallStandardCase"``).
        ifc_name: Nom IFC du match (debug / reporting).
        confidence: Score 0..1 du match. 1.0 = GUID exact, 0.9 = tag,
            0.75–1.0 = nom fuzzy, 0.55 = localisation seule.
        strategy: Stratégie ayant produit le match (``"guid"`` /
            ``"tag"`` / ``"name"`` / ``"localisation"``).
        candidates: Pistes alternatives (en cas d'ambiguïté tag par
            exemple). Format ``[{uuid, type, name, score}]``.
        reason: Explication du non-match (None si match réussi).
    """

    record: DoeRecord
    ifc_uuid: str | None = Field(
        None, description="UUID IFC matché (None si pas de match retenu)."
    )
    ifc_type: str | None = None
    ifc_name: str | None = None
    confidence: float = Field(
        0.0, description="Confiance du matching (0..1)."
    )
    strategy: str | None = Field(
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
    reason: str | None = Field(
        None, description="Raison du non-match si ``ifc_uuid`` est None."
    )

    def is_matched(self) -> bool:
        """Indique si le record a été rapproché à un élément IFC.

        Returns:
            True si ``ifc_uuid`` est défini (donc enrichissement
            possible). False si non match ou ambiguïté non levée.
        """
        return self.ifc_uuid is not None
