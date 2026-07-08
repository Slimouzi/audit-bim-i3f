"""E9 (audit profond 2ᵉ passe) — sérialisation intra-session dans le middleware.

Sans verrou, deux ``tools/call`` concurrents d'un **même** client mutent l'état
partagé en parallèle (les tools sync tournent en threadpool) : un
``set_active_model`` peut changer la cible pendant qu'un ``full_audit`` calcule ses
findings → plan « findings A / cible B » scellé et applicable. Le middleware prend
un ``asyncio.Lock`` **par session** autour de l'exécution.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from audit_bim.mcp.middleware import SessionBindingMiddleware
from audit_bim.mcp.session import _store


def _ctx(session_id: str) -> SimpleNamespace:
    return SimpleNamespace(fastmcp_context=SimpleNamespace(session_id=session_id, client_id=None))


def _run(coro):
    return asyncio.run(coro)


def test_same_session_calls_are_serialized():
    mw = SessionBindingMiddleware()
    order: list[str] = []

    async def slow_call_next(_context):
        order.append("enter")
        await asyncio.sleep(0.03)
        order.append("exit")
        return "ok"

    async def drive():
        ctx = _ctx("sess-A")
        await asyncio.gather(
            mw.on_call_tool(ctx, slow_call_next),
            mw.on_call_tool(ctx, slow_call_next),
        )

    _run(drive())
    # Sérialisé : le 2e n'entre qu'après la sortie du 1er.
    assert order == ["enter", "exit", "enter", "exit"]


def test_different_sessions_run_concurrently():
    mw = SessionBindingMiddleware()
    order: list[str] = []

    async def slow_call_next(_context):
        order.append("enter")
        await asyncio.sleep(0.03)
        order.append("exit")
        return "ok"

    async def drive():
        await asyncio.gather(
            mw.on_call_tool(_ctx("sess-1"), slow_call_next),
            mw.on_call_tool(_ctx("sess-2"), slow_call_next),
        )

    _run(drive())
    # Concurrent : les deux entrent avant que l'un ne sorte.
    assert order == ["enter", "enter", "exit", "exit"]


def test_lock_is_released_on_exception():
    # Une exception dans un appel ne doit pas laisser le verrou pris (sinon le
    # tool suivant de la même session resterait bloqué à jamais).
    mw = SessionBindingMiddleware()

    async def boom(_context):
        raise RuntimeError("boom")

    async def ok(_context):
        return "ok"

    async def drive():
        ctx = _ctx("sess-X")
        try:
            await mw.on_call_tool(ctx, boom)
        except RuntimeError:
            pass
        # le verrou doit être libre → cet appel aboutit sans blocage
        return await asyncio.wait_for(mw.on_call_tool(ctx, ok), timeout=1.0)

    assert _run(drive()) == "ok"


def test_current_session_bound_and_reset():
    from audit_bim.mcp.session import current_session

    mw = SessionBindingMiddleware()

    async def check(_context):
        # pendant l'appel, current_session pointe la bonne session
        assert current_session.get() is _store.get("sess-B")
        return "ok"

    async def drive():
        return await mw.on_call_tool(_ctx("sess-B"), check)

    assert _run(drive()) == "ok"
