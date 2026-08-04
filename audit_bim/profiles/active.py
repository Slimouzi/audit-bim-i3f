"""Profil actif du serveur — déclaré par l'environnement, I3F par défaut.

Un seul profil est actif par processus : c'est lui qui décide quels outils le
serveur enregistre et quel prompt il expose. Le choix est fait au démarrage, pas
par un outil MCP : un client ne doit pas pouvoir basculer le référentiel d'un
audit en cours d'échange.

**Un identifiant inconnu arrête le serveur.** Se rabattre silencieusement sur
I3F serait le pire comportement possible : un opérateur qui écrit
``AUDIT_BIM_PROFILE=bim-in-moton`` obtiendrait un serveur qui démarre, répond,
et imprime « CCH BIM I3F » dans le rapport d'un autre AMO. C'est exactement
l'accident que le registre de profils existe pour empêcher, et un repli par
défaut le rendrait indétectable.
"""

from __future__ import annotations

from bim_mcp_runtime import RuntimeConfig

from .models import McpProfile
from .registry import DEFAULT_PROFILE_ID, get_profile, list_profiles

#: Suffixe lu sous le préfixe ``AUDIT_BIM`` → ``AUDIT_BIM_PROFILE``.
ACTIVE_PROFILE_ENV_SUFFIX = "PROFILE"

_CONFIG = RuntimeConfig(env_prefix="AUDIT_BIM")

#: Nom complet de la variable, pour les messages et la documentation.
ACTIVE_PROFILE_ENV = _CONFIG.env_name(ACTIVE_PROFILE_ENV_SUFFIX)

__all__ = [
    "ACTIVE_PROFILE_ENV",
    "ACTIVE_PROFILE_ENV_SUFFIX",
    "UnknownProfileError",
    "active_profile_id",
    "resolve_active_profile",
]


class UnknownProfileError(ValueError):
    """L'identifiant demandé ne correspond à aucun profil déclaré."""


def active_profile_id(config: RuntimeConfig | None = None) -> str:
    """Identifiant du profil demandé, ou le défaut.

    La lecture est **paresseuse** : ``RuntimeConfig`` consulte ``os.environ`` à
    chaque appel. Figer la valeur à l'import ferait manquer une variable posée
    par un lanceur ou un superviseur après le chargement du module — le défaut
    exact que ``RuntimeConfig`` puis ``SessionStore`` ont dû corriger.
    """
    return (config or _CONFIG).get_str(ACTIVE_PROFILE_ENV_SUFFIX) or DEFAULT_PROFILE_ID


def resolve_active_profile(config: RuntimeConfig | None = None) -> McpProfile:
    """Profil actif. Lève :class:`UnknownProfileError` si l'identifiant est faux."""
    requested = active_profile_id(config)
    try:
        return get_profile(requested)
    except KeyError:
        known = ", ".join(p.id for p in list_profiles())
        raise UnknownProfileError(
            f"{ACTIVE_PROFILE_ENV}={requested!r} ne correspond à aucun profil "
            f"déclaré (connus : {known}). Le serveur ne démarre pas plutôt que "
            f"de servir le référentiel d'un autre client."
        ) from None
