"""Serveur MCP FastMCP de l'audit BIM I3F."""

from .app import mcp, register_all
from .server import main

__all__ = ["main", "mcp", "register_all"]
