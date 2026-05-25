"""Test d'intégration : deux sessions MCP HTTP n'observent pas le même état.

Vérifie que le ``SessionBindingMiddleware`` isole bien le ``_State``
entre deux clients ``fastmcp.Client`` connectés au même serveur. On
mute la phase dans la session A et on vérifie qu'elle n'est pas vue
par la session B.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.integration
class TestSessionIsolationOverHttp:
    """Deux clients distincts → deux ``session_id`` → deux ``_State``."""

    def test_phase_does_not_leak_between_sessions(self, mcp_http_server):
        try:
            from fastmcp import Client
            from fastmcp.client.transports import StreamableHttpTransport
        except ImportError:
            pytest.skip("fastmcp Client non disponible.")

        endpoint = mcp_http_server["mcp_endpoint"]

        async def _scenario():
            # Client A : mute phase = APS via set_active_model.
            # Pas d'``access_token`` en paramètre — depuis le round 7
            # review, c'est refusé sur transport réseau sauf opt-in
            # explicite. Le client BIMData prend l'env BIMDATA_API_KEY
            # (``dummy-for-integration-tests`` posé par le conftest).
            transport_a = StreamableHttpTransport(endpoint)
            async with Client(transport_a) as client_a:
                await client_a.call_tool(
                    "set_active_model",
                    {
                        "cloud_id": "111",
                        "project_id": "222",
                        "model_id": "333",
                        "phase": "APS",
                    },
                )
                ctx_a = await client_a.call_tool("project_context_questions", {})

            # Client B : nouvelle session, doit voir un état propre
            transport_b = StreamableHttpTransport(endpoint)
            async with Client(transport_b) as client_b:
                ctx_b = await client_b.call_tool("project_context_questions", {})

            return ctx_a, ctx_b

        ctx_a, ctx_b = asyncio.run(_scenario())

        # Petit utilitaire : extraire le payload d'un appel MCP
        def _data(res):
            return getattr(res, "data", None) or getattr(res, "structured_content", None) or {}

        a = _data(ctx_a)
        b = _data(ctx_b)

        # Session A : a configuré phase=APS et model_id=333
        assert a.get("current_context", {}).get("phase") == "APS"
        assert a.get("current_context", {}).get("model_id") == "333"

        # Session B : doit avoir un context PROPRE — pas le phase ni
        # le model_id de A. Le test passe si phase != APS (différent)
        # OU si phase est None (session vierge).
        b_ctx = b.get("current_context", {})
        assert b_ctx.get("phase") != "APS" or b_ctx.get("model_id") != "333", (
            "Fuite de contexte détectée : la session B voit l'état de A "
            f"(A={a.get('current_context')}, B={b_ctx})"
        )
