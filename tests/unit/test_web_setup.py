"""Façade web ``/mcp-setup`` + liaison token → session MCP (couches 1 & 3).

Couvre les tests de sécurité obligatoires :

- ``POST /api/mcp/session`` ne renvoie jamais ``BIMDATA_API_KEY`` ;
- token invalide → tools MCP refusés ;
- token expiré → tools MCP refusés ;
- deux sessions / deux ``model_id`` restent isolées ;
- ``DELETE`` révoque le token ;
- logs / erreurs redacted (le secret/clé n'apparaît jamais dans les logs).
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from audit_bim.extraction.client import BIMDataAuthError
from audit_bim.mcp import middleware as mw
from audit_bim.mcp import security
from audit_bim.mcp.server import mcp
from audit_bim.mcp.session import current_session
from audit_bim.mcp.session_credentials import SetupSessionStore, split_token

API_KEY = "SUPER_SECRET_BIMDATA_KEY"


# ── Faux client BIMData (aucun appel réseau) ─────────────────────────────


class _FakeClient:
    def __init__(self, **kw):
        self.kw = kw

    def get_project(self):
        return {"name": "Programme Test"}

    def get_model(self):
        return {"name": "TEST.ifc"}


def _fake_auth(code: int):
    class _C(_FakeClient):
        def get_project(self):
            raise BIMDataAuthError(f"BIMData {code} on /project")

    return _C


@pytest.fixture
def web_client(monkeypatch):
    monkeypatch.setattr("audit_bim.web.setup.BIMDataClient", _FakeClient)
    # Custom routes seules : pas besoin du lifespan MCP.
    return TestClient(mcp.http_app())


def _payload(**over):
    p = {
        "bimdata_api_key": API_KEY,
        "cloud_id": "10",
        "project_id": "20",
        "model_id": "30",
        "default_phase": "DOE",
        "auditor_name": "AMO BIM",
    }
    p.update(over)
    return p


# ── Couche 1 : endpoints web ─────────────────────────────────────────────


def test_setup_page_served(web_client):
    r = web_client.get("/mcp-setup")
    assert r.status_code == 200
    assert "Connexion BIMData" in r.text


def test_test_connection_ok(web_client):
    r = web_client.post("/api/mcp/test-connection", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["project_name"] == "Programme Test"
    assert body["model_name"] == "TEST.ifc"
    # La clé ne fuite jamais dans la réponse.
    assert API_KEY not in r.text


def test_test_connection_auth_401(monkeypatch, web_client):
    monkeypatch.setattr("audit_bim.web.setup.BIMDataClient", _fake_auth(401))
    r = web_client.post("/api/mcp/test-connection", json=_payload())
    assert r.status_code == 401
    assert r.json()["ok"] is False


def test_test_connection_permission_403(monkeypatch, web_client):
    monkeypatch.setattr("audit_bim.web.setup.BIMDataClient", _fake_auth(403))
    r = web_client.post("/api/mcp/test-connection", json=_payload())
    assert r.status_code == 403


def test_test_connection_validation_422(web_client):
    r = web_client.post("/api/mcp/test-connection", json=_payload(model_id=""))
    assert r.status_code == 422


def test_create_session_never_returns_api_key(web_client):
    r = web_client.post("/api/mcp/session", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["mcp_ready"] is True
    assert body["session_id"] and body["token"]
    assert body["header_name"] == "X-MCP-Session-Token"
    # >>> La clé API BIMData ne doit JAMAIS apparaître dans la réponse <<<
    assert API_KEY not in r.text
    assert "bimdata_api_key" not in r.text


def test_status_then_delete_revokes(web_client):
    token = web_client.post("/api/mcp/session", json=_payload()).json()["token"]
    sid, _ = split_token(token)
    headers = {"X-MCP-Session-Token": token}

    st = web_client.get("/api/mcp/session/status", headers=headers)
    assert st.status_code == 200
    info = st.json()
    assert info["model_id"] == "30" and info["phase"] == "DOE"
    assert API_KEY not in st.text

    dl = web_client.request("DELETE", f"/api/mcp/session/{sid}", headers=headers)
    assert dl.status_code == 200 and dl.json()["ok"] is True

    # Après révocation, le status est refusé.
    st2 = web_client.get("/api/mcp/session/status", headers=headers)
    assert st2.status_code == 401


def test_delete_wrong_token_refused(web_client):
    token = web_client.post("/api/mcp/session", json=_payload()).json()["token"]
    sid, _ = split_token(token)
    bad = {"X-MCP-Session-Token": f"{sid}.wrong-secret"}
    dl = web_client.request("DELETE", f"/api/mcp/session/{sid}", headers=bad)
    assert dl.status_code == 401


# ── Couche 3 : middleware token → session MCP ────────────────────────────


def _run_dispatch(monkeypatch, *, store, raw_token):
    """Exécute ``McpSessionTokenMiddleware._dispatch`` et renvoie le
    ``model_id`` vu par le tool (via ``current_session``), ou lève."""
    monkeypatch.setattr(mw, "get_store", lambda: store)
    monkeypatch.setattr(mw, "_raw_session_token", lambda: raw_token)
    captured = {}

    async def call_next(_ctx):
        captured["model_id"] = current_session.get().model_id
        captured["api_key"] = current_session.get().client.api_key
        return "OK"

    middleware = mw.McpSessionTokenMiddleware()
    result = asyncio.run(middleware._dispatch(object(), call_next))
    return result, captured


def test_valid_token_binds_credentialed_session(monkeypatch):
    store = SetupSessionStore()
    _, token = store.create(api_key="K", cloud_id=1, project_id=2, model_id=77, phase="DOE")
    result, captured = _run_dispatch(monkeypatch, store=store, raw_token=token)
    assert result == "OK"
    assert captured["model_id"] == "77"
    assert captured["api_key"] == "K"


def test_two_sessions_isolated_via_middleware(monkeypatch):
    store = SetupSessionStore()
    _, t1 = store.create(api_key="K1", cloud_id=1, project_id=1, model_id=111, phase="DOE")
    _, t2 = store.create(api_key="K2", cloud_id=2, project_id=2, model_id=222, phase="PRO")
    _, c1 = _run_dispatch(monkeypatch, store=store, raw_token=t1)
    _, c2 = _run_dispatch(monkeypatch, store=store, raw_token=t2)
    assert c1["model_id"] == "111" and c1["api_key"] == "K1"
    assert c2["model_id"] == "222" and c2["api_key"] == "K2"


def test_invalid_token_refuses_tool(monkeypatch):
    store = SetupSessionStore()
    with pytest.raises(ToolError):
        _run_dispatch(monkeypatch, store=store, raw_token="bad.secret")


def test_expired_token_refuses_tool(monkeypatch):
    store = SetupSessionStore(ttl_s=3600)
    _, token = store.create(api_key="K", cloud_id=1, project_id=2, model_id=3, phase="DOE")
    real_now = time.time()
    monkeypatch.setattr("audit_bim.mcp.session_credentials.time.time", lambda: real_now + 7200)
    with pytest.raises(ToolError):
        _run_dispatch(monkeypatch, store=store, raw_token=token)


def test_missing_token_passthrough_when_not_required(monkeypatch):
    # Pas de flag require + pas de token → pass-through (legacy/stdio).
    monkeypatch.setattr(mw, "_raw_session_token", lambda: None)
    monkeypatch.delenv("AUDIT_BIM_REQUIRE_SESSION_TOKEN", raising=False)

    async def call_next(_ctx):
        return "PASSTHROUGH"

    middleware = mw.McpSessionTokenMiddleware()
    assert asyncio.run(middleware._dispatch(object(), call_next)) == "PASSTHROUGH"


def test_missing_token_refused_when_required(monkeypatch):
    monkeypatch.setattr(mw, "_raw_session_token", lambda: None)
    monkeypatch.setenv("AUDIT_BIM_REQUIRE_SESSION_TOKEN", "true")
    monkeypatch.setattr(security, "_RUNTIME_TRANSPORT", "streamable-http")

    async def call_next(_ctx):
        return "SHOULD_NOT_RUN"

    middleware = mw.McpSessionTokenMiddleware()
    with pytest.raises(ToolError):
        asyncio.run(middleware._dispatch(object(), call_next))


def test_missing_token_refused_by_default_when_protected(monkeypatch):
    # Défaut fail-closed : transport réseau + clé service + flag NON posé
    # → token requis (sans avoir à poser AUDIT_BIM_REQUIRE_SESSION_TOKEN).
    monkeypatch.setattr(mw, "_raw_session_token", lambda: None)
    monkeypatch.delenv("AUDIT_BIM_REQUIRE_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("AUDIT_BIM_API_KEY", "svc-key")
    monkeypatch.setattr(security, "_RUNTIME_TRANSPORT", "streamable-http")

    async def call_next(_ctx):
        return "SHOULD_NOT_RUN"

    with pytest.raises(ToolError):
        asyncio.run(mw.McpSessionTokenMiddleware()._dispatch(object(), call_next))


def test_logs_redacted_on_invalid_token(monkeypatch, caplog):
    store = SetupSessionStore()
    raw = "abc.SUPERSECRETVALUE"
    monkeypatch.setattr(mw, "get_store", lambda: store)
    monkeypatch.setattr(mw, "_raw_session_token", lambda: raw)

    async def call_next(_ctx):
        return "OK"

    middleware = mw.McpSessionTokenMiddleware()
    with caplog.at_level("WARNING"), pytest.raises(ToolError):
        asyncio.run(middleware._dispatch(object(), call_next))
    # Le secret brut ne doit jamais apparaître dans les logs ; un hash oui.
    assert "SUPERSECRETVALUE" not in caplog.text
    assert "sha256:" in caplog.text


# ── Guard clé service sur les routes /api/mcp/* (P1-a) ───────────────────

_API_ROUTES = [
    ("POST", "/api/mcp/test-connection"),
    ("POST", "/api/mcp/session"),
    ("GET", "/api/mcp/session/status"),
    ("DELETE", "/api/mcp/session/abc123"),
]


@pytest.fixture
def keyed_client(monkeypatch):
    """Client web avec ``AUDIT_BIM_API_KEY`` actif (déploiement protégé)."""
    monkeypatch.setenv("AUDIT_BIM_API_KEY", "svc-key")
    monkeypatch.setattr("audit_bim.web.setup.BIMDataClient", _FakeClient)
    return TestClient(mcp.http_app())


@pytest.mark.parametrize("method,path", _API_ROUTES)
def test_api_route_refused_without_service_key(keyed_client, method, path):
    # Le guard s'exécute avant tout parsing → 401 sans X-API-Key.
    r = keyed_client.request(method, path)
    assert r.status_code == 401


@pytest.mark.parametrize("method,path", _API_ROUTES)
def test_api_route_refused_with_wrong_service_key(keyed_client, method, path):
    r = keyed_client.request(method, path, headers={"X-API-Key": "nope"})
    assert r.status_code == 401


def test_api_routes_allowed_with_correct_service_key(keyed_client):
    h = {"X-API-Key": "svc-key"}
    r = keyed_client.post("/api/mcp/test-connection", headers=h, json=_payload())
    assert r.status_code == 200
    r = keyed_client.post("/api/mcp/session", headers=h, json=_payload())
    assert r.status_code == 200
    token = r.json()["token"]
    sid, _ = split_token(token)
    h2 = {"X-API-Key": "svc-key", "X-MCP-Session-Token": token}
    assert keyed_client.get("/api/mcp/session/status", headers=h2).status_code == 200
    assert keyed_client.request("DELETE", f"/api/mcp/session/{sid}", headers=h2).status_code == 200


def test_setup_page_open_without_service_key(keyed_client):
    # La page HTML reste accessible (aucun secret) même clé service active.
    assert keyed_client.get("/mcp-setup").status_code == 200
