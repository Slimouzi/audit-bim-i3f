"""Profils clients/AMO composant les briques BIM génériques.

Le serveur actuel reste le MCP I3F. Ce package expose seulement une cartographie
stable des capacités réutilisables et des spécialisations client, pour préparer
les prochains MCP sans dupliquer la logique I3F.
"""

from .registry import (
    DEFAULT_PROFILE_ID,
    get_profile,
    list_generic_modules,
    list_profiles,
    profiles_payload,
)

__all__ = [
    "DEFAULT_PROFILE_ID",
    "get_profile",
    "list_generic_modules",
    "list_profiles",
    "profiles_payload",
]
