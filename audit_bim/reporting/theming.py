"""Palette, typographie et styles communs aux livrables Word + xlsx.

La charte appliquée aux rapports d'audit est la **charte BIMData —
Brand Guidelines 2022 (v1.0)**. Les constantes sont exposées sous deux
jeux de noms :

- Constantes ``BIMDATA_*`` — **canoniques**, à utiliser pour tout
  nouveau code du module reporting.
- Alias historiques ``KORHUS_*`` et ``I3F_*`` — **dépréciés**, conservés
  pour compatibilité ascendante (intégrations externes). Ils pointent
  désormais sur les équivalents BIMData ; à supprimer à terme.

Attributs de marque BIMData (Simplicity / Modernity / Technology /
Scalable) : palette sobre, primaire bleu ardoise ``#2F374A`` et accent
jaune ``#F9C72C``, typographie Roboto / Arial.

Les couleurs de **sévérité** (feux tricolores) sont indépendantes de la
charte de marque : elles obéissent à une convention métier (rouge/orange/
vert) que la charte BIMData n'écrase pas — un bloc CRITICAL doit rester
rouge visible sur le rapport.
"""

from __future__ import annotations

# ── Palette BIMData (hex sans #) ──────────────────────────────────────
# Source : BIMData — Brand Guidelines 2022 v1.0.
# Source éditoriale complète (logo, typographie, mise en page, QA) :
#   audit_bim/reporting/BRAND_GUIDELINES.md
# Le code ne garde que les tokens exécutables — pas de duplication de la
# charte ; toute évolution de fond se fait d'abord dans BRAND_GUIDELINES.md.
#
# Primaires (cœur de l'identité de marque).
BIMDATA_PRIMARY = "2F374A"  # bleu ardoise : fonds sombres, titres, couverture
BIMDATA_SECONDARY = "F9C72C"  # jaune accent : filets, supertitles, mise en valeur
BIMDATA_ROYAL_BLUE = "3375DD"  # bleu royal : liens, accents secondaires
BIMDATA_WHITE = "FFFFFF"  # texte sur fond sombre, respiration
BIMDATA_GRANITE = "606060"  # texte secondaire, légendes
# Secondaires (mise en valeur, compléments du primaire).
BIMDATA_BLACK = "000000"  # texte strict (contraintes monochromes)
BIMDATA_GRANITE_LIGHT = "7A7A7A"  # texte secondaire clair
BIMDATA_SILVER_DARK = "BDBDBD"  # filets, bordures, séparateurs
BIMDATA_SILVER_LIGHT = "F7F7F7"  # fonds de page légers
BIMDATA_BLUE_NEUTRAL_LIGHT = "F0F5FF"  # fonds d'encadrés et tableaux
# Tertiaire dérivé : light slate lisible sur fond primaire sombre
# (sous-titres de couverture). Pas un token officiel mais cohérent.
BIMDATA_TERTIARY = "D6DEEB"
# États UI étendus (pour usage ponctuel / cohérence avec l'app web).
BIMDATA_HIGH = "FF3D1E"  # rouge vif
BIMDATA_WARNING = "FF9100"  # orange
BIMDATA_SUCCESS = "00AF50"  # vert

# Typographie BIMData — Roboto avec fallback Arial pour Word/Excel.
BIMDATA_FONT_PRIMARY = "Roboto"
BIMDATA_FONT_FALLBACK = "Arial"

# ── Alias dépréciés (rétro-compat) ───────────────────────────────────
# Anciennes chartes (Korhus.ai, I3F). Conservés le temps de migrer les
# intégrations externes ; ils résolvent vers les tokens BIMData.
KORHUS_PRIMARY = BIMDATA_PRIMARY
KORHUS_SECONDARY = BIMDATA_SECONDARY
KORHUS_TERTIARY = BIMDATA_TERTIARY
KORHUS_WHITE = BIMDATA_WHITE
KORHUS_GRANITE = BIMDATA_GRANITE
KORHUS_GRANITE_LIGHT = BIMDATA_GRANITE_LIGHT
KORHUS_SILVER_DARK = BIMDATA_SILVER_DARK
KORHUS_SILVER_LIGHT = BIMDATA_SILVER_LIGHT
KORHUS_BLUE_NEUTRAL_LIGHT = BIMDATA_BLUE_NEUTRAL_LIGHT
KORHUS_BLACK = BIMDATA_BLACK
KORHUS_FONT_PRIMARY = BIMDATA_FONT_PRIMARY
KORHUS_FONT_FALLBACK = BIMDATA_FONT_FALLBACK

I3F_BLUE = BIMDATA_PRIMARY
I3F_BLUE_LIGHT = BIMDATA_BLUE_NEUTRAL_LIGHT
I3F_GREY = BIMDATA_GRANITE
I3F_GREY_LIGHT = BIMDATA_SILVER_DARK
WHITE = BIMDATA_WHITE
BLACK = BIMDATA_BLACK

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

# Couleurs de thèmes (camemberts) — palette catégorielle alignée sur la
# charte BIMData (bleu royal, jaune secondaire, granite, états UI) tout
# en restant distinguables à l'œil.
THEME_COLORS = {
    "Hiérarchie spatiale": "3375DD",  # royal blue
    "Nommage Site / Bâtiment / Étage": "FF9100",  # warning orange
    "Nommage Zone": "F9C72C",  # secondary yellow
    "Nommage Pièce": "00AF50",  # success green
    "Propriété manquante": "7A4FBF",  # violet (distinction)
    "Propriété invalide": "FF3D1E",  # high red
    "Classification IFC": "2F374A",  # primary
    "Quantités (surfaces, volumes)": "2E9BD6",  # bleu clair
    "Document attendu": "7A7A7A",  # granite light
}
