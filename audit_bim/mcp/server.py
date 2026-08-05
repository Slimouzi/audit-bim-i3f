"""Serveur MCP « Audit BIM » — **point d'entrée et outils transverses**.

Ce module n'expose plus que trois noms :

- ``main`` — point d'entrée stdio, défini dans ``app`` ;
- ``mcp`` — l'instance partagée, définie dans ``app`` ;
- ``list_mcp_profiles`` — outil transverse du serveur, indépendant des profils.

Les outils vivent dans le **profil actif** (``audit_bim.profiles.<id>``) et dans
le socle partagé (``audit_bim.tools_shared``). L'enregistrement est piloté par
``McpProfile.tool_modules`` ; ce module n'y participe pas.

**Les ré-exports ``server.<tool>`` ont été retirés.** Ils permettaient
``from audit_bim.mcp import server; server.full_audit(...)`` du temps où tous
les outils vivaient ici. Trois lots ont vidé cette compat de sa substance :
E3-A lui a retiré le prompt, E3-B a migré tous les appelants, E4 a sorti
``main`` et rendu les ré-exports paresseux pour qu'un simple import cesse
d'enregistrer le profil I3F. Il ne restait qu'une surface que personne
n'empruntait — vérifiée par balayage sur les treize dépôts de l'écosystème — et
qu'un contrôle statique devait garder vide.

Les **aliases métier LEGACY** gardent leur compat, mais par un seul mécanisme :
``AUDIT_BIM_ENABLE_LEGACY_ALIASES`` (cf. ``app._legacy_aliases_enabled``), qui
les enregistre comme outils MCP. Les ré-exports Python correspondants
doublonnaient ce drapeau ; deux mécanismes pour une même compat, c'est un de
trop, et c'est toujours le moins visible qui survit à une suppression.

Le module reste importable — ``python -m audit_bim.mcp`` et un import direct de
``audit_bim.mcp.server`` doivent continuer de fonctionner sans rien enregistrer.
"""

from __future__ import annotations

from .app import main, mcp  # noqa: F401  (point d'entrée + instance partagée)
from .tools_profiles import list_mcp_profiles  # noqa: F401  (outil transverse)

__all__ = ["main", "mcp", "list_mcp_profiles"]
