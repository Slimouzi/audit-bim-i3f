"""Tests du garde-fou ``access_token`` en transport réseau (round 7)."""

from __future__ import annotations

import pytest

from audit_bim.mcp.security import (
    ALLOW_ACCESS_TOKEN_PARAM_ENV,
    AccessTokenParamDisabledError,
    ensure_access_token_param_allowed,
    is_access_token_param_allowed,
    set_runtime_transport,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ALLOW_ACCESS_TOKEN_PARAM_ENV, raising=False)
    set_runtime_transport("stdio")  # reset entre chaque test


class TestIsAccessTokenParamAllowed:
    def test_default_stdio_allowed(self):
        set_runtime_transport("stdio")
        assert is_access_token_param_allowed() is True

    def test_default_unknown_transport_refused(self):
        # PR3 §3a — transport NON déclaré (montage ASGI custom) → fail-closed.
        set_runtime_transport("")
        assert is_access_token_param_allowed() is False

    def test_default_script_mode_allowed(self):
        # Entrypoints locaux (runners/cli) se déclarent "script" → permissif.
        set_runtime_transport("script")
        assert is_access_token_param_allowed() is True

    @pytest.mark.parametrize("transport", ["http", "sse", "streamable-http"])
    def test_default_network_refused(self, transport):
        set_runtime_transport(transport)
        assert is_access_token_param_allowed() is False

    def test_env_true_overrides_network_default(self, monkeypatch):
        set_runtime_transport("http")
        monkeypatch.setenv(ALLOW_ACCESS_TOKEN_PARAM_ENV, "true")
        assert is_access_token_param_allowed() is True

    def test_env_false_overrides_stdio_default(self, monkeypatch):
        set_runtime_transport("stdio")
        monkeypatch.setenv(ALLOW_ACCESS_TOKEN_PARAM_ENV, "false")
        assert is_access_token_param_allowed() is False

    @pytest.mark.parametrize("val", ["1", "TRUE", "yes", "on"])
    def test_env_truthy_variants(self, monkeypatch, val):
        set_runtime_transport("http")
        monkeypatch.setenv(ALLOW_ACCESS_TOKEN_PARAM_ENV, val)
        assert is_access_token_param_allowed() is True


class TestEnsureAccessTokenParamAllowed:
    def test_stdio_passes(self):
        set_runtime_transport("stdio")
        ensure_access_token_param_allowed()  # ne lève pas

    def test_http_refused_by_default(self):
        set_runtime_transport("http")
        with pytest.raises(AccessTokenParamDisabledError, match="refusé"):
            ensure_access_token_param_allowed()

    def test_http_passes_with_opt_in(self, monkeypatch):
        set_runtime_transport("http")
        monkeypatch.setenv(ALLOW_ACCESS_TOKEN_PARAM_ENV, "true")
        ensure_access_token_param_allowed()

    def test_is_permission_error(self):
        # Subclass de PermissionError pour découpler les callers
        set_runtime_transport("http")
        with pytest.raises(PermissionError):
            ensure_access_token_param_allowed()


class TestServerToolsCallGate:
    """Vérifie que ``set_active_model`` et ``full_audit`` appellent la
    garde quand ``access_token`` est fourni."""

    def test_set_active_model_refuses_token_on_http(self, monkeypatch):
        from audit_bim.profiles.i3f.tools_session import set_active_model

        set_runtime_transport("http")
        # On veut juste vérifier que la garde déclenche AVANT
        # l'instanciation BIMDataClient — pas de mocking BIMData
        # nécessaire.
        with pytest.raises(AccessTokenParamDisabledError):
            set_active_model(
                cloud_id="c",
                project_id="p",
                model_id="m",
                access_token="user-bearer-token",
            )

    def test_set_active_model_passes_without_token(self, monkeypatch):
        # Sans access_token, la garde n'est pas appelée — la suite peut
        # échouer pour d'autres raisons (BIMData unreachable), on n'en
        # teste que l'absence de levée d'AccessTokenParamDisabledError.
        from audit_bim.mcp.session import _Session, current_session
        from audit_bim.profiles.i3f.tools_session import set_active_model

        set_runtime_transport("http")
        sess = _Session()
        token = current_session.set(sess)
        try:
            # On accepte qu'une autre exception lève (BIMDataAuthError,
            # ValueError sur config manquante…), tant que ce n'est pas
            # AccessTokenParamDisabledError.
            try:
                set_active_model(cloud_id="c", project_id="p", model_id="m")
            except AccessTokenParamDisabledError:
                pytest.fail("La garde ne devrait pas se déclencher sans token")
            except Exception:
                pass  # autre raison d'échec — non testée ici
        finally:
            current_session.reset(token)

    def test_full_audit_refuses_token_on_http(self):
        from audit_bim.profiles.i3f.tools_audit import full_audit

        set_runtime_transport("http")
        # ``push_mode`` arbitraire — la garde doit casser avant la
        # vérification de push_mode.
        with pytest.raises(AccessTokenParamDisabledError):
            full_audit(
                cloud_id="c",
                project_id="p",
                model_id="m",
                push_mode="none",
                access_token="user-token",
            )
