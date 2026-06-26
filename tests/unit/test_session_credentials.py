"""Store de credentials par session (couche 2 du modèle endpoint + token)."""

from __future__ import annotations

import time

import pytest

from audit_bim.mcp import session_credentials as sc
from audit_bim.mcp.session_credentials import CredentialError, SetupSessionStore, split_token


def _create(store: SetupSessionStore, **over):
    kw = dict(api_key="K", cloud_id=1, project_id=2, model_id=3, phase="DOE")
    kw.update(over)
    return store.create(**kw)


def test_create_returns_session_id_and_compound_token():
    store = SetupSessionStore()
    session_id, token = _create(store)
    assert token.startswith(session_id + ".")
    sid, secret = split_token(token)
    assert sid == session_id and secret


def test_store_never_keeps_raw_secret():
    store = SetupSessionStore()
    _, token = _create(store)
    _, secret = split_token(token)
    # Le secret brut n'apparaît nulle part dans l'état interne du store.
    blob = repr(store.__dict__)
    assert secret not in blob


def test_resolve_valid_token():
    store = SetupSessionStore()
    _, token = _create(store, model_id=42)
    rec = store.resolve_token(token)
    assert rec.model_id == "42"
    assert rec.phase.value == "DOE"


def test_invalid_secret_refused():
    store = SetupSessionStore()
    session_id, _ = _create(store)
    with pytest.raises(CredentialError):
        store.get_session(session_id, "wrong-secret")


def test_unknown_session_refused():
    store = SetupSessionStore()
    with pytest.raises(CredentialError):
        store.get_session("nope", "secret")


def test_malformed_token_refused():
    store = SetupSessionStore()
    with pytest.raises(CredentialError):
        store.resolve_token("no-dot-here")
    with pytest.raises(CredentialError):
        store.resolve_token(None)


def test_expired_token_refused(monkeypatch):
    store = SetupSessionStore(ttl_s=3600)
    _, token = _create(store)
    # Avance l'horloge au-delà du TTL.
    real_now = time.time()
    monkeypatch.setattr(sc.time, "time", lambda: real_now + 7200)
    with pytest.raises(CredentialError):
        store.resolve_token(token)


def test_revoke_then_refused():
    store = SetupSessionStore()
    session_id, token = _create(store)
    _, secret = split_token(token)
    assert store.revoke(session_id, secret) is True
    with pytest.raises(CredentialError):
        store.resolve_token(token)
    # Idempotent : seconde révocation renvoie False sans lever.
    assert store.revoke(session_id, secret) is False


def test_revoke_wrong_secret_refused():
    store = SetupSessionStore()
    session_id, _ = _create(store)
    with pytest.raises(CredentialError):
        store.revoke(session_id, "wrong")


def test_two_sessions_isolated():
    store = SetupSessionStore()
    _, t1 = _create(store, model_id=111)
    _, t2 = _create(store, model_id=222)
    assert store.resolve_token(t1).model_id == "111"
    assert store.resolve_token(t2).model_id == "222"


def test_invalid_phase_refused():
    store = SetupSessionStore()
    with pytest.raises(CredentialError):
        _create(store, phase="NOPE")


def test_missing_required_field_refused():
    store = SetupSessionStore()
    with pytest.raises(CredentialError):
        _create(store, api_key="")
    with pytest.raises(CredentialError):
        _create(store, model_id="")


def test_info_is_non_sensitive():
    store = SetupSessionStore()
    _, token = _create(store, api_key="SECRET_KEY")
    rec = store.resolve_token(token)
    info = store.info(rec)
    assert info.model_id == "3"
    assert info.expires_in_s > 0
    # La vue ne porte aucune clé / secret.
    assert "SECRET_KEY" not in repr(info)
