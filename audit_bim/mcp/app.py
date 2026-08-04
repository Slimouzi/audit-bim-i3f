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
from importlib import import_module

from fastmcp import FastMCP

from ..profiles.active import resolve_active_profile
from .middleware import (
    ApiKeyMiddleware,
    ErrorMaskingMiddleware,
    SessionBindingMiddleware,
)
from .session import _State  # ré-export : conteneur d'état de session

__all__ = ["mcp", "_State", "main", "register_all", "registered_profile_id"]

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
_registered_profile_id: str | None = None


def registered_profile_id() -> str | None:
    """Identifiant du profil effectivement enregistré, ou ``None`` avant appel.

    Sert au diagnostic : un serveur qui expose des outils inattendus doit
    pouvoir dire sous quel profil il a démarré.
    """
    return _registered_profile_id


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
    """Enregistre les outils du **profil actif** sur l'instance partagée.

    Les modules à importer ne sont plus écrits ici : ils sont déclarés par le
    profil (``McpProfile.tool_modules``), dans l'ordre historique. Le serveur
    n'enregistre en propre que ses outils transverses — ``tools_profiles``.

    Idempotente. Retourne l'instance ``mcp`` prête (tools **canoniques** +
    prompt du profil). Les **aliases métier LEGACY** restent **opt-in**
    (cf. :func:`_legacy_aliases_enabled`).

    Il n'y a **pas** de bascule de profil à chaud : FastMCP refuse un nom déjà
    pris, et un serveur qui changerait de référentiel en cours de session
    servirait deux réponses incohérentes au même client. Le profil se choisit
    au démarrage ; pour en essayer un autre, on relance le processus (c'est
    aussi ce que font les tests, en sous-processus frais).
    """
    global _registered, _registered_profile_id
    if _registered:
        return mcp

    profile = resolve_active_profile()

    # Ces imports SONT l'enregistrement (ils déclenchent les ``@mcp.tool``).
    # ``server`` n'est délibérément PAS importé ici : il ré-exporte tout le
    # profil I3F au niveau module, donc l'importer réenregistrerait les outils
    # d'I3F quel que soit le profil actif — la sélection n'aurait aucun effet.
    # Il ne déclare plus rien depuis E3-A ; son import était devenu inerte.
    for module_path in profile.tool_modules:
        import_module(module_path)

    from . import tools_profiles  # noqa: F401  (outils transverses du serveur)

    # Prompts du profil actif : déclaration explicite, pas effet de bord
    # d'import. C'est le point par lequel un autre profil enregistre les siens.
    if profile.prompt_module:
        import_module(profile.prompt_module).register_prompts(mcp)

    if profile.legacy_alias_module and _legacy_aliases_enabled():
        import_module(profile.legacy_alias_module)

    _registered = True
    _registered_profile_id = profile.id
    return mcp


def main() -> None:
    """Point d'entrée stdio simple : enregistre le profil actif, puis sert.

    Vivait dans ``server.py``. L'y laisser obligeait le paquet à importer
    ``server`` pour exposer ``main`` — donc à charger ses ré-exports, donc à
    enregistrer le profil I3F avant même le choix du profil actif. Le point
    d'entrée appartient au module qui tient l'instance, pas au module de compat.

    L'exécutable ``audit-bim-mcp`` passe, lui, par ``__main__.main`` (argparse,
    transports réseau, garde-fous de démarrage).
    """
    register_all()
    mcp.run()
