"""Tools MCP — profils clients/AMO et découpage générique."""

from __future__ import annotations

from ..profiles import profiles_payload
from .app import mcp


@mcp.tool()
def list_mcp_profiles(profile_id: str | None = None) -> dict:
    """Liste les profils MCP client/AMO et les briques génériques réutilisables.

    Ce tool est purement déclaratif : il ne change pas le profil actif, ne
    modifie pas la session et ne déclenche aucun calcul. I3F reste le profil par
    défaut ; ``bim_in_motion`` est exposé comme cible de préparation du prochain
    MCP, sans activer de comportement I3F par accident.
    """
    try:
        return profiles_payload(profile_id)
    except KeyError:
        return {
            "status": "error",
            "error": "unknown_profile",
            "profile_id": profile_id,
            "available_profile_ids": [p["id"] for p in profiles_payload()["profiles"]],
        }
