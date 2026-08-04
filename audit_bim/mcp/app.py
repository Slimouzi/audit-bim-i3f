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

import os

from fastmcp import FastMCP

from .middleware import (
    ApiKeyMiddleware,
    ErrorMaskingMiddleware,
    SessionBindingMiddleware,
)
from .session import _State  # ré-export : conteneur d'état de session

__all__ = ["mcp", "_State", "register_all"]

mcp = FastMCP("audit-bim-i3f")
# Masquage d'erreurs en réseau (E10) en **premier** = enveloppe extérieure : il
# rattrape les exceptions non gérées de toute la chaîne. Puis isolation de session
# (bind ``_State`` au client MCP courant) et authentification optionnelle. En stdio,
# les trois sont des no-ops transparents.
mcp.add_middleware(ErrorMaskingMiddleware())
mcp.add_middleware(SessionBindingMiddleware())
mcp.add_middleware(ApiKeyMiddleware())

# Bootstrap des chemins par défaut depuis l'env : fait dans ``_Session.__init__``
# (cf. session.py) — chaque session HTTP repart avec les mêmes pointeurs CCH/annexes
# qu'en stdio.

_registered = False


def _legacy_aliases_enabled() -> bool:
    """Vrai si les **aliases métier LEGACY** doivent être enregistrés.

    Opt-in via ``AUDIT_BIM_ENABLE_LEGACY_ALIASES`` (``1`` / ``true`` / ``yes`` /
    ``on``, casse ignorée). Absent ou faux ⇒ ``aliases.py`` **n'est pas importé**
    (donc les 8 aliases ne sont pas enregistrés) : moins de bruit côté Claude/harness.
    """
    return os.getenv("AUDIT_BIM_ENABLE_LEGACY_ALIASES", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def register_all() -> FastMCP:
    """Importe (une seule fois) tous les modules de tools dans un **ordre déclaré**,
    déclenchant leurs décorateurs ``@mcp.tool`` sur l'instance partagée.

    Idempotente. Retourne l'instance ``mcp`` prête (tools **canoniques** + prompt).
    Ordre : modules de domaine d'abord (session/audit/reporting), puis actions/query.
    Les **aliases métier LEGACY** (re-dispatch vers ``tools_actions``) sont **opt-in**
    (cf. :func:`_legacy_aliases_enabled`) : par défaut ``aliases.py`` n'est pas importé.
    """
    global _registered
    if _registered:
        return mcp
    # Ces imports SONT l'enregistrement explicite (déclenchent les @mcp.tool).
    # Ordre déclaré : session/audit/reporting (domaine) → actions/query (lecture/
    # écriture) → server (prompt + compat).
    from ..profiles.i3f import (  # noqa: F401
        tools_actions,
        tools_audit,
        tools_query,
        tools_reporting,
        tools_session,
    )
    from . import server, tools_profiles  # noqa: F401

    # Aliases = compat LEGACY, **opt-in** par env : par défaut on ne les importe
    # pas → 8 tools de moins exposés par défaut. ``server`` n'importe plus
    # ``aliases`` au niveau module (ré-exports compat rendus lazy via PEP 562),
    # donc ce garde suffit à ne rien enregistrer quand le flag est absent/faux.
    if _legacy_aliases_enabled():
        from ..profiles.i3f import aliases  # noqa: F401

    _registered = True
    return mcp
