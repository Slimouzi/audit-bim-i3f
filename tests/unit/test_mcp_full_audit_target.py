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

from audit_bim import config as _config
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import tools_audit as mcp_server
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
        monkeypatch.setattr(_config, "CLOUD_ID", "cloud-ENV")
        monkeypatch.setattr(_config, "PROJECT_ID", "projet-ENV")
        monkeypatch.setattr(_config, "MODEL_ID", "MODEL_ID_ENV")

        monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))

        class _FakeAuditResult:
            findings: list = []
            snapshot = snap

            def summary(self):
                return {"n_findings": 0}

        with (
            patch.object(mcp_server, "build_catalog"),
            patch.object(mcp_server, "catalog_usable", return_value=(True, None)),
            patch.object(mcp_server, "set_active_model") as m_set,
            patch.object(mcp_server, "extract_snapshot", return_value=snap),
            patch.object(mcp_server, "run_audit", return_value=_FakeAuditResult()) as m_run,
            patch.object(mcp_server, "build_report_context") as m_ctx,
            patch.object(mcp_server, "merge_user_context") as m_merge,
            patch.object(mcp_server, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(mcp_server, "write_word_report", return_value=tmp_path / "x.docx"),
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

    @pytest.mark.parametrize(
        ("target_kwargs", "expected_key", "expected_value"),
        [
            ({"model_id": "new"}, "model_id", "new"),
            ({"cloud_id": "9", "project_id": "8", "model_id": "new"}, "cloud_id", "9"),
        ],
    )
    def test_explicit_target_triggers_set_active_model(
        self,
        _isolated_session,
        tmp_path,
        monkeypatch,
        target_kwargs,
        expected_key,
        expected_value,
    ):
        """Un ID ou une URL explicite recadre la cible via
        ``set_active_model``."""
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
            patch.object(mcp_server, "catalog_usable", return_value=(True, None)),
            patch.object(mcp_server, "set_active_model") as m_set,
            patch.object(mcp_server, "extract_snapshot", return_value=snap),
            patch.object(mcp_server, "run_audit", return_value=_FakeAuditResult()),
            patch.object(mcp_server, "build_report_context") as m_ctx,
            patch.object(mcp_server, "merge_user_context") as m_merge,
            patch.object(mcp_server, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(mcp_server, "write_word_report", return_value=tmp_path / "x.docx"),
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
                push_mode="none",
                output_dir=str(tmp_path),
                confirm_context=True,
                **target_kwargs,
            )

            m_set.assert_called_once()
            kwargs = m_set.call_args.kwargs
            assert kwargs[expected_key] == expected_value

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
            patch.object(mcp_server, "catalog_usable", return_value=(True, None)),
            patch.object(mcp_server, "set_active_model") as m_set,
            patch.object(mcp_server, "extract_snapshot", return_value=snap),
            patch.object(mcp_server, "run_audit", return_value=_FakeAuditResult()),
            patch.object(mcp_server, "build_report_context") as m_ctx,
            patch.object(mcp_server, "merge_user_context") as m_merge,
            patch.object(mcp_server, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(mcp_server, "write_word_report", return_value=tmp_path / "x.docx"),
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
            patch.object(mcp_server, "catalog_usable", return_value=(True, None)),
            patch.object(mcp_server, "set_active_model") as m_set,
            patch.object(mcp_server, "extract_snapshot", return_value=snap),
            patch.object(mcp_server, "run_audit", return_value=_FakeAuditResult()) as m_run,
            patch.object(mcp_server, "build_report_context") as m_ctx,
            patch.object(mcp_server, "merge_user_context") as m_merge,
            patch.object(mcp_server, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(mcp_server, "write_word_report", return_value=tmp_path / "x.docx"),
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

            # **Triple cohérence demandée par la revue CTO** : la phase
            # explicite DCE doit gagner partout — sinon on a une
            # divergence silencieuse entre l'audit exécuté et le rapport
            # publié.
            assert m_run.call_args.args[2] == BIMPhase.DCE
            assert m_merge.call_args.kwargs["project_phase"] == "DCE"

        # _State.phase a été ré-aligné à BIMPhase.DCE pour rester
        # cohérent avec l'audit qui vient de tourner.
        assert _isolated_session.phase == BIMPhase.DCE


class TestFullAuditNoCrossModelContextContamination:
    """P1 — un ``full_audit(model_id=<B>)`` dans une session où le modèle
    A est déjà chargé ne doit **jamais** proposer l'adresse, la description
    ou la phase du modèle A pour le rapport du modèle B.

    Avant le fix, les suggestions de contexte étaient calculées depuis
    ``_State.snapshot`` (modèle A) *avant* l'activation de la cible URL
    (modèle B). Le fix active la cible et charge son snapshot en tête de
    ``full_audit``, si bien que phase/adresse/description proviennent
    toujours du modèle réellement audité.
    """

    def test_url_target_context_never_leaks_from_previous_model(
        self, _isolated_session, tmp_path, monkeypatch
    ):
        # Modèle A déjà en session : phase DOE, description + adresse propres.
        snap_a = ModelSnapshot(
            project={"name": "MODELE-A", "description": "DESCRIPTION-A", "phase": "DOE"},
            model={"id": "AAA", "name": "modele_A.ifc"},
        ).index()
        _isolated_session.client = _FakeClient(model_id="AAA")
        _isolated_session.model_id = "AAA"
        _isolated_session.phase = BIMPhase.DOE
        _isolated_session.snapshot = snap_a

        # Modèle B — la cible URL. Phase APS, description distincte.
        snap_b = ModelSnapshot(
            project={"name": "MODELE-B", "description": "DESCRIPTION-B", "phase": "APS"},
            model={"id": "BBB", "name": "modele_B.ifc"},
        ).index()

        monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))

        def _fake_set(**kwargs):
            # Effet réel de set_active_model : bascule la session sur B et
            # invalide le snapshot (rechargé juste après par extract_snapshot).
            _isolated_session.client = _FakeClient(model_id="BBB")
            _isolated_session.model_id = "BBB"
            _isolated_session.phase = BIMPhase(kwargs.get("phase", "PRO").upper())
            _isolated_session.snapshot = None

        # L'adresse suggérée reflète le snapshot ACTIF au moment de l'appel :
        # c'est précisément l'ordre que le fix garantit.
        def _fake_addr():
            snap = _isolated_session.snapshot
            return f"ADDR-{(snap.model or {}).get('name')}" if snap is not None else None

        with (
            patch.object(mcp_server, "set_active_model", side_effect=_fake_set),
            patch.object(mcp_server, "extract_snapshot", return_value=snap_b),
            patch.object(mcp_server, "_snapshot_address_suggestion", side_effect=_fake_addr),
        ):
            out = mcp_server.full_audit(
                cloud_id="1",
                project_id="2",
                model_id="BBB",
                push_mode="none",
                output_dir=str(tmp_path),
                confirm_context=False,  # force le dialogue needs_context
            )

        # Le tool refuse en demandant le contexte → on inspecte les suggestions.
        assert out["status"] == "needs_context"
        q_by_key = {q["key"]: q for q in out["questions"]}

        # Adresse : celle de B, jamais de A.
        assert q_by_key["project_address"]["suggested_value"] == "ADDR-modele_B.ifc"
        # Description : celle de B, jamais de A.
        assert q_by_key["project_description"]["suggested_value"] == "DESCRIPTION-B"
        # Phase proposée : APS (modèle B), jamais DOE (modèle A).
        assert q_by_key["project_phase"]["suggested_value"] == "APS"

        # La session pointe bien sur B après l'activation en tête de fonction.
        assert _isolated_session.model_id == "BBB"


class TestForceRefreshSnapshotSemantics:
    """P2 — sémantique de ``force_refresh_snapshot`` documentée :

    - une **nouvelle cible explicite** (URL/IDs) force **toujours** une
      extraction fraîche, même avec ``force_refresh_snapshot=False`` (on ne
      peut pas réutiliser le snapshot d'un autre modèle) ;
    - une **cible préservée** avec un snapshot déjà en session **respecte**
      ``force_refresh_snapshot=False`` (pas d'extraction).
    """

    def test_explicit_target_forces_extraction_despite_flag_false(
        self, _isolated_session, tmp_path, monkeypatch
    ):
        # Session avec un snapshot du modèle A déjà chargé.
        snap_a = _snapshot_with_model("modele_A.ifc", model_id="AAA")
        _isolated_session.client = _FakeClient(model_id="AAA")
        _isolated_session.model_id = "AAA"
        _isolated_session.snapshot = snap_a

        snap_b = _snapshot_with_model("modele_B.ifc", model_id="BBB")
        monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))

        class _FakeAuditResult:
            findings: list = []
            snapshot = snap_b

            def summary(self):
                return {"n_findings": 0}

        def _fake_set(**kwargs):
            _isolated_session.client = _FakeClient(model_id="BBB")
            _isolated_session.model_id = "BBB"
            _isolated_session.phase = BIMPhase(kwargs.get("phase", "PRO").upper())
            _isolated_session.snapshot = None

        with (
            patch.object(mcp_server, "build_catalog"),
            patch.object(mcp_server, "catalog_usable", return_value=(True, None)),
            patch.object(mcp_server, "set_active_model", side_effect=_fake_set),
            patch.object(mcp_server, "extract_snapshot", return_value=snap_b) as m_extract,
            patch.object(mcp_server, "run_audit", return_value=_FakeAuditResult()),
            patch.object(mcp_server, "build_report_context", return_value=object()),
            patch.object(mcp_server, "merge_user_context", return_value=object()),
            patch.object(mcp_server, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(mcp_server, "write_word_report", return_value=tmp_path / "x.docx"),
        ):
            mcp_server.full_audit(
                cloud_id="1",
                project_id="2",
                model_id="BBB",
                force_refresh_snapshot=False,  # doit être outrepassé par la nouvelle cible
                push_mode="none",
                output_dir=str(tmp_path),
                confirm_context=True,
            )
            # Extraction fraîche forcée malgré le flag False : exactement une fois,
            # pour le nouveau modèle.
            m_extract.assert_called_once()
            assert _isolated_session.snapshot is snap_b

    def test_preserved_target_honors_flag_false(self, _isolated_session, tmp_path, monkeypatch):
        # Cible préservée + snapshot déjà chargé → aucune extraction.
        snap = _snapshot_with_model("maquette.ifc", model_id="1673781")
        _isolated_session.client = _FakeClient(model_id="1673781")
        _isolated_session.model_id = "1673781"
        _isolated_session.phase = BIMPhase.AVP
        _isolated_session.snapshot = snap
        monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))

        class _FakeAuditResult:
            findings: list = []
            snapshot = snap

            def summary(self):
                return {"n_findings": 0}

        with (
            patch.object(mcp_server, "build_catalog"),
            patch.object(mcp_server, "catalog_usable", return_value=(True, None)),
            patch.object(mcp_server, "set_active_model") as m_set,
            patch.object(mcp_server, "extract_snapshot", return_value=snap) as m_extract,
            patch.object(mcp_server, "run_audit", return_value=_FakeAuditResult()),
            patch.object(mcp_server, "build_report_context", return_value=object()),
            patch.object(mcp_server, "merge_user_context", return_value=object()),
            patch.object(mcp_server, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(mcp_server, "write_word_report", return_value=tmp_path / "x.docx"),
        ):
            mcp_server.full_audit(
                cloud_id=None,
                project_id=None,
                model_id=None,
                phase="AVP",
                force_refresh_snapshot=False,
                push_mode="none",
                output_dir=str(tmp_path),
                confirm_context=True,
            )
            m_set.assert_not_called()  # cible préservée
            m_extract.assert_not_called()  # flag False respecté (snapshot réutilisé)
