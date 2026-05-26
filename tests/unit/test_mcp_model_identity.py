"""Tests du garde-fou d'identité du modèle BIMData actif.

Couvre :

- les helpers purs ``normalize_model_name`` / ``model_matches_expected`` ;
- le tool MCP ``verify_active_model`` (chemins ok / mismatch / sans
  snapshot) ;
- l'option ``expected_model_name`` de ``full_audit`` (interruption
  avant génération des livrables en cas de mismatch, comportement
  inchangé sans expected).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.model_identity import (
    model_matches_expected,
    normalize_model_name,
)
from audit_bim.mcp.session import _Session, current_session

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def _isolated_session():
    sess = _Session()
    token = current_session.set(sess)
    try:
        yield sess
    finally:
        current_session.reset(token)


class _FakeClient:
    """BIMDataClient minimal : on n'a besoin que de l'attribut ``model_id``."""

    def __init__(self, cloud_id="c", project_id="p", model_id="m"):
        self.cloud_id = cloud_id
        self.project_id = project_id
        self.model_id = model_id


def _snapshot_with_model(name: str, model_id: str = "42") -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "Projet test"},
        model={"id": model_id, "name": name, "modified_date": "2026-05-25"},
    ).index()


# ── Helpers purs ───────────────────────────────────────────────────────


class TestNormalizeModelName:
    def test_none_returns_empty(self):
        assert normalize_model_name(None) == ""

    def test_non_string_returns_empty(self):
        assert normalize_model_name(123) == ""  # type: ignore[arg-type]

    def test_strips_accents(self):
        assert normalize_model_name("LIFFRÉ") == "liffre"
        assert normalize_model_name("Façade éàùç") == "facade eauc"

    def test_lowercases(self):
        assert normalize_model_name("Maquette") == "maquette"

    def test_collapses_whitespace(self):
        assert normalize_model_name("  Maquette   BIM\tDOE  ") == "maquette bim doe"


class TestModelMatchesExpected:
    def test_match_substring_case_and_accent_insensitive(self):
        assert model_matches_expected("Maquette BIM - LIFFRÉ - DOE.ifc", "LIFFRE") is True

    def test_match_with_accented_expected(self):
        assert model_matches_expected("Maquette LIFFRE DOE.ifc", "Liffré") is True

    def test_mismatch(self):
        assert model_matches_expected("Autre projet.ifc", "LIFFRE") is False

    def test_empty_expected_disables_check(self):
        assert model_matches_expected("anything.ifc", "") is True
        assert model_matches_expected("anything.ifc", None) is True

    def test_empty_model_name_does_not_match_non_empty_expected(self):
        assert model_matches_expected(None, "LIFFRE") is False
        assert model_matches_expected("", "LIFFRE") is False

    def test_whitespace_only_expected_is_ignored(self):
        # Normalisation → vide → check désactivé.
        assert model_matches_expected("autre.ifc", "   ") is True


# ── verify_active_model ────────────────────────────────────────────────


class TestVerifyActiveModel:
    def test_ok_when_match(self, _isolated_session):
        _isolated_session.client = _FakeClient(model_id="abc")
        snap = _snapshot_with_model("Maquette BIM - LIFFRÉ - DOE.ifc", model_id="abc")
        with patch.object(mcp_server, "extract_snapshot", return_value=snap):
            res = mcp_server.verify_active_model(expected_model_name="LIFFRE")
        assert res["ok"] is True
        assert res["model_name"] == "Maquette BIM - LIFFRÉ - DOE.ifc"
        assert res["model_id"] == "abc"
        assert res["project_name"] == "Projet test"
        assert res["from_cache"] is False
        assert "conforme" in res["message"].lower()
        # Le tool a rafraîchi le snapshot en session.
        assert _isolated_session.snapshot is snap
        # Le tool ne touche pas _State.result.
        assert _isolated_session.result is None

    def test_ko_when_mismatch_does_not_touch_result(self, _isolated_session):
        _isolated_session.client = _FakeClient(model_id="zzz")
        snap = _snapshot_with_model("Autre projet.ifc", model_id="zzz")
        with patch.object(mcp_server, "extract_snapshot", return_value=snap):
            res = mcp_server.verify_active_model(expected_model_name="LIFFRE")
        assert res["ok"] is False
        assert "inattendu" in res["message"].lower()
        assert "liffre" in res["message"].lower()
        assert "autre projet" in res["message"].lower()
        assert _isolated_session.result is None

    def test_no_client_raises(self, _isolated_session):
        # Pas de set_active_model — _State.client est None.
        with pytest.raises(RuntimeError, match="BIMData"):
            mcp_server.verify_active_model(expected_model_name="LIFFRE")

    def test_empty_expected_raises(self, _isolated_session):
        _isolated_session.client = _FakeClient()
        with pytest.raises(ValueError, match="expected_model_name"):
            mcp_server.verify_active_model(expected_model_name="   ")

    def test_refresh_false_without_snapshot_raises(self, _isolated_session):
        _isolated_session.client = _FakeClient()
        # Pas de snapshot en session, refresh désactivé → message clair.
        with pytest.raises(RuntimeError, match="snapshot"):
            mcp_server.verify_active_model(
                expected_model_name="LIFFRE",
                refresh_snapshot=False,
            )

    def test_refresh_false_uses_existing_snapshot(self, _isolated_session):
        _isolated_session.client = _FakeClient()
        snap = _snapshot_with_model("Maquette LIFFRE DOE.ifc")
        _isolated_session.snapshot = snap
        with patch.object(mcp_server, "extract_snapshot") as m_extract:
            res = mcp_server.verify_active_model(
                expected_model_name="LIFFRE",
                refresh_snapshot=False,
            )
            m_extract.assert_not_called()
        assert res["ok"] is True
        assert res["from_cache"] is None

    def test_refresh_with_cache_returns_hit_flag(self, _isolated_session):
        _isolated_session.client = _FakeClient()
        snap = _snapshot_with_model("Maquette LIFFRE DOE.ifc")
        with (
            patch.object(
                mcp_server, "cached_extract_snapshot", return_value=(snap, True)
            ) as m_cached,
            patch.object(mcp_server, "extract_snapshot") as m_direct,
        ):
            res = mcp_server.verify_active_model(
                expected_model_name="LIFFRE",
                refresh_snapshot=True,
                use_cache=True,
            )
            m_cached.assert_called_once()
            m_direct.assert_not_called()
        assert res["ok"] is True
        assert res["from_cache"] is True


# ── full_audit guard ───────────────────────────────────────────────────


class TestFullAuditExpectedModelName:
    def test_mismatch_raises_before_reports(self, _isolated_session):
        """Le mismatch doit lever AVANT toute génération de livrable."""
        snap = _snapshot_with_model("Autre maquette.ifc")
        with (
            patch.object(mcp_server, "build_catalog") as m_catalog,
            patch.object(mcp_server, "set_active_model") as m_set,
            patch.object(mcp_server, "extract_snapshot", return_value=snap),
            patch.object(mcp_server, "run_audit") as m_run,
            patch.object(mcp_server, "write_xlsx_annex") as m_xlsx,
            patch.object(mcp_server, "write_word_report") as m_word,
        ):
            # set_active_model est mocké : il faut installer client + phase
            # dans la session manuellement pour atteindre l'étape snapshot.
            def _fake_set(**kwargs):
                _isolated_session.client = _FakeClient()
                from audit_bim.requirements.models import BIMPhase

                _isolated_session.phase = BIMPhase.PRO

            m_set.side_effect = _fake_set
            with pytest.raises(ValueError, match="Modèle actif inattendu"):
                mcp_server.full_audit(
                    cloud_id="c",
                    project_id="p",
                    model_id="m",
                    push_mode="none",
                    expected_model_name="LIFFRE",
                    # Bypass de la validation de contexte projet (PR #17) :
                    # on teste le garde-fou d'identité, pas la complétude
                    # du contexte AMO BIM.
                    confirm_context=True,
                )
            m_catalog.assert_called_once()
            m_run.assert_not_called()
            m_xlsx.assert_not_called()
            m_word.assert_not_called()

    def test_match_does_not_raise_for_guard(self, _isolated_session, tmp_path, monkeypatch):
        """Avec un nom conforme, le garde-fou laisse passer. On stoppe
        ensuite avant le filesystem en mockant l'audit.
        """
        snap = _snapshot_with_model("Maquette LIFFRÉ DOE.ifc")
        # Sandbox d'exports : on isole tout sous tmp_path.
        monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))

        class _FakeAuditResult:
            # Le snapshot est attaché car ``build_report_context`` (PR #17)
            # le lit pour produire le contexte projet du rapport.
            findings: list = []
            snapshot = snap

            def summary(self):
                return {"n_findings": 0}

        with (
            patch.object(mcp_server, "build_catalog"),
            patch.object(mcp_server, "set_active_model") as m_set,
            patch.object(mcp_server, "extract_snapshot", return_value=snap),
            patch.object(mcp_server, "run_audit", return_value=_FakeAuditResult()),
            patch.object(mcp_server, "build_report_context") as m_ctx,
            patch.object(mcp_server, "merge_user_context") as m_merge,
            patch.object(mcp_server, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(mcp_server, "write_word_report", return_value=tmp_path / "x.docx"),
            patch.object(mcp_server, "push_bcf_topics", return_value=[]),
            patch.object(mcp_server, "push_smart_views", return_value=[]),
        ):
            m_ctx.return_value = object()
            m_merge.return_value = object()

            def _fake_set(**kwargs):
                _isolated_session.client = _FakeClient()
                from audit_bim.requirements.models import BIMPhase

                _isolated_session.phase = BIMPhase.PRO

            m_set.side_effect = _fake_set
            # Pas d'exception attendue : si le garde-fou se déclenche
            # à tort, ValueError remonterait.
            out = mcp_server.full_audit(
                cloud_id="c",
                project_id="p",
                model_id="m",
                push_mode="none",
                expected_model_name="LIFFRE",
                output_dir=str(tmp_path),
                confirm_context=True,
            )
        assert "summary" in out

    def test_no_expected_keeps_legacy_behavior(self, _isolated_session, tmp_path, monkeypatch):
        """Sans expected_model_name, full_audit ne lève pas même si le
        nom du modèle ne ressemble à rien d'attendu.
        """
        snap = _snapshot_with_model("Quelque chose.ifc")
        monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))

        class _FakeAuditResult:
            findings: list = []
            snapshot = snap

            def summary(self):
                return {"n_findings": 0}

        with (
            patch.object(mcp_server, "build_catalog"),
            patch.object(mcp_server, "set_active_model") as m_set,
            patch.object(mcp_server, "extract_snapshot", return_value=snap),
            patch.object(mcp_server, "run_audit", return_value=_FakeAuditResult()),
            patch.object(mcp_server, "build_report_context") as m_ctx,
            patch.object(mcp_server, "merge_user_context") as m_merge,
            patch.object(mcp_server, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(mcp_server, "write_word_report", return_value=tmp_path / "x.docx"),
            patch.object(mcp_server, "push_bcf_topics", return_value=[]),
            patch.object(mcp_server, "push_smart_views", return_value=[]),
        ):
            m_ctx.return_value = object()
            m_merge.return_value = object()

            def _fake_set(**kwargs):
                _isolated_session.client = _FakeClient()
                from audit_bim.requirements.models import BIMPhase

                _isolated_session.phase = BIMPhase.PRO

            m_set.side_effect = _fake_set
            out = mcp_server.full_audit(
                cloud_id="c",
                project_id="p",
                model_id="m",
                push_mode="none",
                output_dir=str(tmp_path),
                confirm_context=True,
            )
        assert "summary" in out
