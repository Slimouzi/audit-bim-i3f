"""Profil MCP « AMO BIM in Motion » — second consommateur, minimal.

Ce profil existe pour **prouver la frontière**, pas pour livrer une offre. Il
n'expose que ce qu'un AMO doit pouvoir faire avant toute spécialisation :
désigner une maquette, vérifier que c'est la bonne, en lire un instantané.

Il n'importe **rien** de ``audit_bim.profiles.i3f`` — ni module, ni constante,
ni texte — et ne recopie aucun de ses 45 outils. C'est la contrainte qui donne
sa valeur au profil : un socle partagé conçu sans second consommateur réel
resterait une hypothèse, et se révélerait faux au moment de l'utiliser.

Ce qu'il consomme sont les briques déjà neutres du dépôt : ``mcp.app``,
``mcp.session``, ``mcp.model_identity``, ``mcp.security`` et ``extraction``.
Ce que cette liste laisse voir — et ce qu'elle laisse encore de côté — est la
matière de l'inventaire à venir.
"""

from __future__ import annotations

__all__ = ["prompts", "tools_session"]
