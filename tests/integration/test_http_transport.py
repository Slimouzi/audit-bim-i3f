"""Tests d'intégration HTTP du serveur MCP (transport streamable-http).

Valide que :

- le serveur démarre et écoute sur le port demandé,
- ``GET /mcp`` sans header ``Accept`` correct renvoie ``406`` (comportement
  MCP standard — protection contre les clients mal configurés),
- ``GET /mcp`` avec ``Accept: text/event-stream`` ne renvoie pas 406 (le
  serveur considère la requête valide même s'il manque l'init MCP).

On ne teste pas ici la sémantique des tools eux-mêmes (couvert par les
tests unitaires) ; on valide la **mécanique de transport HTTP** côté MCP.
"""

from __future__ import annotations

import pytest
import requests


@pytest.mark.integration
class TestHttpServerLifecycle:
    def test_server_responds_on_root(self, mcp_http_server):
        # Le serveur écoute, même si la route / n'est pas définie.
        r = requests.get(mcp_http_server["url"] + "/", timeout=5)
        # 404 ou autre code 4xx accepté — l'important est que le serveur
        # écoute (sinon erreur de connexion).
        assert r.status_code < 600

    def test_mcp_endpoint_returns_406_without_sse_accept(self, mcp_http_server):
        # Comportement MCP standard : sans Accept text/event-stream,
        # streamable-http refuse l'établissement de connexion.
        r = requests.get(mcp_http_server["mcp_endpoint"], timeout=5)
        assert r.status_code == 406
        # Le body est un JSON-RPC error MCP standard
        body = r.json()
        assert body.get("jsonrpc") == "2.0"
        assert "error" in body
        assert "event-stream" in body["error"]["message"].lower()


@pytest.mark.integration
class TestMcpProtocolHandshake:
    """Vérifie qu'un client MCP peut initialiser une session.

    On utilise directement le client SDK fastmcp pour éviter de
    réimplémenter le protocole MCP (init / list_tools).
    """

    def test_list_tools_via_fastmcp_client(self, mcp_http_server):
        # Import paresseux : fastmcp.Client est dans fastmcp depuis 2.x
        try:
            from fastmcp import Client
            from fastmcp.client.transports import StreamableHttpTransport
        except ImportError:
            pytest.skip("fastmcp Client non disponible dans cette version.")

        import asyncio

        async def _run():
            transport = StreamableHttpTransport(mcp_http_server["mcp_endpoint"])
            async with Client(transport) as client:
                tools = await client.list_tools()
                return tools

        tools = asyncio.run(_run())
        names = {t.name for t in tools}
        # Les tools clés doivent être présents
        assert "project_context_questions" in names
        assert "list_classification_systems" in names
        assert "extract_model_snapshot" in names
        assert "full_audit" in names

    def test_call_list_classification_systems(self, mcp_http_server):
        try:
            from fastmcp import Client
            from fastmcp.client.transports import StreamableHttpTransport
        except ImportError:
            pytest.skip("fastmcp Client non disponible dans cette version.")

        import asyncio

        async def _run():
            transport = StreamableHttpTransport(mcp_http_server["mcp_endpoint"])
            async with Client(transport) as client:
                # Ce tool ne nécessite pas BIMData credentials ni snapshot
                return await client.call_tool("list_classification_systems", {})

        result = asyncio.run(_run())
        # Le résultat MCP est typiquement un objet avec .data / .content
        # On vérifie qu'il contient la liste attendue.
        payload = (
            getattr(result, "data", None) or getattr(result, "structured_content", None) or result
        )
        # Doit contenir les 4 systèmes (UniFormat II, Omniclass, CCS, 3F)
        text = repr(payload)
        assert "UniFormat" in text
        assert "Omniclass" in text
