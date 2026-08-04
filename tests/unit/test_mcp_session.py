"""Isolation par session — mécanique fournie par ``bim-mcp-runtime``.

Le magasin vient désormais du moteur ; ce module ne garde que ``_Session``,
dont les champs sont métier. Ces tests vérifient donc deux choses distinctes :
que le câblage est correct (préfixe d'environnement, fabrique), et que le
comportement observé côté serveur n'a pas bougé.
"""

from __future__ import annotations

import time

import pytest
from bim_mcp_runtime import SessionStore

from audit_bim.mcp import session as session_mod
from audit_bim.mcp.session import (
    _Session,
    _State,
    current_session,
)


def _store(**kwargs) -> SessionStore[_Session]:
    """Magasin du moteur, câblé comme celui du serveur.

    Le ``config`` porte le préfixe ``AUDIT_BIM`` : c'est lui qui garantit que
    les variables d'environnement historiques restent lues.
    """
    kwargs.setdefault("config", session_mod._runtime_config)
    return SessionStore(_Session, **kwargs)


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
        store = _store(ttl_s=60, max_sessions=10)
        s1 = store.get("alice")
        s2 = store.get("alice")
        assert s1 is s2

    def test_isolated_keys(self):
        store = _store(ttl_s=60, max_sessions=10)
        assert store.get("alice") is not store.get("bob")

    def test_ttl_eviction(self):
        store = _store(ttl_s=60, max_sessions=10)
        store.get("alice")
        # Force expiration
        store._touched["alice"] = time.monotonic() - 120
        store.get("bob")  # déclenche purge
        assert "alice" not in store.keys()

    def test_lru_eviction(self):
        store = _store(ttl_s=3600, max_sessions=2)
        store.get("a")
        store.get("b")
        store.get("a")  # rend "a" plus récent que "b"
        store.get("c")  # devrait évincer "b"
        assert set(store.keys()) == {"a", "c"}

    def test_clear(self):
        store = _store()
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
    """Le préfixe du serveur reste lu : aucune migration de déploiement."""

    def test_ttl_env_override(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_SESSION_TTL_S", "120")
        assert _store().ttl_s == 120

    def test_invalid_ttl_falls_back(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_SESSION_TTL_S", "not-a-number")
        assert _store().ttl_s == session_mod.DEFAULT_SESSION_TTL_S

    def test_max_sessions_env_override(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_MAX_SESSIONS", "4")
        assert _store().max_sessions == 4

    def test_env_names_are_unchanged(self):
        """Contrat public du serveur : les noms de variables ne bougent pas."""
        assert session_mod.SESSION_TTL_ENV == "AUDIT_BIM_SESSION_TTL_S"
        assert session_mod.MAX_SESSIONS_ENV == "AUDIT_BIM_MAX_SESSIONS"
        assert session_mod._runtime_config.env_name("SESSION_TTL_S") == (
            session_mod.SESSION_TTL_ENV
        )
