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

from .security import API_KEY_ENV, verify_api_key
from .session import _store, current_session

logger = logging.getLogger("audit_bim.mcp.middleware")


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

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        ctx = context.fastmcp_context
        key = self._session_key(ctx)
        session = _store.get(key)
        token = current_session.set(session)
        try:
            return await call_next(context)
        finally:
            current_session.reset(token)

    # Idem pour les autres handlers qui peuvent toucher à l'état (prompts,
    # resources). On copie le pattern par cohérence.

    async def on_get_prompt(self, context: MiddlewareContext, call_next):
        ctx = context.fastmcp_context
        token = current_session.set(_store.get(self._session_key(ctx)))
        try:
            return await call_next(context)
        finally:
            current_session.reset(token)

    async def on_read_resource(self, context: MiddlewareContext, call_next):
        ctx = context.fastmcp_context
        token = current_session.set(_store.get(self._session_key(ctx)))
        try:
            return await call_next(context)
        finally:
            current_session.reset(token)


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
