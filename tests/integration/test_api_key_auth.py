"""Tests d'intégration HTTP : vérification de ``AUDIT_BIM_API_KEY``.

Couvre les 3 cas attendus quand le serveur tourne avec une clé service :

1. Pas de header ``X-API-Key`` → init MCP refusé.
2. Mauvaise clé → init MCP refusé.
3. Bonne clé → ``list_tools`` renvoie les tools.
"""

from __future__ import annotations

import asyncio

import pytest


def _connect_and_list_tools(endpoint: str, headers: dict[str, str] | None) -> list:
    """Helper : tente init + list_tools via fastmcp.Client.

    Returns:
        La liste de tools si la session aboutit, sinon lève l'erreur de
        connexion / d'auth telle quelle.
    """
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    async def _run():
        transport = StreamableHttpTransport(endpoint, headers=headers or {})
        async with Client(transport) as client:
            return await client.list_tools()

    return asyncio.run(_run())


def _auth_refusal_excinfo() -> type[BaseException]:
    """Type d'exception attendu quand le middleware refuse l'auth.

    FastMCP wrappe la ``ToolError`` levée dans ``on_initialize`` en
    :class:`mcp.shared.exceptions.McpError` avec un message générique.
    On cible ce type précis plutôt que ``Exception`` pour éviter de
    masquer des erreurs réseau / timeout (qui ne sont pas un refus
    d'auth).
    """
    from mcp.shared.exceptions import McpError

    return McpError


@pytest.mark.integration
class TestApiKeyAuth:
    """Garantit le contrat *séparation refus / acceptation* :

    - ``test_valid_header_accepted`` : l'auth réussie revient avec les
      tools attendus ;
    - ``test_*_refused`` : sans clé / mauvaise clé → ``McpError``
      typé (pas n'importe quelle exception).

    FastMCP wrappe ``ToolError`` levée dans ``on_initialize`` en
    ``McpError("Invalid request parameters")`` — on teste sur le type
    pour ne pas masquer un timeout / erreur réseau.
    """

    def test_missing_header_refused(self, mcp_http_server_with_api_key):
        endpoint = mcp_http_server_with_api_key["mcp_endpoint"]
        with pytest.raises(_auth_refusal_excinfo()):
            _connect_and_list_tools(endpoint, headers=None)

    def test_wrong_header_refused(self, mcp_http_server_with_api_key):
        endpoint = mcp_http_server_with_api_key["mcp_endpoint"]
        with pytest.raises(_auth_refusal_excinfo()):
            _connect_and_list_tools(endpoint, headers={"X-API-Key": "wrong-key"})

    def test_valid_header_accepted(self, mcp_http_server_with_api_key):
        endpoint = mcp_http_server_with_api_key["mcp_endpoint"]
        api_key = mcp_http_server_with_api_key["api_key"]
        tools = _connect_and_list_tools(endpoint, headers={"X-API-Key": api_key})
        names = {t.name for t in tools}
        # Les tools attendus sont bien exposés
        assert "list_classification_systems" in names
        assert "project_context_questions" in names

    def test_valid_then_invalid_in_separate_sessions(self, mcp_http_server_with_api_key):
        """Garantit que l'auth est vérifiée à chaque nouvelle session, pas
        cachée d'une connexion précédente."""
        endpoint = mcp_http_server_with_api_key["mcp_endpoint"]
        api_key = mcp_http_server_with_api_key["api_key"]
        # Session 1 : OK
        _connect_and_list_tools(endpoint, headers={"X-API-Key": api_key})
        # Session 2 : sans clé → refusé (type précis : pas timeout/réseau)
        with pytest.raises(_auth_refusal_excinfo()):
            _connect_and_list_tools(endpoint, headers=None)
