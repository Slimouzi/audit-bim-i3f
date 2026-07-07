"""Instance MCP + middleware + état de session — **socle sans tools**.

Ce module ne contient **aucun** ``@mcp.tool`` : il n'importe donc aucun module de
tools et ne crée aucun cycle. Tous les modules de tools importent l'instance
partagée via ``from .app import mcp`` (au lieu de l'ancien ``from .server import
mcp``, dont l'ordre d'import était porteur et invisible).

L'enregistrement des tools est **explicite** : cf. :func:`register_all` — appelée
par ``__main__`` et par la fixture de tests, elle importe les modules de tools dans
un ordre déclaré. Plus aucun import à effet de bord en fin de ``server.py`` ni de
``noqa: E402``.
"""

from __future__ import annotations

from fastmcp import FastMCP

from .middleware import ApiKeyMiddleware, SessionBindingMiddleware
from .session import _State  # ré-export : conteneur d'état de session

__all__ = ["mcp", "_State", "register_all"]

mcp = FastMCP("audit-bim-i3f")
# Middleware d'isolation de session (bind ``_State`` au client MCP courant) et
# d'authentification optionnelle. En stdio, les deux sont des no-ops transparents.
mcp.add_middleware(SessionBindingMiddleware())
mcp.add_middleware(ApiKeyMiddleware())

# Bootstrap des chemins par défaut depuis l'env : fait dans ``_Session.__init__``
# (cf. session.py) — chaque session HTTP repart avec les mêmes pointeurs CCH/annexes
# qu'en stdio.

_registered = False


def register_all() -> FastMCP:
    """Importe (une seule fois) tous les modules de tools dans un **ordre déclaré**,
    déclenchant leurs décorateurs ``@mcp.tool`` sur l'instance partagée.

    Idempotente. Retourne l'instance ``mcp`` prête (49 tools + prompt). Ordre :
    modules de domaine d'abord (session/audit/reporting), puis actions/query, puis
    aliases (qui re-dispatchent vers ``tools_actions``)."""
    global _registered
    if _registered:
        return mcp
    # Ces imports SONT l'enregistrement explicite (déclenchent les @mcp.tool).
    from . import (  # noqa: F401
        aliases,
        server,
        tools_actions,
        tools_query,
    )

    _registered = True
    return mcp
