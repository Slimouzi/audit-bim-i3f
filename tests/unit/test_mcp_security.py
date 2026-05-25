"""Tests des briques :mod:`audit_bim.mcp.security`."""

from __future__ import annotations

import pytest

from audit_bim.mcp.security import (
    API_KEY_ENV,
    REQUIRE_API_KEY_ENV,
    WritesDisabledError,
    assert_startup_config,
    ensure_writes_allowed,
    is_api_key_required,
    is_prod,
    is_write_allowed,
    scrub,
    set_runtime_transport,
    verify_api_key,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Repart d'un env propre + runtime transport stdio pour chaque test."""
    for var in (
        API_KEY_ENV,
        REQUIRE_API_KEY_ENV,
        "AUDIT_BIM_ENV",
        "AUDIT_BIM_ALLOW_WRITES",
    ):
        monkeypatch.delenv(var, raising=False)
    # Reset le runtime transport (les autres tests d'intégration peuvent
    # l'avoir mis à autre chose).
    set_runtime_transport("stdio")


# ── Flags ────────────────────────────────────────────────────────────────


class TestEnvFlags:
    def test_is_prod_false_default(self):
        assert is_prod() is False

    @pytest.mark.parametrize("val", ["production", "prod", "PROD"])
    def test_is_prod_truthy(self, monkeypatch, val):
        monkeypatch.setenv("AUDIT_BIM_ENV", val)
        assert is_prod() is True

    def test_is_api_key_required_default(self):
        assert is_api_key_required() is False

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
    def test_is_api_key_required_truthy(self, monkeypatch, val):
        monkeypatch.setenv(REQUIRE_API_KEY_ENV, val)
        assert is_api_key_required() is True

    def test_is_api_key_required_via_prod(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_ENV", "production")
        assert is_api_key_required() is True

    def test_is_write_allowed_default_true_in_stdio(self):
        # Mode dev / stdio par défaut
        set_runtime_transport("stdio")
        assert is_write_allowed() is True

    def test_is_write_allowed_default_false_in_http(self):
        set_runtime_transport("http")
        assert is_write_allowed() is False

    def test_is_write_allowed_default_false_in_sse(self):
        set_runtime_transport("sse")
        assert is_write_allowed() is False

    def test_is_write_allowed_default_false_in_streamable_http(self):
        set_runtime_transport("streamable-http")
        assert is_write_allowed() is False

    def test_is_write_allowed_env_overrides_transport(self, monkeypatch):
        # En HTTP, défaut = False ; on peut forcer True via env
        set_runtime_transport("http")
        monkeypatch.setenv("AUDIT_BIM_ALLOW_WRITES", "true")
        assert is_write_allowed() is True

    def test_is_write_allowed_env_explicit_false_in_stdio(self, monkeypatch):
        # Et inversement : en stdio on peut désactiver explicitement
        set_runtime_transport("stdio")
        monkeypatch.setenv("AUDIT_BIM_ALLOW_WRITES", "false")
        assert is_write_allowed() is False


# ── ensure_writes_allowed ────────────────────────────────────────────────


class TestEnsureWritesAllowed:
    def test_passes_when_writes_allowed(self):
        ensure_writes_allowed("create_bcf_topics")  # ne lève pas

    def test_blocks_when_writes_disabled(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_ALLOW_WRITES", "false")
        with pytest.raises(WritesDisabledError, match="désactivées"):
            ensure_writes_allowed("doe_enrich_model")

    def test_is_permission_error(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_ALLOW_WRITES", "false")
        with pytest.raises(PermissionError):
            ensure_writes_allowed("apply_classifications")


# ── assert_startup_config ────────────────────────────────────────────────


class TestStartupConfig:
    def test_stdio_always_ok(self):
        # stdio = pas de réseau, pas de contrainte
        assert_startup_config(transport="stdio")

    def test_http_dev_without_key_ok(self, caplog):
        with caplog.at_level("WARNING", logger="audit_bim.mcp.security"):
            assert_startup_config(transport="http", host="127.0.0.1")
        assert any("API_KEY non défini" in r.message for r in caplog.records)

    def test_prod_http_without_key_refuses(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_ENV", "production")
        with pytest.raises(RuntimeError, match="AUDIT_BIM_API_KEY"):
            assert_startup_config(transport="http", host="127.0.0.1")

    def test_prod_http_with_key_and_input_dir_ok(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUDIT_BIM_ENV", "production")
        monkeypatch.setenv("AUDIT_BIM_API_KEY", "secret")
        monkeypatch.setenv("AUDIT_INPUT_DIR", str(tmp_path))
        assert_startup_config(transport="http", host="127.0.0.1")

    def test_require_flag_refuses_without_key(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BIM_REQUIRE_API_KEY", "true")
        with pytest.raises(RuntimeError):
            assert_startup_config(transport="streamable-http", host="127.0.0.1")

    def test_refuses_bind_all_interfaces_without_prod(self):
        with pytest.raises(RuntimeError, match="0.0.0.0"):
            assert_startup_config(transport="http", host="0.0.0.0")

    def test_bind_all_interfaces_allowed_in_prod_with_key_and_input_dir(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("AUDIT_BIM_ENV", "production")
        monkeypatch.setenv("AUDIT_BIM_API_KEY", "secret")
        monkeypatch.setenv("AUDIT_INPUT_DIR", str(tmp_path))
        assert_startup_config(transport="http", host="0.0.0.0")

    def test_prod_http_without_input_dir_refused(self, monkeypatch):
        # Round 3 review : AUDIT_INPUT_DIR doit être obligatoire en prod
        # réseau, au même titre que la clé service.
        monkeypatch.setenv("AUDIT_BIM_ENV", "production")
        monkeypatch.setenv("AUDIT_BIM_API_KEY", "secret")
        monkeypatch.delenv("AUDIT_INPUT_DIR", raising=False)
        with pytest.raises(RuntimeError, match="AUDIT_INPUT_DIR"):
            assert_startup_config(transport="http", host="127.0.0.1")

    def test_require_flag_without_input_dir_refused(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUDIT_BIM_REQUIRE_API_KEY", "true")
        monkeypatch.setenv("AUDIT_BIM_API_KEY", "secret")
        monkeypatch.delenv("AUDIT_INPUT_DIR", raising=False)
        with pytest.raises(RuntimeError, match="AUDIT_INPUT_DIR"):
            assert_startup_config(transport="http", host="127.0.0.1")

    def test_prod_http_with_full_config_ok(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUDIT_BIM_ENV", "production")
        monkeypatch.setenv("AUDIT_BIM_API_KEY", "secret")
        monkeypatch.setenv("AUDIT_INPUT_DIR", str(tmp_path))
        assert_startup_config(transport="http", host="127.0.0.1")


# ── verify_api_key ───────────────────────────────────────────────────────


class TestVerifyApiKey:
    def test_disabled_when_env_unset(self):
        # Pas d'env → la garde est désactivée, accepte tout (même None)
        assert verify_api_key(None) is True
        assert verify_api_key("anything") is True

    def test_rejects_missing(self, monkeypatch):
        monkeypatch.setenv(API_KEY_ENV, "secret")
        assert verify_api_key(None) is False
        assert verify_api_key("") is False

    def test_rejects_wrong(self, monkeypatch):
        monkeypatch.setenv(API_KEY_ENV, "secret")
        assert verify_api_key("nope") is False

    def test_accepts_matching(self, monkeypatch):
        monkeypatch.setenv(API_KEY_ENV, "secret")
        assert verify_api_key("secret") is True

    def test_constant_time_compare_resists_prefix(self, monkeypatch):
        # Test pragmatique : un préfixe correct ne passe pas
        monkeypatch.setenv(API_KEY_ENV, "abcdefgh")
        assert verify_api_key("abcd") is False


# ── scrub ────────────────────────────────────────────────────────────────


class TestScrub:
    def test_none(self):
        assert scrub(None) == "<none>"

    def test_hash_prefix(self):
        out = scrub("my-token")
        assert out.startswith("sha256:")
        assert len(out) == len("sha256:") + 8

    def test_deterministic(self):
        assert scrub("x") == scrub("x")
        assert scrub("x") != scrub("y")
