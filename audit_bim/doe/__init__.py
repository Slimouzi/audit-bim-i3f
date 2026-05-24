"""Agent DOE → IFC.

Extrait des données de Dossier des Ouvrages Exécutés (Excel pour V1, PDF/OCR
à venir), les rapproche d'éléments IFC du modèle BIMData via 4 stratégies
en cascade (GUID, Tag, Nom fuzzy, Localisation), et enrichit la maquette
avec les propriétés extraites.
"""

from .enricher import apply_matches_to_model
from .extractors.excel import parse_doe_excel
from .matcher import match_doe_records
from .models import DoeRecord, Match
from .reporter import summarize_matches

__all__ = [
    "DoeRecord",
    "Match",
    "apply_matches_to_model",
    "match_doe_records",
    "parse_doe_excel",
    "summarize_matches",
]
