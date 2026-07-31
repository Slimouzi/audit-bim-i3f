"""Tests unitaires des **étapes nommées** de ``full_audit`` (PR2 §2c).

``full_audit`` est décomposé en fonctions d'étape testables ; le tool n'est plus
qu'un orchestrateur court. On vérifie ici chaque étape isolément — la forme du
payload et le comportement bout-en-bout restent couverts par
``test_mcp_full_audit_target`` / ``test_mcp_model_identity``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from audit_bim.mcp import tools_audit as ta
from audit_bim.mcp.session import _Session, current_session


@pytest.fixture
def _session():
    """État de session isolé : le proxy ``_State`` route vers cet objet."""
    sess = _Session()
    token = current_session.set(sess)
    try:
        yield sess
    finally:
        current_session.reset(token)


# ── _fa_resolve_push_mode ─────────────────────────────────────────────────────
def test_push_mode_ask_returns_needs_user_choice():
    out = ta._fa_resolve_push_mode("ask")
    assert isinstance(out, dict) and out["status"] == "needs_user_choice"
    assert set(out["options"]) == {"bcf", "smartview", "both", "none"}


def test_push_mode_default_empty_is_none():
    assert ta._fa_resolve_push_mode("") == "none"


@pytest.mark.parametrize("m", ["bcf", "smartview", "both", "none", "BCF", "Both"])
def test_push_mode_valid_passthrough_lowercased(m):
    assert ta._fa_resolve_push_mode(m) == m.lower()


def test_push_mode_invalid_raises():
    with pytest.raises(ValueError, match="push_mode invalide"):
        ta._fa_resolve_push_mode("zzz")


# ── _fa_assert_expected_model (contrôle d'identité, étape 3c) ──────────────────
def _state_with_model(name, model_id="m1"):
    return SimpleNamespace(model={"name": name, "id": model_id})


def test_assert_expected_model_none_is_noop():
    ta._fa_assert_expected_model(None)  # ne lève pas


def test_assert_expected_model_match_ok(_session):
    _session.snapshot = _state_with_model("Maquette LIFFRÉ DOE.ifc")
    ta._fa_assert_expected_model("liffre")  # accent/casse-insensible → ne lève pas


def test_assert_expected_model_mismatch_raises_before_deliverables(_session):
    _session.snapshot = _state_with_model("Autre projet.ifc")
    with pytest.raises(ValueError, match="Modèle actif inattendu"):
        ta._fa_assert_expected_model("LIFFRE")


# ── _fa_prepare_publication (étape 6) ─────────────────────────────────────────
@pytest.mark.parametrize(
    "mode,keys",
    [
        ("none", {"push_mode"}),
        ("bcf", {"push_mode", "bcf_plan"}),
        ("smartview", {"push_mode", "smart_views_plan"}),
        ("both", {"push_mode", "bcf_plan", "smart_views_plan"}),
    ],
)
def test_prepare_publication_keys_per_mode(mode, keys):
    with (
        patch.object(ta, "prepare_bcf_topics", return_value={"plan": "bcf"}),
        patch.object(ta, "prepare_smart_views_plan", return_value={"plan": "sv"}),
    ):
        pub = ta._fa_prepare_publication(mode)
    assert set(pub) == keys and pub["push_mode"] == mode


# ── _fa_build_payload (étape 7b — forme gelée) ────────────────────────────────
def test_build_payload_shape_and_next_step(_session):
    _session.result = SimpleNamespace(summary=lambda: {"n_findings": 3})
    out = ta._fa_build_payload("none", "w.docx", "x.xlsx", "f.json", {"push_mode": "none"})
    assert out == {
        "summary": {"n_findings": 3},
        "deliverables": {"word": "w.docx", "xlsx": "x.xlsx", "findings_json": "f.json"},
        "publication": {"push_mode": "none"},
    }
    assert "next_step" not in out  # mode 'none' → pas de next_step
    out_bcf = ta._fa_build_payload("bcf", "w.docx", "x.xlsx", "f.json", {"push_mode": "bcf"})
    assert "next_step" in out_bcf and "apply_bcf_topics" in out_bcf["next_step"]
