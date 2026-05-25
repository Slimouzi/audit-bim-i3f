"""Briques de sécurité du serveur MCP audit-bim-i3f.

Trois axes :

1. **Auth applicative** pour les transports HTTP / SSE / streamable-http.
   La clé service ``AUDIT_BIM_API_KEY`` doit être présentée dans le
   header ``X-API-Key`` (ou dans la query string ``?api_key=...``
   pour les clients SSE qui ne peuvent pas customiser les headers).
   Comparaison à temps constant. En mode ``stdio``, la garde est
   désactivée (le canal IPC est implicitement de confiance).

2. **Fail-fast au démarrage** : un serveur prod qui démarre en HTTP
   *sans* clé service est presque toujours une erreur de configuration.
   :func:`assert_startup_config` lève ``RuntimeError`` quand :

   - transport ≠ stdio ET ``AUDIT_BIM_REQUIRE_API_KEY=true`` (ou
     ``AUDIT_BIM_ENV=production``) ET la clé n'est pas définie ;
   - host = ``0.0.0.0`` sans ``AUDIT_BIM_ENV=production``.

3. **Politique d'écriture** : ``AUDIT_BIM_ALLOW_WRITES`` (défaut
   ``false`` en HTTP, ``true`` en stdio) gouverne tous les tools
   mutatifs côté BIMData (apply_classifications, doe_enrich,
   create_bcf_topics, create_smart_views, full_audit avec push).
   :func:`ensure_writes_allowed` est appelée par chaque tool mutatif
   avant d'effectuer un changement distant.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets

logger = logging.getLogger("audit_bim.mcp.security")

API_KEY_ENV = "AUDIT_BIM_API_KEY"
REQUIRE_API_KEY_ENV = "AUDIT_BIM_REQUIRE_API_KEY"
ENV_NAME_ENV = "AUDIT_BIM_ENV"
ALLOW_WRITES_ENV = "AUDIT_BIM_ALLOW_WRITES"


# ── Politique : prod vs dev ──────────────────────────────────────────────


def _is_truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def is_prod() -> bool:
    """Mode production explicite (``AUDIT_BIM_ENV=production`` ou ``prod``)."""
    return (os.getenv(ENV_NAME_ENV) or "").strip().lower() in ("production", "prod")


def is_api_key_required() -> bool:
    """``True`` si la clé service est obligatoire (flag explicite ou prod)."""
    return _is_truthy(os.getenv(REQUIRE_API_KEY_ENV)) or is_prod()


def is_write_allowed() -> bool:
    """Indique si les tools mutatifs peuvent toucher à BIMData.

    Par défaut, on lit ``AUDIT_BIM_ALLOW_WRITES`` :

    - défini → cette valeur (``true`` / ``false``).
    - non défini → ``True`` (mode dev / Claude Desktop local).

    Pour un déploiement HTTP exposé, mettre explicitement
    ``AUDIT_BIM_ALLOW_WRITES=false`` puis ne re-permettre les push
    qu'au besoin et de manière scopée.
    """
    raw = os.getenv(ALLOW_WRITES_ENV)
    if raw is None:
        return True
    return _is_truthy(raw)


class WritesDisabledError(PermissionError):
    """Levée par un tool mutatif quand ``AUDIT_BIM_ALLOW_WRITES=false``."""


def ensure_writes_allowed(action: str) -> None:
    """À appeler par les tools mutatifs avant tout side-effect distant.

    Args:
        action: Nom court de l'opération (pour les logs).

    Raises:
        WritesDisabledError: Si la politique courante interdit les
            écritures BIMData.
    """
    if not is_write_allowed():
        logger.warning("write blocked action=%s reason=AUDIT_BIM_ALLOW_WRITES=false", action)
        raise WritesDisabledError(
            f"Écritures BIMData désactivées (AUDIT_BIM_ALLOW_WRITES=false). "
            f"Action refusée : {action}. Pour autoriser, démarrer le serveur "
            f"avec AUDIT_BIM_ALLOW_WRITES=true (déconseillé en HTTP exposé)."
        )


# ── Démarrage : fail-fast ────────────────────────────────────────────────


def assert_startup_config(*, transport: str, host: str | None = None) -> None:
    """Valide la configuration au démarrage du serveur MCP.

    Args:
        transport: ``stdio`` / ``http`` / ``sse`` / ``streamable-http``.
        host: Hôte d'écoute (pertinent pour HTTP/SSE).

    Raises:
        RuntimeError: Configuration prod incomplète ou risquée.
    """
    if transport == "stdio":
        # stdio ne s'expose pas au réseau : aucune contrainte
        return

    # Transports réseau : ré-évaluer la politique.
    if is_api_key_required() and not os.getenv(API_KEY_ENV):
        raise RuntimeError(
            "Transport réseau activé en mode production "
            "(AUDIT_BIM_REQUIRE_API_KEY=true ou AUDIT_BIM_ENV=production) "
            "mais AUDIT_BIM_API_KEY n'est pas défini — refus de démarrer."
        )

    if host == "0.0.0.0" and not is_prod():
        raise RuntimeError(
            "Refus de bind 0.0.0.0 sans AUDIT_BIM_ENV=production. "
            "Pour exposer le serveur publiquement, définir explicitement "
            "AUDIT_BIM_ENV=production (et configurer AUDIT_BIM_API_KEY, "
            "AUDIT_BIM_ALLOW_WRITES selon le besoin)."
        )

    # Warnings utiles
    if not os.getenv(API_KEY_ENV):
        logger.warning(
            "AUDIT_BIM_API_KEY non défini — transport %s ouvert sans clé service. "
            "À ne pas exposer hors réseau de confiance.",
            transport,
        )
    if is_write_allowed():
        logger.warning(
            "AUDIT_BIM_ALLOW_WRITES non restreint en transport %s — les tools "
            "mutatifs (apply_classifications, doe_enrich, create_bcf_topics, "
            "create_smart_views, full_audit avec push) peuvent toucher BIMData.",
            transport,
        )


# ── Auth helpers : vérification de la clé service ────────────────────────


def verify_api_key(provided: str | None) -> bool:
    """Compare en temps constant ``provided`` avec ``AUDIT_BIM_API_KEY``.

    - Si la variable d'env n'est pas définie → ``True`` (garde
      désactivée). C'est le mode dev / stdio.
    - Sinon → vrai uniquement si ``provided`` correspond exactement.
    """
    expected = os.getenv(API_KEY_ENV)
    if not expected:
        return True
    if not provided:
        return False
    return secrets.compare_digest(provided, expected)


def scrub(token: str | None) -> str:
    """Identifiant court non-réversible d'un token, pour la corrélation logs."""
    if not token:
        return "<none>"
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
