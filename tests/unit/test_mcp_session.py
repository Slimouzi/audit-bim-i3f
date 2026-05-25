"""Tests du :class:`_SessionStore` et de l'isolation par session."""

from __future__ import annotations

import time

import pytest

from audit_bim.mcp import session as session_mod
from audit_bim.mcp.session import (
    _Session,
    _SessionStore,
    _State,
    current_session,
)


class TestSession:
    def test_default_classification_system(self):
        s = _Session()
        assert s.classification_system == "UniFormat II"

    def test_ensures_raise_when_unset(self):
        s = _Session()
        with pytest.raises(RuntimeError, match="catalogue"):
            s.ensure_catalog()
        with pytest.raises(RuntimeError, match="BIMData"):
            s.ensure_client()
        with pytest.raises(RuntimeError, match="snapshot"):
            s.ensure_snapshot()
        with pytest.raises(RuntimeError, match="audit"):
            s.ensure_result()


class TestSessionStore:
    def test_get_creates_and_memoizes(self):
        store = _SessionStore(ttl_s=60, max_sessions=10)
        s1 = store.get("alice")
        s2 = store.get("alice")
        assert s1 is s2

    def test_isolated_keys(self):
        store = _SessionStore(ttl_s=60, max_sessions=10)
        assert store.get("alice") is not store.get("bob")

    def test_ttl_eviction(self):
        store = _SessionStore(ttl_s=60, max_sessions=10)
        store.get("alice")
        # Force expiration
        store._touched["alice"] = time.monotonic() - 120
        store.get("bob")  # déclenche purge
        assert "alice" not in store.keys()

    def test_lru_eviction(self):
        store = _SessionStore(ttl_s=3600, max_sessions=2)
        store.get("a")
        store.get("b")
        store.get("a")  # rend "a" plus récent que "b"
        store.get("c")  # devrait évincer "b"
        assert set(store.keys()) == {"a", "c"}

    def test_clear(self):
        store = _SessionStore()
        store.get("alice")
        assert store.clear("alice") is True
        assert store.clear("alice") is False


class TestStateProxy:
    def test_routes_to_current_session(self):
        s = _Session()
        s.cloud_id = "test-cloud"
        token = current_session.set(s)
        try:
            assert _State.cloud_id == "test-cloud"
        finally:
            current_session.reset(token)

    def test_writes_to_current_session(self):
        s = _Session()
        token = current_session.set(s)
        try:
            _State.project_id = "proj-X"
            assert s.project_id == "proj-X"
        finally:
            current_session.reset(token)

    def test_two_sessions_isolated(self):
        s_alice = _Session()
        s_bob = _Session()

        token = current_session.set(s_alice)
        try:
            _State.model_id = "alice-model"
        finally:
            current_session.reset(token)

        token = current_session.set(s_bob)
        try:
            _State.model_id = "bob-model"
            assert _State.model_id == "bob-model"
        finally:
            current_session.reset(token)

        assert s_alice.model_id == "alice-model"
        assert s_bob.model_id == "bob-model"


class TestEnvOverrides:
    def test_ttl_env_override(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_SESSION_TTL_S", "120")
        store = _SessionStore()
        assert store._ttl_s == 120

    def test_invalid_ttl_falls_back(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_SESSION_TTL_S", "not-a-number")
        store = _SessionStore()
        assert store._ttl_s == session_mod.DEFAULT_SESSION_TTL_S

    def test_max_sessions_env_override(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_MAX_SESSIONS", "4")
        store = _SessionStore()
        assert store._max == 4
