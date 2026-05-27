"""Tests de la politique de préservation de cible dans ``full_audit``.

Contexte : avant ce fix, ``full_audit(model_id=None)`` appelait
inconditionnellement ``set_active_model(model_id=None)`` qui retombait
sur ``config.MODEL_ID`` (issu de ``.env``). Conséquence : si
l'utilisateur avait préalablement posé une cible explicite
(``set_active_model(model_id="1673781")``) puis validé son identité
via ``verify_active_model``, ``full_audit`` écrasait silencieusement
cette cible avec la valeur d'env — risque opérationnel direct.

Politique testée :

- IDs explicites → ``set_active_model`` appelé (cible recadrée).
- Aucun ID + ``_State.client`` présent → cible préservée, pas de
  ``set_active_model``.
- Aucun ID + pas de client → fallback ``.env`` via ``set_active_model``
  (comportement historique).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.session import _Session, current_session
from audit_bim.requirements.models import BIMPhase

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
    """BIMDataClient minimal pour les tests."""

    def __init__(self, cloud_id="c", project_id="p", model_id="m"):
        self.cloud_id = cloud_id
        self.project_id = project_id
        self.model_id = model_id


def _snapshot_with_model(name: str, model_id: str = "42") -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "Projet test"},
        model={"id": model_id, "name": name, "modified_date": "2026-05-26"},
    ).index()


# ── Tests ──────────────────────────────────────────────────────────────


class TestFullAuditPreservesActiveTarget:
    def test_preserves_target_when_no_ids_and_client_present(
        self, _isolated_session, tmp_path, monkeypatch
    ):
        """Scénario type :
        1. set_active_model(model_id="1673781")
        2. verify_active_model(...) OK
        3. full_audit(model_id=None, expected_model_name="...")

        Doit garder ``model_id == "1673781"``, *pas* revenir au
        ``MODEL_ID`` du ``.env``.
        """
        # Pré-condition : utilisateur a posé une cible explicite +
        # snapshot chargé via verify_active_model.
        _isolated_session.client = _FakeClient(model_id="1673781")
        _isolated_session.cloud_id = "cloud-actif"
        _isolated_session.project_id = "projet-actif"
        _isolated_session.model_id = "1673781"
        _isolated_session.phase = BIMPhase.DOE
        snap = _snapshot_with_model("19_rue_Marc_Antoine_Petit.ifc", model_id="1673781")
        _isolated_session.snapshot = snap

        # On simule un ``.env`` qui pointe sur une AUTRE cible — c'est
        # exactement le piège que le fix doit éviter.
        monkeypatch.setattr(mcp_server.config, "CLOUD_ID", "cloud-ENV")
        monkeypatch.setattr(mcp_server.config, "PROJECT_ID", "projet-ENV")
        monkeypatch.setattr(mcp_server.config, "MODEL_ID", "MODEL_ID_ENV")

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
            patch.object(mcp_server, "run_audit", return_value=_FakeAuditResult()) as m_run,
            patch.object(mcp_server, "build_report_context") as m_ctx,
            patch.object(mcp_server, "merge_user_context") as m_merge,
            patch.object(mcp_server, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(mcp_server, "write_word_report", return_value=tmp_path / "x.docx"),
            patch.object(mcp_server, "push_bcf_topics", return_value=[]),
            patch.object(mcp_server, "push_smart_views", return_value=[]),
        ):
            m_ctx.return_value = object()
            m_merge.return_value = object()

            out = mcp_server.full_audit(
                cloud_id=None,
                project_id=None,
                model_id=None,
                push_mode="none",
                expected_model_name="19_rue_Marc_Antoine_Petit",
                output_dir=str(tmp_path),
                confirm_context=True,
            )

            # **Vérification clé** : set_active_model n'a PAS été appelé.
            m_set.assert_not_called()

            # run_audit a tourné avec la **phase active DOE**, pas le
            # défaut "PRO" du paramètre.
            m_run.assert_called_once()
            assert m_run.call_args.args[2] == BIMPhase.DOE

            # merge_user_context a reçu project_phase="DOE" — sinon le
            # rapport Word afficherait PRO alors que l'audit a tourné
            # en DOE (le bug que ce fix corrige).
            m_merge.assert_called_once()
            assert m_merge.call_args.kwargs["project_phase"] == "DOE"

        # Cible préservée — on n'est pas revenu sur les valeurs .env.
        assert _isolated_session.client.model_id == "1673781"
        assert _isolated_session.cloud_id == "cloud-actif"
        assert _isolated_session.project_id == "projet-actif"
        assert _isolated_session.model_id == "1673781"
        # La phase posée précédemment est préservée (DOE), pas écrasée
        # par le défaut "PRO" du paramètre.
        assert _isolated_session.phase == BIMPhase.DOE
        # L'audit s'est bien déroulé jusqu'au bout.
        assert "summary" in out

    def test_explicit_ids_trigger_set_active_model(self, _isolated_session, tmp_path, monkeypatch):
        """Si l'appelant fournit au moins un ID, ``set_active_model``
        est appelé (changement de cible explicite)."""
        _isolated_session.client = _FakeClient(model_id="old")
        _isolated_session.model_id = "old"
        snap = _snapshot_with_model("nouvelle_maquette.ifc", model_id="new")
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
                # Simule l'effet de set_active_model sur la session.
                _isolated_session.client = _FakeClient(model_id=kwargs.get("model_id") or "?")
                _isolated_session.model_id = kwargs.get("model_id")
                _isolated_session.phase = BIMPhase(kwargs.get("phase", "PRO").upper())

            m_set.side_effect = _fake_set

            mcp_server.full_audit(
                cloud_id=None,
                project_id=None,
                model_id="new",  # ID explicite → re-targeting demandé
                push_mode="none",
                output_dir=str(tmp_path),
                confirm_context=True,
            )

            m_set.assert_called_once()
            kwargs = m_set.call_args.kwargs
            assert kwargs["model_id"] == "new"

    def test_no_client_no_ids_falls_back_to_env(self, _isolated_session, tmp_path, monkeypatch):
        """Pas de cible active + pas d'IDs fournis → ``set_active_model``
        est appelé (avec les ``None`` qui retomberont sur ``.env`` dans
        l'implémentation de ``set_active_model``). Comportement
        historique préservé pour les sessions fraîches.
        """
        # Pré-condition : session vierge — pas de client en mémoire.
        assert _isolated_session.client is None
        snap = _snapshot_with_model("env_target.ifc", model_id="env-id")
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
                # set_active_model résout les None via .env et installe
                # un client — on simule le résultat minimal.
                _isolated_session.client = _FakeClient(model_id="env-id")
                _isolated_session.phase = BIMPhase.PRO

            m_set.side_effect = _fake_set

            mcp_server.full_audit(
                cloud_id=None,
                project_id=None,
                model_id=None,
                push_mode="none",
                output_dir=str(tmp_path),
                confirm_context=True,
            )

            m_set.assert_called_once()  # fallback historique préservé

    def test_explicit_phase_overrides_active_state(self, _isolated_session, tmp_path, monkeypatch):
        """Si l'appelant passe ``phase=...`` explicitement et que cette
        valeur diffère du défaut "PRO", elle gagne sur ``_State.phase``.
        Évite que le bypass "préserver la phase active" piège un
        utilisateur qui voulait délibérément changer de phase audit
        (cas légitime : passage AVP → PRO d'une même cible).
        """
        _isolated_session.client = _FakeClient(model_id="1673781")
        _isolated_session.phase = BIMPhase.AVP  # phase active
        snap = _snapshot_with_model("maquette.ifc", model_id="1673781")
        _isolated_session.snapshot = snap
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

            mcp_server.full_audit(
                cloud_id=None,
                project_id=None,
                model_id=None,
                phase="DCE",  # explicite, différent de PRO et de AVP
                push_mode="none",
                output_dir=str(tmp_path),
                confirm_context=True,
            )

            # Cible toujours préservée (pas d'IDs fournis).
            m_set.assert_not_called()
            # Mais la phase explicite DCE gagne sur AVP pour le contexte.
            assert m_merge.call_args.kwargs["project_phase"] == "DCE"
