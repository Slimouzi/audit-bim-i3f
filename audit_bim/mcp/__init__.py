"""Serveur MCP FastMCP de l'audit BIM I3F.

``main`` est exposé **paresseusement** (PEP 562). Depuis E2, ``server`` importe
les outils du profil (``audit_bim.profiles.i3f``) ; les tirer ici créerait un
cycle : importer un module du profil initialise d'abord ``audit_bim.mcp``, dont
l'``__init__`` importerait ``server``, qui réimporterait le module en cours.

Le cycle ne se manifeste que si le profil est importé **en premier** — donc pas
en suite complète, où un autre test a déjà chargé ``audit_bim.mcp``. Il est
couvert par un test qui démarre un interpréteur neuf.

``mcp`` et ``register_all`` restent immédiats : ``app`` n'importe le profil
qu'à l'intérieur de ``register_all``, pas au niveau module.
"""

from .app import mcp, register_all

__all__ = ["main", "mcp", "register_all"]


def __getattr__(name: str):
    """Import paresseux de ``main`` (PEP 562) — cf. docstring du module."""
    if name == "main":
        from .server import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
