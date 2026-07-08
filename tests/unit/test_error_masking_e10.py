"""E10 (audit profond 2ᵉ passe) — masquage des erreurs en transport réseau.

Sans ``mask_error_details`` (non fixable à la construction de ``mcp``), une
exception non gérée d'un tool partirait au client avec son ``str()`` brut (chemins
serveur, URLs signées). ``ErrorMaskingMiddleware`` la masque en réseau (message
générique + détail redacté dans les logs) et la laisse brute en local.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

from audit_bim.mcp.middleware import ErrorMaskingMiddleware
from audit_bim.mcp.security import set_runtime_transport


@pytest.fixture(autouse=True)
def _restore_transport():
    from audit_bim.mcp import security

    prev = security._RUNTIME_TRANSPORT
    yield
    security._RUNTIME_TRANSPORT = prev


def _ctx():
    return SimpleNamespace(fastmcp_context=SimpleNamespace(session_id="s", client_id=None))


def _run(coro):
    return asyncio.run(coro)


_LEAKY = "boom at /Users/stani/code/MCP/secret/plan.json ?X-Amz-Signature=abcdef1234567890"


def test_network_transport_masks_details():
    set_runtime_transport("http")
    mw = ErrorMaskingMiddleware()

    async def leaky(_ctx):
        raise RuntimeError(_LEAKY)

    async def drive():
        with pytest.raises(ToolError) as ei:
            await mw.on_call_tool(_ctx(), leaky)
        msg = str(ei.value)
        assert "/Users/stani" not in msg
        assert "abcdef1234567890" not in msg
        assert "logs serveur" in msg

    _run(drive())


def test_local_transport_keeps_original():
    set_runtime_transport("stdio")
    mw = ErrorMaskingMiddleware()

    async def leaky(_ctx):
        raise RuntimeError(_LEAKY)

    async def drive():
        with pytest.raises(RuntimeError) as ei:
            await mw.on_call_tool(_ctx(), leaky)
        # en local, l'erreur brute est conservée (utile en dev)
        assert "plan.json" in str(ei.value)

    _run(drive())


def test_tool_error_passes_through_even_on_network():
    set_runtime_transport("http")
    mw = ErrorMaskingMiddleware()

    async def business(_ctx):
        raise ToolError("message métier destiné au client")

    async def drive():
        with pytest.raises(ToolError, match="message métier"):
            await mw.on_call_tool(_ctx(), business)

    _run(drive())


def test_success_passes_through():
    set_runtime_transport("http")
    mw = ErrorMaskingMiddleware()

    async def ok(_ctx):
        return "result"

    assert _run(mw.on_call_tool(_ctx(), ok)) == "result"
