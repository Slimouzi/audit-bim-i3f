"""Outils MCP partagés entre profils — aucun référentiel client.

Ce paquet ne contient que ce dont l'inventaire (`docs/scope-shared-tools.md`)
a prouvé la neutralité par analyse de dépendances, **et** qu'un second profil
réclamait réellement. Un outil qu'aucun autre appelant ne demande n'y entre
pas : ce serait parier sur son usage.
"""

from __future__ import annotations

__all__ = ["session"]
