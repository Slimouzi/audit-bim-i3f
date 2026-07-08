"""E13 (audit profond 2ᵉ passe) — couverture de ``on_get_prompt`` /
``on_read_resource`` du ``SessionBindingMiddleware``.

Ces handlers touchent à l'état de session (ils bindent ``current_session``) mais
n'étaient couverts par aucun test : une fuite d'état inter-sessions via les prompts
ou les resources passerait inaperçue. On vérifie bind + reset + isolation par clé.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from audit_bim.mcp.middleware import SessionBindingMiddleware
from audit_bim.mcp.session import _store, current_session


def _ctx(session_id: str) -> SimpleNamespace:
    return SimpleNamespace(fastmcp_context=SimpleNamespace(session_id=session_id, client_id=None))


def _run(coro):
    return asyncio.run(coro)


def _bound_session_during(handler_name: str, session_id: str):
    """Appelle le handler et renvoie la session vue par ``current_session`` pendant
    l'appel + son état après (doit être remis à zéro)."""
    mw = SessionBindingMiddleware()
    seen = {}

    async def call_next(_context):
        seen["during"] = current_session.get()
        return "ok"

    async def drive():
        handler = getattr(mw, handler_name)
        out = await handler(_ctx(session_id), call_next)
        return out

    out = _run(drive())
    return out, seen["during"]


def test_on_get_prompt_binds_and_resets():
    out, during = _bound_session_during("on_get_prompt", "sess-P")
    assert out == "ok"
    assert during is _store.get("sess-P")
    # après l'appel, plus aucune session bindée (LookupError → défaut None)
    assert current_session.get(None) is None


def test_on_read_resource_binds_and_resets():
    out, during = _bound_session_during("on_read_resource", "sess-R")
    assert out == "ok"
    assert during is _store.get("sess-R")
    assert current_session.get(None) is None


def test_prompt_isolation_between_sessions():
    # Deux clés distinctes → deux sessions distinctes (pas de partage d'état).
    _, s1 = _bound_session_during("on_get_prompt", "sess-1")
    _, s2 = _bound_session_during("on_get_prompt", "sess-2")
    assert s1 is not s2
    assert s1 is _store.get("sess-1")
    assert s2 is _store.get("sess-2")


def test_reset_even_on_exception():
    mw = SessionBindingMiddleware()

    async def boom(_context):
        raise RuntimeError("boom")

    async def drive():
        try:
            await mw.on_read_resource(_ctx("sess-E"), boom)
        except RuntimeError:
            pass
        # le finally du middleware doit avoir reset la session
        return current_session.get(None)

    assert _run(drive()) is None
