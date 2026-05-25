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


@pytest.mark.integration
class TestApiKeyAuth:
    """Garantit le contrat *séparation refus / acceptation* :

    Le test critique est ``test_valid_header_accepted`` (l'auth réussie
    revient avec les tools), couplé aux deux refus (``missing`` et
    ``wrong``). FastMCP wrappe les erreurs middleware en ``McpError``
    avec un message générique ``"Invalid request parameters"`` — on
    accepte donc ce message comme indicateur de refus, ce qui suffit à
    distinguer auth-OK de auth-KO.
    """

    def test_missing_header_refused(self, mcp_http_server_with_api_key):
        endpoint = mcp_http_server_with_api_key["mcp_endpoint"]
        with pytest.raises(Exception):  # noqa: B017 — fastmcp wrappe en McpError générique
            _connect_and_list_tools(endpoint, headers=None)

    def test_wrong_header_refused(self, mcp_http_server_with_api_key):
        endpoint = mcp_http_server_with_api_key["mcp_endpoint"]
        with pytest.raises(Exception):  # noqa: B017 — fastmcp wrappe en McpError générique
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
        # Session 2 : sans clé → refusé
        with pytest.raises(Exception):  # noqa: B017 — fastmcp wrappe en McpError générique
            _connect_and_list_tools(endpoint, headers=None)
