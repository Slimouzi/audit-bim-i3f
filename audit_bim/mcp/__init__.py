"""Serveur MCP FastMCP de l'audit BIM I3F.

``main``, ``mcp`` et ``register_all`` viennent tous de ``app`` — le module qui
tient l'instance et l'enregistrement.

L'``__init__`` importait auparavant ``main`` depuis ``server``, et devait le
faire **paresseusement** pour éviter un cycle. Ce détour a disparu avec sa
cause : ``server`` n'importe plus le profil au niveau module, et ``main`` a
rejoint ``app``. Le paquet ne charge donc plus jamais les ré-exports de compat
— importer ``audit_bim.mcp`` n'enregistre aucun outil client.
"""

from .app import main, mcp, register_all

__all__ = ["main", "mcp", "register_all"]
