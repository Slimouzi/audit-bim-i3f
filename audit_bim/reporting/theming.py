"""Palette et styles communs aux livrables Word + xlsx (look pro AMO BIM)."""
from __future__ import annotations

# Palette (hex sans #)
I3F_BLUE = "1F4E79"      # bleu principal (titres, bandeaux)
I3F_BLUE_LIGHT = "D9E2F3"  # fond clair (tableaux header alterné)
I3F_GREY = "404040"      # texte principal
I3F_GREY_LIGHT = "BFBFBF"  # bordures
WHITE = "FFFFFF"
BLACK = "000000"

SEVERITY_COLORS = {
    "CRITICAL": "B22222",
    "HIGH": "D2691E",
    "MEDIUM": "DAA520",
    "LOW": "6B8E23",
    "INFO": "4682B4",
}

THEME_COLORS = {
    "Hiérarchie spatiale": "5B9BD5",
    "Nommage Site / Bâtiment / Étage": "ED7D31",
    "Nommage Zone": "FFC000",
    "Nommage Pièce": "70AD47",
    "Propriété manquante": "7030A0",
    "Propriété invalide": "C00000",
    "Classification IFC": "264478",
    "Quantités (surfaces, volumes)": "2E75B6",
    "Document attendu": "A5A5A5",
}
