"""Routes HTTP de la page « MCP Client Setup ».

Couche 1 du modèle « endpoint + token ». Sert :

- ``GET /mcp-setup`` — page HTML statique (tokens BIMData).
- ``POST /api/mcp/test-connection`` — teste les credentials BIMData.
- ``POST /api/mcp/session`` — crée une session crédentialée, renvoie un
  token opaque + l'endpoint MCP.
- ``GET /api/mcp/session/status`` — état non sensible d'une session.
- ``DELETE /api/mcp/session/{session_id}`` — révoque une session.

**Aucune réponse ne contient la clé API BIMData.** Le token (et son
secret) ne transite jamais dans une URL ni dans les logs.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from ..extraction.client import BIMDataAuthError, BIMDataClient
from ..mcp.security import verify_api_key
from ..mcp.session_credentials import CredentialError, get_store, split_token

logger = logging.getLogger("audit_bim.web.setup")

SESSION_TOKEN_HEADER = "X-MCP-Session-Token"

# Page HTML chargée une fois (incluse en package-data).
_PAGE_HTML = (Path(__file__).parent / "templates" / "mcp_setup.html").read_text(encoding="utf-8")


# ── Helpers ─────────────────────────────────────────────────────────────


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _require_service_api_key(request: Request) -> JSONResponse | None:
    """Guard clé service sur les routes ``/api/mcp/*``.

    ``ApiKeyMiddleware`` ne couvre que l'``initialize`` MCP : les custom
    routes Starlette doivent vérifier ``AUDIT_BIM_API_KEY`` elles-mêmes,
    sinon n'importe qui pourrait poster une clé BIMData et créer des
    sessions (broker de credentials non authentifié).

    - ``AUDIT_BIM_API_KEY`` non défini → ouvert (dev / stdio local).
    - défini → ``X-API-Key`` manquant ou faux → ``401``.

    Renvoie une ``JSONResponse`` de refus, ou ``None`` si l'accès est permis.
    """
    if verify_api_key(request.headers.get("x-api-key")):
        return None
    logger.warning("custom route refused: missing/invalid X-API-Key")
    return _err(401, "Clé service requise (en-tête X-API-Key).")


async def _read_payload(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception as exc:  # JSON invalide / corps vide
        raise CredentialError("Corps JSON invalide.") from exc
    if not isinstance(data, dict):
        raise CredentialError("Corps JSON invalide (objet attendu).")
    return data


def _make_client(payload: dict) -> BIMDataClient:
    """Construit un ``BIMDataClient`` **transitoire** depuis le payload.

    La clé API est injectée **par instance** (jamais via le ``config``
    global) — cf. ``BIMDataClient(api_key=...)``.
    """
    api_key = (payload.get("bimdata_api_key") or "").strip()
    if not api_key:
        raise CredentialError("Clé API BIMData requise.")
    cloud_id = payload.get("cloud_id")
    project_id = payload.get("project_id")
    model_id = payload.get("model_id")
    for label, val in (("cloud_id", cloud_id), ("project_id", project_id), ("model_id", model_id)):
        if val is None or str(val).strip() == "":
            raise CredentialError(f"{label} requis.")
    return BIMDataClient(
        api_key=api_key,
        cloud_id=cloud_id,
        project_id=project_id,
        model_id=model_id,
    )


def _test_connection(payload: dict) -> dict:
    """Teste la connexion BIMData et renvoie ``{project_name, model_name}``.

    Lève ``CredentialError`` (validation), ``BIMDataAuthError`` (401/403),
    ou ``requests.RequestException`` (réseau / autre statut).
    """
    client = _make_client(payload)
    project = client.get_project()
    model = client.get_model()
    return {
        "project_name": (project or {}).get("name"),
        "model_name": (model or {}).get("name"),
    }


def _mcp_endpoint(request: Request) -> str:
    # Endpoint MCP streamable-http (best-effort) servi par le même process.
    return f"{request.url.scheme}://{request.url.netloc}/mcp/"


# ── Routes ──────────────────────────────────────────────────────────────


def register_setup_routes(mcp) -> None:
    """Enregistre la page + l'API REST sur l'app FastMCP (custom routes).

    No-op fonctionnel en stdio (les custom routes ne sont servies que sous
    transport HTTP).
    """

    @mcp.custom_route("/mcp-setup", methods=["GET"])
    async def setup_page(request: Request) -> HTMLResponse:  # noqa: ARG001
        return HTMLResponse(_PAGE_HTML)

    @mcp.custom_route("/api/mcp/test-connection", methods=["POST"])
    async def test_connection(request: Request) -> JSONResponse:
        if (deny := _require_service_api_key(request)) is not None:
            return deny
        try:
            payload = await _read_payload(request)
            info = _test_connection(payload)
        except CredentialError as exc:
            return _err(422, str(exc))
        except BIMDataAuthError as exc:
            status = 403 if "403" in str(exc) else 401
            logger.warning("test-connection refused: BIMData auth (%s)", status)
            return _err(status, "Authentification/permission BIMData refusée.")
        except requests.RequestException:
            logger.warning("test-connection failed: BIMData unreachable/error")
            return _err(502, "BIMData injoignable ou a renvoyé une erreur.")
        return JSONResponse({"ok": True, **info})

    @mcp.custom_route("/api/mcp/session", methods=["POST"])
    async def create_session(request: Request) -> JSONResponse:
        if (deny := _require_service_api_key(request)) is not None:
            return deny
        try:
            payload = await _read_payload(request)
            # On revalide la connexion avant de matérialiser la session.
            _test_connection(payload)
            session_id, token = get_store().create(
                api_key=payload["bimdata_api_key"],
                cloud_id=payload["cloud_id"],
                project_id=payload["project_id"],
                model_id=payload["model_id"],
                phase=payload.get("default_phase", ""),
                auditor_name=payload.get("auditor_name"),
                project_address=payload.get("project_address"),
            )
        except CredentialError as exc:
            return _err(422, str(exc))
        except BIMDataAuthError as exc:
            status = 403 if "403" in str(exc) else 401
            return _err(status, "Authentification/permission BIMData refusée.")
        except requests.RequestException:
            return _err(502, "BIMData injoignable ou a renvoyé une erreur.")
        logger.info("mcp session created")
        # On ne renvoie JAMAIS la clé API. Le token est l'unique secret remis.
        return JSONResponse(
            {
                "ok": True,
                "session_id": session_id,
                "token": token,
                "mcp_ready": True,
                "mcp_endpoint": _mcp_endpoint(request),
                "header_name": SESSION_TOKEN_HEADER,
            }
        )

    @mcp.custom_route("/api/mcp/session/status", methods=["GET"])
    async def session_status(request: Request) -> JSONResponse:
        if (deny := _require_service_api_key(request)) is not None:
            return deny
        raw = request.headers.get(SESSION_TOKEN_HEADER)
        try:
            rec = get_store().resolve_token(raw)
        except CredentialError as exc:
            return _err(401, str(exc))
        info = get_store().info(rec)
        return JSONResponse(
            {
                "ok": True,
                "mcp_ready": True,
                "cloud_id": info.cloud_id,
                "project_id": info.project_id,
                "model_id": info.model_id,
                "phase": info.phase,
                "expires_in_s": info.expires_in_s,
            }
        )

    @mcp.custom_route("/api/mcp/session/{session_id}", methods=["DELETE"])
    async def delete_session(request: Request) -> JSONResponse:
        if (deny := _require_service_api_key(request)) is not None:
            return deny
        session_id = request.path_params["session_id"]
        raw = request.headers.get(SESSION_TOKEN_HEADER)
        tok_sid, secret = split_token(raw)
        # Le session_id du path (public) doit correspondre au token présenté.
        if not secret or tok_sid != session_id:
            return _err(401, "Token absent ou ne correspond pas à la session.")
        try:
            revoked = get_store().revoke(session_id, secret)
        except CredentialError as exc:
            return _err(401, str(exc))
        logger.info("mcp session revoked")
        return JSONResponse({"ok": bool(revoked)})
