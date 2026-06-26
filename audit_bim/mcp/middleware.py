"""Middlewares fastmcp du serveur audit-bim-i3f.

- :class:`SessionBindingMiddleware` : bind la
  :data:`audit_bim.mcp.session.current_session` à la session du client
  MCP actif avant chaque ``tools/call`` / ``prompts/get`` / etc., de
  sorte que le proxy ``_State`` route ses accès vers la bonne instance.

- :class:`ApiKeyMiddleware` : si ``AUDIT_BIM_API_KEY`` est défini,
  vérifie la clé service présentée par le client à
  l'initialisation MCP. Désactivé sur le transport ``stdio`` (le canal
  IPC est implicitement de confiance).
"""

from __future__ import annotations

import logging
import os

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

from ..extraction.client import BIMDataClient
from .security import (
    API_KEY_ENV,
    REQUIRE_SESSION_TOKEN_ENV,
    _is_network_transport,
    _is_truthy,
    verify_api_key,
)
from .security import scrub as _scrub
from .session import _Session, _store, current_session
from .session_credentials import CredentialError, _Record, get_store

logger = logging.getLogger("audit_bim.mcp.middleware")

# En-tête porteur du token de session crédentialée (façade ``/mcp-setup``).
# Distinct de ``X-API-Key`` (guard opérateur ``AUDIT_BIM_API_KEY``).
SESSION_TOKEN_HEADER = "x-mcp-session-token"


def _raw_session_token() -> str | None:
    """Lit l'en-tête ``X-MCP-Session-Token`` de la requête HTTP courante."""
    try:
        headers = get_http_headers(include_all=True)
    except Exception:
        return None
    return headers.get(SESSION_TOKEN_HEADER)


def _require_session_token() -> bool:
    """Faut-il refuser un appel d'outil sans token de session valide ?

    Politique **fail-closed par défaut en mode protégé** :

    - hors transport réseau (stdio) → jamais (``False``).
    - ``AUDIT_BIM_REQUIRE_SESSION_TOKEN`` défini explicitement → honoré.
    - sinon → ``True`` dès qu'``AUDIT_BIM_API_KEY`` est défini (déploiement
      HTTP protégé / hébergé : le token EST la frontière d'accès aux
      outils) ; ``False`` pour un HTTP RPC legacy sans clé service.

    Un token *présent mais invalide/expiré* est de toute façon toujours
    refusé en amont (``McpSessionTokenMiddleware._dispatch``).
    """
    if not _is_network_transport():
        return False
    raw = os.getenv(REQUIRE_SESSION_TOKEN_ENV)
    if raw is not None:
        return _is_truthy(raw)
    return bool(os.getenv(API_KEY_ENV))


def _build_credentialed_session(rec: _Record) -> _Session:
    """Fabrique un ``_Session`` à partir d'un record crédentialé.

    Le client BIMData reçoit la clé API **par instance** (pas de mutation
    du ``config`` global) — cf. ``BIMDataClient(api_key=...)``.
    """
    s = _Session()
    s.cloud_id = rec.cloud_id
    s.project_id = rec.project_id
    s.model_id = rec.model_id
    s.phase = rec.phase
    s.auditor_name = rec.auditor_name
    s.project_address = rec.project_address
    s.client = BIMDataClient(
        api_key=rec.api_key,
        cloud_id=rec.cloud_id,
        project_id=rec.project_id,
        model_id=rec.model_id,
    )
    return s


class SessionBindingMiddleware(Middleware):
    """Bind ``current_session`` au client MCP actif pour la durée de l'appel.

    La clé de session est issue, dans l'ordre, de :

    1. ``ctx.session_id`` (fastmcp ≥ 2.x)
    2. ``ctx.client_id``
    3. ``"default"`` (stdio mono-client, tests)
    """

    @staticmethod
    def _session_key(ctx) -> str:
        return getattr(ctx, "session_id", None) or getattr(ctx, "client_id", None) or "default"

    async def _bind(self, context: MiddlewareContext, call_next):
        # Si un token de session crédentialée est présent, on **cède** la
        # liaison à ``McpSessionTokenMiddleware`` (ordre-indépendant : peu
        # importe lequel s'exécute en premier, la session crédentialée
        # n'est jamais écrasée par la session générique vide).
        if _raw_session_token():
            return await call_next(context)
        ctx = context.fastmcp_context
        token = current_session.set(_store.get(self._session_key(ctx)))
        try:
            return await call_next(context)
        finally:
            current_session.reset(token)

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        return await self._bind(context, call_next)

    async def on_get_prompt(self, context: MiddlewareContext, call_next):
        return await self._bind(context, call_next)

    async def on_read_resource(self, context: MiddlewareContext, call_next):
        return await self._bind(context, call_next)


class ApiKeyMiddleware(Middleware):
    """Vérifie ``AUDIT_BIM_API_KEY`` à l'initialisation MCP (HTTP/SSE).

    Le header ``X-API-Key`` est extrait du transport sous-jacent quand
    disponible. Si la variable d'env n'est pas définie, la garde est
    désactivée. En stdio, fastmcp ne route pas l'initialize via ce
    middleware → comportement transparent.

    **Hypothèse de sécurité — vérification uniquement à l'initialize** :
    le protocole MCP exige que tout client effectue ``initialize`` avant
    tout autre handler (tools/list, tools/call, prompts/get, etc.).
    FastMCP refuse les requêtes hors-séquence — un client qui n'a pas
    fait ``initialize`` ne peut donc pas atteindre un tool. Vérifier la
    clé au seul ``on_initialize`` est suffisant *à condition* que cette
    garantie tienne côté framework.

    Si cette hypothèse devait être remise en cause (bug FastMCP, transport
    custom, etc.), la vérification doit être étendue à ``on_call_tool`` /
    ``on_get_prompt`` / ``on_read_resource``. Garder ce module comme point
    d'extension unique.
    """

    async def on_initialize(self, context: MiddlewareContext, call_next):
        expected = os.getenv(API_KEY_ENV)
        if not expected:
            return await call_next(context)
        # On lit le header du transport HTTP. fastmcp 3.x expose
        # ``context.fastmcp_context.request_context`` pour les transports
        # web — la clé exacte peut varier, on tente plusieurs noms.
        provided = self._extract_api_key(context)
        if not verify_api_key(provided):
            logger.warning("mcp init refused: invalid api key")
            raise ToolError("AUDIT_BIM_API_KEY invalide ou absent.")
        return await call_next(context)

    @staticmethod
    def _extract_api_key(context: MiddlewareContext) -> str | None:
        """Cherche la clé dans les headers HTTP de la requête courante.

        Utilise ``fastmcp.server.dependencies.get_http_headers`` qui
        introspecte le ``starlette.Request`` actif (snapshot inclus pour
        les tâches lifespan). Renvoie ``None`` si transport non-HTTP
        (stdio) ou si le header est absent.
        """
        _ = context  # ctx fastmcp non utilisé : on lit l'env HTTP global
        try:
            # ``include={"x-api-key"}`` n'est pas nécessaire (X-API-Key
            # n'est pas dans la liste d'exclusion par défaut), mais on
            # demande ``include_all=True`` pour rester robustes aux
            # changements futurs de la whitelist fastmcp.
            headers = get_http_headers(include_all=True)
        except Exception:
            return None
        # headers est dict[str, str] avec clés normalisées en minuscules.
        return headers.get("x-api-key")


class McpSessionTokenMiddleware(Middleware):
    """Lie une session crédentialée (page ``/mcp-setup``) via en-tête token.

    Couche 3 du modèle « endpoint + token » : le client MCP présente
    ``X-MCP-Session-Token: <session_id>.<secret>`` ; ce middleware résout le
    token vers les credentials BIMData stockés côté serveur
    (:mod:`audit_bim.mcp.session_credentials`) et lie ``current_session`` à
    la session crédentialée pour la durée de l'appel.

    **Politique (fail closed)** :

    - token **présent et invalide/expiré** → refus (``ToolError``), toujours.
    - token **présent et valide** → bind de la session crédentialée.
    - token **absent** → refus dès que le token est *requis*, sinon
      pass-through (stdio / env / legacy). Le caractère requis est décidé
      par :func:`_require_session_token` : sur transport réseau, le token
      est obligatoire **par défaut en mode protégé** (dès qu'``AUDIT_BIM_API_KEY``
      est défini), ou si ``AUDIT_BIM_REQUIRE_SESSION_TOKEN`` l'impose
      explicitement.

    Ce middleware **n'est pas** un remplacement d'``ApiKeyMiddleware`` (guard
    opérateur ``AUDIT_BIM_API_KEY`` à l'``initialize``) : les deux couches
    composent. Le token client est **distinct** d'``AUDIT_BIM_API_KEY``.
    """

    async def _dispatch(self, context: MiddlewareContext, call_next):
        raw = _raw_session_token()
        if not raw:
            if _require_session_token():
                logger.warning("mcp tool refused: missing X-MCP-Session-Token")
                raise ToolError(
                    "Session MCP requise : en-tête X-MCP-Session-Token absent. "
                    "Configurez une session via /mcp-setup."
                )
            return await call_next(context)

        store = get_store()
        try:
            rec = store.resolve_token(raw)
        except CredentialError as exc:
            # Jamais le token brut dans les logs — uniquement un hash court.
            logger.warning("mcp tool refused (%s) token=%s", exc, _scrub(raw))
            raise ToolError(f"Session MCP invalide : {exc}") from exc

        session = store.ensure_mcp_session(rec, lambda: _build_credentialed_session(rec))
        token = current_session.set(session)
        try:
            return await call_next(context)
        finally:
            current_session.reset(token)

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        return await self._dispatch(context, call_next)

    async def on_get_prompt(self, context: MiddlewareContext, call_next):
        return await self._dispatch(context, call_next)

    async def on_read_resource(self, context: MiddlewareContext, call_next):
        return await self._dispatch(context, call_next)
