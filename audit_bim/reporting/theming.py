"""Charte des livrables : tokens BIMData (socle) + cartes métier (ici).

La **charte de marque** — palette et typographie — vit désormais dans le socle
générique ``bim_reporting.theming`` et n'est que ré-exportée ici, sous les mêmes
noms, pour ne réécrire aucun call-site.

Ce qui **reste dans ce dépôt**, et pourquoi :

- ``SEVERITY_COLORS`` — feux tricolores indexés par l'enum ``Severity``. Ré-export
  depuis ``audit_bim.audit.findings`` (single source of truth) ; convention
  métier, pas charte de marque. Un bloc CRITICAL doit rester rouge visible même
  si la charte évolue.
- ``THEME_COLORS`` — palette catégorielle indexée par les thèmes d'audit.

Les figer dans le socle obligerait un futur MCP à hériter des énumérés d'un
autre ; les fonctions du socle qui en ont besoin les reçoivent en paramètre
(``bim_reporting.excel.build_formats(wb, severity_colors=…)``,
``bim_reporting.charts.pie_chart(values, colors_map, …)``).

Les alias historiques ``KORHUS_*`` / ``I3F_*`` restent ici : ils portent du
vocabulaire client, qui n'a rien à faire dans un package partagé.
"""

from __future__ import annotations

# Tokens de marque — implémentation dans le socle générique ``bim-reporting``.
# Source éditoriale complète (logo, typographie, mise en page, QA) :
#   audit_bim/reporting/BRAND_GUIDELINES.md
# Le socle ne porte que les tokens exécutables ; toute évolution de fond se fait
# d'abord dans BRAND_GUIDELINES.md, qui reste la charte de référence.
from bim_reporting.theming import (  # noqa: F401  (ré-exports)
    BIMDATA_BLACK,
    BIMDATA_BLUE_NEUTRAL_LIGHT,
    BIMDATA_FONT_FALLBACK,
    BIMDATA_FONT_PRIMARY,
    BIMDATA_GRANITE,
    BIMDATA_GRANITE_LIGHT,
    BIMDATA_HIGH,
    BIMDATA_PRIMARY,
    BIMDATA_ROYAL_BLUE,
    BIMDATA_SECONDARY,
    BIMDATA_SILVER_DARK,
    BIMDATA_SILVER_LIGHT,
    BIMDATA_SUCCESS,
    BIMDATA_TERTIARY,
    BIMDATA_WARNING,
    BIMDATA_WHITE,
)

# Palette feux tricolores : convention métier attachée à l'enum ``Severity``,
# hébergée dans ``audit_bim.audit.findings`` (single source of truth). Ré-export
# ici (import descendant reporting → audit, légal) pour que word_report /
# xlsx_annex / avp_i3f l'importent depuis theming sans changement — sans recréer
# le cycle audit ↔ reporting.
from ..audit.findings import SEVERITY_COLORS  # noqa: F401  (ré-export)

# ── Alias dépréciés (rétro-compat, fenêtre de migration) ─────────────
# Anciennes chartes (Korhus.ai, I3F) résolues vers les tokens BIMData.
# Réduits en audit v0.8 aux 6 alias encore référencés (les 12 autres
# n'avaient plus aucun consommateur, tests compris) ; retrait complet
# planifié à la prochaine version majeure. Ils portent du vocabulaire
# client : ils restent donc ici, jamais dans le socle partagé.
KORHUS_PRIMARY = BIMDATA_PRIMARY
KORHUS_SECONDARY = BIMDATA_SECONDARY
KORHUS_FONT_PRIMARY = BIMDATA_FONT_PRIMARY

I3F_BLUE = BIMDATA_PRIMARY
I3F_BLUE_LIGHT = BIMDATA_BLUE_NEUTRAL_LIGHT
I3F_GREY = BIMDATA_GRANITE

# Couleurs de thèmes (camemberts) — palette catégorielle alignée sur la
# charte BIMData (bleu royal, jaune secondaire, granite, états UI) tout
# en restant distinguables à l'œil. Indexée par les thèmes d'audit : reste
# ici, le socle ne connaît pas ces énumérés.
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
    "Cohérence géométrique": "C2185B",  # magenta (audit préliminaire clash)
}
