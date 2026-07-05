"""Tests du module ``audit_bim.mcp.deprecation``."""

from __future__ import annotations

import logging

import pytest

from audit_bim.mcp.deprecation import (
    DEPRECATIONS,
    DeprecatedToolInfo,
    add_deprecation_marker,
    get_deprecation,
    log_deprecated_tool_call,
)

# ── DeprecatedToolInfo ──────────────────────────────────────────────────


class TestDeprecatedToolInfo:
    def test_minimal(self):
        info = DeprecatedToolInfo(tool_name="t", use_instead="new_t")
        assert info.tool_name == "t"
        assert info.use_instead == "new_t"
        assert info.removal_version is None
        assert info.migration_hint is None
        assert info.legacy_status == "deprecated"

    def test_frozen(self):
        info = DeprecatedToolInfo(tool_name="t", use_instead="new_t")
        with pytest.raises((AttributeError, TypeError)):
            info.tool_name = "altered"  # type: ignore[misc]


# ── add_deprecation_marker ──────────────────────────────────────────────


class TestAddDeprecationMarker:
    def test_minimal_marker_on_existing_payload(self):
        info = DeprecatedToolInfo(tool_name="old", use_instead="new")
        out = add_deprecation_marker({"n": 3}, info)
        assert out["n"] == 3
        assert out["deprecated"] is True
        assert out["use_instead"] == "new"
        assert out["legacy_status"] == "deprecated"
        assert "deprecation_note" in out

    def test_none_payload_creates_dict(self):
        info = DeprecatedToolInfo(tool_name="old", use_instead="new")
        out = add_deprecation_marker(None, info)
        assert out["deprecated"] is True
        assert out["use_instead"] == "new"

    def test_non_dict_payload_wrapped_in_result(self):
        info = DeprecatedToolInfo(tool_name="old", use_instead="new")
        out = add_deprecation_marker([1, 2, 3], info)
        assert out["result"] == [1, 2, 3]
        assert out["deprecated"] is True

    def test_removal_version_included_when_set(self):
        info = DeprecatedToolInfo(tool_name="old", use_instead="new", removal_version="0.5.0")
        out = add_deprecation_marker({}, info)
        assert out["removal_version"] == "0.5.0"

    def test_removal_version_omitted_when_none(self):
        info = DeprecatedToolInfo(tool_name="old", use_instead="new")
        out = add_deprecation_marker({}, info)
        assert "removal_version" not in out

    def test_migration_hint_included_when_set(self):
        info = DeprecatedToolInfo(
            tool_name="old",
            use_instead="new",
            migration_hint="filtrer puis appliquer",
        )
        out = add_deprecation_marker({}, info)
        assert out["migration_hint"] == "filtrer puis appliquer"

    def test_legacy_status_propagated(self):
        info = DeprecatedToolInfo(
            tool_name="old", use_instead="new", legacy_status="legacy_wrapper"
        )
        out = add_deprecation_marker({}, info)
        assert out["legacy_status"] == "legacy_wrapper"


# ── log_deprecated_tool_call ────────────────────────────────────────────


class TestLogDeprecatedToolCall:
    def test_logs_info_level(self, caplog):
        info = DeprecatedToolInfo(tool_name="old", use_instead="new")
        with caplog.at_level(logging.INFO, logger="audit_bim.mcp.deprecation"):
            log_deprecated_tool_call(info)
        msgs = [r.getMessage() for r in caplog.records]
        assert any("deprecated tool called: old" in m for m in msgs)
        assert any("prefer new" in m for m in msgs)

    def test_extra_context_included(self, caplog):
        info = DeprecatedToolInfo(tool_name="old", use_instead="new")
        with caplog.at_level(logging.INFO, logger="audit_bim.mcp.deprecation"):
            log_deprecated_tool_call(info, extra={"legacy_execute": True})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "legacy_execute" in msgs

    def test_secret_scrubbed_from_extra(self, caplog):
        """Defense-in-depth : un secret dans extra ne doit pas fuiter."""
        info = DeprecatedToolInfo(tool_name="old", use_instead="new")
        with caplog.at_level(logging.INFO, logger="audit_bim.mcp.deprecation"):
            log_deprecated_tool_call(info, extra={"err": "Bearer abcd12345678efgh"})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "abcd12345678efgh" not in msgs
        assert "<scrub:" in msgs


# ── Registre DEPRECATIONS ───────────────────────────────────────────────


class TestRegistry:
    def test_registry_empty_since_v0_5_0(self):
        # Les 5 tools hérités ont été supprimés en v0.5.0 ; le registre est vidé
        # (l'infrastructure de dépréciation reste disponible pour le futur).
        assert DEPRECATIONS == {}

    def test_get_deprecation_removed_tool_returns_none(self):
        for name in (
            "create_bcf_topics",
            "create_smart_views",
            "apply_suggested_classifications",
            "suggest_classifications",
            "doe_enrich_model",
        ):
            assert get_deprecation(name) is None

    def test_get_deprecation_unknown(self):
        assert get_deprecation("does_not_exist") is None

    def test_removal_version_set(self):
        # Vacui aujourd'hui (registre vide) ; garde-fou si on réintroduit des
        # dépréciations.
        for info in DEPRECATIONS.values():
            assert info.removal_version is not None, (
                f"{info.tool_name}: removal_version doit être documentée"
            )
