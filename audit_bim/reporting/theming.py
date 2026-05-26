"""Palette, typographie et styles communs aux livrables Word + xlsx.

La charte appliquée aux rapports d'audit est la **charte Korhus.ai
2025 v1.0** (cf. ``/Users/stani/code/MCP/korhus_brand_kit``). Les
constantes sont exposées sous deux jeux de noms :

- Constantes ``KORHUS_*`` — noms brand-neutres pour les usages internes
  du module reporting.
- Alias historiques ``I3F_*`` — conservés pour compatibilité ascendante
  (tests, intégrations externes). Ils pointent désormais sur les
  équivalents Korhus.

Les couleurs de **sévérité** (feux tricolores) sont indépendantes de la
charte de marque : elles obéissent à une convention métier (rouge/orange/
vert) que la charte Korhus n'écrase pas — un bloc CRITICAL doit rester
rouge visible sur le rapport, même en mode brand sombre.
"""

from __future__ import annotations

# ── Palette Korhus.ai (hex sans #) ────────────────────────────────────
# Source : Brand Guidelines 2025 v1.0 (korhus_brand_tokens.json).
KORHUS_PRIMARY = "0C101B"  # fonds sombres, titres forts, page de couverture
KORHUS_SECONDARY = "59F4FF"  # accent technologique (cyan), filets, CTA
KORHUS_TERTIARY = "D1D8ED"  # fonds doux, aplats secondaires
KORHUS_WHITE = "FFFFFF"  # texte sur fond sombre, respiration
KORHUS_GRANITE = "606060"  # texte secondaire, légendes
KORHUS_GRANITE_LIGHT = "7A7A7A"  # texte secondaire clair
KORHUS_SILVER_DARK = "BDBDBD"  # filets, bordures, séparateurs
KORHUS_SILVER_LIGHT = "F7F7F7"  # fonds de page légers
KORHUS_BLUE_NEUTRAL_LIGHT = "F0F5FF"  # fonds d'encadrés et tableaux
KORHUS_BLACK = "000000"  # texte strict (contraintes monochromes)

# Typographie Korhus — Roboto avec fallback Arial pour Word/Excel.
KORHUS_FONT_PRIMARY = "Roboto"
KORHUS_FONT_FALLBACK = "Arial"

# ── Alias historiques (rétro-compat) ─────────────────────────────────
# Les anciens templates utilisaient ``I3F_BLUE`` comme couleur de
# titres/bandeaux ; on l'aligne sur ``KORHUS_PRIMARY`` (le sombre) pour
# garder la même intention sémantique (« couleur forte de marque »).
I3F_BLUE = KORHUS_PRIMARY  # ex 1F4E79 → 0C101B
I3F_BLUE_LIGHT = KORHUS_BLUE_NEUTRAL_LIGHT  # ex D9E2F3 → F0F5FF
I3F_GREY = KORHUS_GRANITE  # ex 404040 → 606060
I3F_GREY_LIGHT = KORHUS_SILVER_DARK  # ex BFBFBF → BDBDBD
WHITE = KORHUS_WHITE
BLACK = KORHUS_BLACK

# Palette feux tricolores standard (single source of truth — voir aussi
# audit_bim.audit.findings.severity_color qui ré-exporte ces valeurs).
# Indépendant de la charte de marque (convention métier prime).
SEVERITY_COLORS = {
    "CRITICAL": "8B0000",  # rouge très foncé (dark red)
    "HIGH": "DC3545",  # rouge
    "MEDIUM": "FF8C00",  # orange (dark orange)
    "LOW": "28A745",  # vert
    "INFO": "4682B4",  # bleu (steel blue) — pas de gravité
}

# Couleurs de thèmes (camemberts) — adoucies pour s'intégrer à la charte
# Korhus (palette tech sobre) tout en restant distinguables à l'œil.
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
