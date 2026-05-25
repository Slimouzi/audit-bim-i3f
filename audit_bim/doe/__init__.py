"""Agent DOE → IFC.

Extrait des données de Dossier des Ouvrages Exécutés (Excel, PDF natif,
PDF scanné via OCR Tesseract), les rapproche d'éléments IFC du modèle
BIMData via 4 stratégies en cascade (GUID, Tag, Nom fuzzy,
Localisation), et enrichit la maquette avec les propriétés extraites.
"""

from .address import extract_address_from_doe, extract_address_from_text
from .conflicts import (
    ConflictReport,
    ConflictType,
    classify_conflict,
    detect_conflicts,
    summarize_conflicts,
)
from .enricher import apply_matches_to_model
from .extractors import parse_doe, parse_doe_excel, parse_doe_pdf
from .matcher import match_doe_records
from .models import DoeRecord, Match
from .reporter import summarize_matches

__all__ = [
    "ConflictReport",
    "ConflictType",
    "DoeRecord",
    "Match",
    "apply_matches_to_model",
    "classify_conflict",
    "detect_conflicts",
    "extract_address_from_doe",
    "extract_address_from_text",
    "match_doe_records",
    "parse_doe",
    "parse_doe_excel",
    "parse_doe_pdf",
    "summarize_conflicts",
    "summarize_matches",
]
