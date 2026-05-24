"""Audit BIM conforme au Cahier des Charges BIM I3F (CCH V3.x).

Package exposant :

- les *parseurs* des documents MOA (PDF + xlsx) → catalogue d'exigences,
- l'*extracteur* du modèle IFC depuis BIMData (auth OAuth2/API-Key),
- le *moteur d'audit* (nommage, propriétés, classifications, hiérarchie),
- les *reporters* Word + XLSX livrables,
- le builder de *Smart Views* BIMData,
- un serveur *MCP* (FastMCP) pour piloter le tout depuis Claude.
"""

__version__ = "0.1.0"
