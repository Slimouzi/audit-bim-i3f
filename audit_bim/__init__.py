"""Audit BIM conforme au Cahier des Charges BIM I3F (CCH V3.x).

Package exposant :

- les *parseurs* des documents MOA (PDF + xlsx) → catalogue d'exigences,
- l'*extracteur* du modèle IFC depuis BIMData (auth OAuth2/API-Key),
- le *moteur d'audit* (nommage, propriétés, classifications, hiérarchie),
- les *reporters* Word + XLSX livrables,
- le builder de *Smart Views* BIMData,
- un serveur *MCP* (FastMCP) pour piloter le tout depuis Claude.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# Source unique de vérité : la version est lue depuis les métadonnées
# du package installé (cf. ``pyproject.toml``). Évite la dérive
# historique entre ``__init__.py`` (hardcodé "0.1.0" depuis l'origine
# du projet) et ``pyproject.toml`` (bumpé à chaque release).
try:
    __version__ = _pkg_version("audit-bim-i3f")
except PackageNotFoundError:
    # Lecture du source sans ``pip install`` (CI exotique, archive
    # zip). On signale explicitement plutôt que de mentir avec une
    # vieille valeur.
    __version__ = "0.0.0+unknown"

del _pkg_version, PackageNotFoundError
