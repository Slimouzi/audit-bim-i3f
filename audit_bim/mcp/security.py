"""Briques de sécurité du serveur MCP audit-bim-i3f.

Trois axes :

1. **Auth applicative** pour les transports HTTP / SSE / streamable-http.
   La clé service ``AUDIT_BIM_API_KEY`` doit être présentée dans le
   header ``X-API-Key``. Comparaison à temps constant. En mode
   ``stdio``, la garde est désactivée (le canal IPC est implicitement
   de confiance). On n'expose **pas** la clé via query string — les
   secrets ne doivent pas finir dans les access logs / l'historique
   navigateur. Côté SSE, configurer le client pour envoyer le header
   à l'établissement de la connexion (EventSource ne le supporte pas
   nativement ; utiliser un fetch-based polyfill ou un reverse-proxy
   qui injecte la clé).

2. **Fail-fast au démarrage** : un serveur prod qui démarre en HTTP
   *sans* clé service est presque toujours une erreur de configuration.
   :func:`assert_startup_config` lève ``RuntimeError`` quand :

   - transport ≠ stdio ET ``AUDIT_BIM_REQUIRE_API_KEY=true`` (ou
     ``AUDIT_BIM_ENV=production``) ET la clé n'est pas définie ;
   - **tout transport réseau** ET ``AUDIT_INPUT_DIR`` n'est pas défini,
     sauf opt-out explicite ``AUDIT_BIM_ALLOW_UNBOUNDED_INPUTS=true``
     (PR3 §3b — indépendant de la présence d'une clé) ;
   - host = ``0.0.0.0`` sans ``AUDIT_BIM_ENV=production``.

3. **Politique d'écriture** : ``AUDIT_BIM_ALLOW_WRITES`` gouverne tous
   les tools mutatifs BIMData. Défaut **secure-by-transport, fail-closed**
   (PR3 §3a) :

   - ``true`` uniquement pour un transport **local déclaré** (``stdio`` /
     ``script`` : ``__main__``, ``cli.py``, runners, fixture de tests) ;
   - ``false`` en transport réseau (HTTP / SSE / streamable-http) **et pour
     un transport non déclaré** (``None`` : montage ASGI custom,
     ``fastmcp run``) tant que ``AUDIT_BIM_ALLOW_WRITES=true`` n'est pas
     explicitement posé.

   Le flag explicite gagne toujours. :func:`ensure_writes_allowed` est
   appelée par chaque tool mutatif avant tout side-effect distant.
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
ALLOW_UNBOUNDED_INPUTS_ENV = "AUDIT_BIM_ALLOW_UNBOUNDED_INPUTS"
ALLOW_ACCESS_TOKEN_PARAM_ENV = "AUDIT_BIM_ALLOW_ACCESS_TOKEN_PARAM"

# Transport configuré au démarrage (cf. :func:`set_runtime_transport`).
# ``None`` = **non déclaré** ⇒ traité comme **réseau (fail-closed)** : un montage
# ASGI custom ou ``fastmcp run`` qui n'appelle pas ``set_runtime_transport`` n'obtient
# PAS les défauts permissifs locaux. Les entrypoints locaux **légitimes** (``__main__``
# stdio, ``cli.py``, runners de ``scripts/``, fixture de tests) se déclarent
# explicitement via ``set_runtime_transport`` (``"stdio"`` ou ``"script"``).
_RUNTIME_TRANSPORT: str | None = None

# Transports **locaux** (IPC, pas d'exposition réseau) : défauts permissifs.
_LOCAL_TRANSPORTS = ("stdio", "script")
# Transports **réseau** exposables : défauts fail-closed.
_NETWORK_TRANSPORTS = ("http", "sse", "streamable-http")


def set_runtime_transport(transport: str) -> None:
    """Mémorise le transport choisi au démarrage.

    Appelé par ``audit_bim.mcp.__main__`` avant ``mcp.run`` (transport réel :
    ``stdio``/``http``/…) **et** par les entrypoints locaux (``cli.py``, runners,
    fixture de tests) avec ``"script"`` / ``"stdio"`` pour se **déclarer locaux** —
    sans quoi ils hériteraient du défaut réseau fail-closed (``None``).
    """
    global _RUNTIME_TRANSPORT
    _RUNTIME_TRANSPORT = transport


def _is_network_transport() -> bool:
    """``True`` si le runtime tourne sur un transport réseau exposable."""
    return _RUNTIME_TRANSPORT in _NETWORK_TRANSPORTS


def _is_local_transport() -> bool:
    """``True`` **uniquement** pour un transport local **explicitement déclaré**
    (``stdio``/``script``). ``None`` (non déclaré) → ``False`` : fail-closed."""
    return _RUNTIME_TRANSPORT in _LOCAL_TRANSPORTS


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

    Logique :

    - ``AUDIT_BIM_ALLOW_WRITES`` défini → on respecte la valeur
      explicite (``true`` / ``false``). **Précédence inchangée : le flag
      explicite gagne toujours.**
    - Variable non définie :

      - transport **local déclaré** (``stdio`` / ``script`` : ``__main__``,
        cli, runners, tests) → ``True`` (mode AMO BIM interactif local).
      - transport réseau (``http`` / ``sse`` / ``streamable-http``) **ou
        non déclaré** (``None`` : montage ASGI custom, ``fastmcp run``)
        → ``False`` *par défaut* (**fail-closed**) — un déploiement doit
        explicitement choisir ``AUDIT_BIM_ALLOW_WRITES=true``.
    """
    raw = os.getenv(ALLOW_WRITES_ENV)
    if raw is not None:
        return _is_truthy(raw)
    # Défaut secure-by-transport : local déclaré uniquement (None = fail-closed).
    return _is_local_transport()


class WritesDisabledError(PermissionError):
    """Levée par un tool mutatif quand ``AUDIT_BIM_ALLOW_WRITES=false``."""


class AccessTokenParamDisabledError(PermissionError):
    """Levée quand un Bearer token utilisateur est passé en argument MCP
    alors que le transport réseau l'interdit (cf.
    :func:`is_access_token_param_allowed`).
    """


def is_access_token_param_allowed() -> bool:
    """Indique si un tool MCP accepte ``access_token=...`` en paramètre.

    Logique :

    - ``AUDIT_BIM_ALLOW_ACCESS_TOKEN_PARAM`` défini → respecte la valeur
      explicite (``true`` / ``false``).
    - Variable non définie :

      - transport **local déclaré** (``stdio`` / ``script`` : tests,
        scripts directs) → ``True`` — un token passé en argument circule
        seulement par IPC local.
      - transport réseau (``http`` / ``sse`` / ``streamable-http``) **ou
        non déclaré** (``None``) → ``False`` *par défaut* (**fail-closed**).
        Les paramètres MCP transitent dans des frames JSON-RPC visibles
        côté logs client, agent traces, reverse-proxy. Le serveur doit
        utiliser sa propre auth (env ``BIMDATA_API_KEY`` /
        client_credentials, ou injection d'identité par le proxy).
    """
    raw = os.getenv(ALLOW_ACCESS_TOKEN_PARAM_ENV)
    if raw is not None:
        return _is_truthy(raw)
    return _is_local_transport()


def ensure_access_token_param_allowed() -> None:
    """À appeler par les tools MCP qui acceptent ``access_token=`` avant
    de l'utiliser, **uniquement quand un token est effectivement fourni**.

    Raises:
        AccessTokenParamDisabledError: Si la politique courante interdit
            ce mode (transport réseau sans opt-in explicite).
    """
    if not is_access_token_param_allowed():
        logger.warning(
            "access_token param refused on network transport (set "
            "AUDIT_BIM_ALLOW_ACCESS_TOKEN_PARAM=true to override)"
        )
        raise AccessTokenParamDisabledError(
            "Paramètre `access_token` refusé sur transport réseau "
            "(http/sse/streamable-http) : les arguments MCP transitent "
            "dans les logs client / agent traces / reverse-proxy et un "
            "Bearer token y fuirait.\n\n"
            "Deux corrections possibles :\n"
            "  1. RECOMMANDÉ — configurer l'auth BIMData côté serveur "
            "via les variables d'env (au choix : `BIMDATA_API_KEY=…` ou "
            "`BIMDATA_CLIENT_ID=…` + `BIMDATA_CLIENT_SECRET=…`), puis "
            "appeler set_active_model / full_audit SANS `access_token`.\n"
            "  2. DÉCONSEILLÉ — opt-in explicite en démarrant le serveur "
            "avec `AUDIT_BIM_ALLOW_ACCESS_TOKEN_PARAM=true` (à n'utiliser "
            "que si les logs JSON-RPC sont eux-mêmes confidentiels)."
        )


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


# ── Démarrage : diagnostic auth BIMData ──────────────────────────────────


def _mask_secret(value: str | None) -> str:
    """Empreinte non-divulgante d'un secret : ``…<4 derniers>``."""
    if not value:
        return "∅"
    return f"…{value[-4:]}" if len(value) >= 4 else "…"


def warn_bimdata_auth_mode() -> None:
    """Logge le mode d'auth BIMData **effectif** et avertit si plusieurs modes
    sont configurés en même temps.

    Précédence (identique à ``bimdata_read._auth_headers`` et à
    ``tools_session._active_auth``) : ``access_token`` → ``api_key`` → OAuth2
    ``client_credentials``. Le premier disponible gagne — un credential de rang
    supérieur **périmé masque silencieusement** un mode inférieur valide (cause
    racine classique d'un 401 « inexplicable »). On logge donc, valeurs masquées,
    lequel est retenu et lesquels sont ignorés.
    """
    access = os.getenv("BIMDATA_ACCESS_TOKEN")
    api_key = os.getenv("BIMDATA_API_KEY")
    client_id = os.getenv("BIMDATA_CLIENT_ID")
    client_secret = os.getenv("BIMDATA_CLIENT_SECRET")

    modes: list[tuple[str, str, str]] = []
    if access:
        modes.append(("BIMDATA_ACCESS_TOKEN", "Bearer", access))
    if api_key:
        modes.append(("BIMDATA_API_KEY", "ApiKey", api_key))
    if client_id and client_secret:
        modes.append(("BIMDATA_CLIENT_ID+SECRET", "Bearer(OAuth2)", client_id))

    if not modes:
        logger.warning(
            "Aucune auth BIMData configurée (ni BIMDATA_API_KEY, ni ACCESS_TOKEN, "
            "ni CLIENT_ID+SECRET) — tout appel BIMData échouera."
        )
        return

    source, scheme, value = modes[0]
    logger.info("Auth BIMData active : %s (%s, %s)", source, scheme, _mask_secret(value))
    if len(modes) > 1:
        ignored = ", ".join(m[0] for m in modes[1:])
        logger.warning(
            "Plusieurs modes d'auth BIMData définis → seul %s (%s, %s) est utilisé ; "
            "ignoré(s) : %s. Un credential de rang supérieur périmé masquerait les "
            "autres → n'en configurer qu'un seul (politique clé serveur : BIMDATA_API_KEY "
            "uniquement).",
            source,
            scheme,
            _mask_secret(value),
            ignored,
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
    # Diagnostic auth BIMData — tous transports (le 401 « inexplicable » vient
    # le plus souvent d'ici : mode masqué / credential périmé).
    warn_bimdata_auth_mode()

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

    # ``AUDIT_INPUT_DIR`` est obligatoire pour **tout transport réseau**
    # (durcissement F4). On atteint ce point uniquement en réseau (le
    # ``stdio`` a retourné plus haut). Sans racine définie,
    # ``safe_input_path`` accepte tout fichier local existant — zone trop
    # implicite pour un MCP exposé, indépendamment de la présence d'une clé.
    #
    # Opt-out explicite : ``AUDIT_BIM_ALLOW_UNBOUNDED_INPUTS=true`` (à
    # n'activer qu'en connaissance de cause pour les déploiements qui ont
    # d'autres garde-fous filesystem côté infra — chroot, conteneur
    # restreint, AppArmor).
    if not os.getenv("AUDIT_INPUT_DIR") and not _is_truthy(os.getenv(ALLOW_UNBOUNDED_INPUTS_ENV)):
        raise RuntimeError(
            f"Transport réseau ({transport}) mais AUDIT_INPUT_DIR n'est pas "
            "défini — refus de démarrer. Tout fichier local lisible par le "
            "processus serait sinon ouvrable par un client MCP distant. Définir "
            "AUDIT_INPUT_DIR sur un dossier dédié aux documents auditables "
            "(DOE, CCH, annexes), ou opter explicitement pour le mode permissif "
            "via AUDIT_BIM_ALLOW_UNBOUNDED_INPUTS=true (déconseillé sans "
            "garde-fou filesystem côté infra)."
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
        # Sur un transport réseau, ce log signifie que l'utilisateur a
        # explicitement mis ``AUDIT_BIM_ALLOW_WRITES=true``. C'est un
        # signal à laisser visible pour audit de configuration.
        logger.warning(
            "AUDIT_BIM_ALLOW_WRITES=true en transport %s — les tools "
            "d'écriture (apply_bcf_topics, apply_smart_views_plan, "
            "apply_classification_update_plan, apply_doe_enrichment_plan, "
            "full_audit avec push) peuvent toucher BIMData. Confirmer que "
            "c'est l'effet attendu.",
            transport,
        )
    else:
        logger.info(
            "AUDIT_BIM_ALLOW_WRITES inactif sur transport %s — les tools "
            "mutatifs sont en mode read-only. Définir explicitement "
            "AUDIT_BIM_ALLOW_WRITES=true pour autoriser les push.",
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
