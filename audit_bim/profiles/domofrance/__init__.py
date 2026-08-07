"""Profil Domofrance — inventaire du référentiel client et couverture mesurée.

Ce paquet porte la **logique** ; les scripts de ``scripts/`` n'en sont plus que
des points d'entrée CLI. Le déplacement est purement mécanique : mêmes
compteurs, mêmes rapports, mêmes tests.

Il précède l'ajout d'un profil MCP Domofrance. Tant que ce profil n'existe pas,
ce paquet n'expose **aucun outil** et n'est chargé par aucun profil : le
registre ne le mentionne pas, et la surface MCP est inchangée.

Deux modules :

- :mod:`~audit_bim.profiles.domofrance.controls` — décrit le classeur du maître
  d'ouvrage. Aucune maquette lue, aucun statut de conformité.
- :mod:`~audit_bim.profiles.domofrance.coverage` — croise ce classeur avec un
  document ``spatial_evidence/v1`` et dit ce qui **pourra être tranché**, jamais
  ce qui est conforme.
"""

from __future__ import annotations

__all__ = ["controls", "coverage"]
