"""Façade web légère « MCP Client Setup » (page ``/mcp-setup`` + API REST).

Cette couche **ne contient aucun workflow d'audit** : elle prépare un
contexte sécurisé (credentials BIMData → session crédentialée tokenisée),
après quoi le client pilote l'audit uniquement via l'IA/MCP.
"""

from __future__ import annotations

from .setup import register_setup_routes

__all__ = ["register_setup_routes"]
