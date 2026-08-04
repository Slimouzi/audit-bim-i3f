"""Tests du garde-fou d'identité du modèle BIMData actif.

Couvre :

- le parsing et la résolution des URLs viewer BIMData ;
- les helpers purs ``normalize_model_name`` / ``model_matches_expected`` ;
- le tool MCP ``verify_active_model`` (chemins ok / mismatch / sans
  snapshot) ;
- l'option ``expected_model_name`` de ``full_audit`` (interruption
  avant génération des livrables en cas de mismatch, comportement
  inchangé sans expected).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from audit_bim.extraction.client import BIMDataAuthError
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.model_identity import (
    model_matches_expected,
    normalize_model_name,
    parse_bimdata_viewer_url,
    resolve_bimdata_target,
)
from audit_bim.mcp.session import _Session, current_session
from audit_bim.profiles.i3f import tools_audit, tools_session

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

    def __init__(
        self,
        cloud_id="c",
        project_id="p",
        model_id="m",
        access_token=None,
    ):
        self.cloud_id = cloud_id
        self.project_id = project_id
        self.model_id = model_id
        self.access_token = access_token


def _snapshot_with_model(
    name: str, model_id: str = "42", status: str | None = None
) -> ModelSnapshot:
    model = {"id": model_id, "name": name, "modified_date": "2026-05-25"}
    if status is not None:
        model["status"] = status
    return ModelSnapshot(
        project={"name": "Projet test"},
        model=model,
    ).index()


# ── Helpers purs ───────────────────────────────────────────────────────


class TestParseBimdataViewerUrl:
    URL = "https://platform.bimdata.io/spaces/33617/projects/2698917/viewer/1674450?window=3d"

    def test_extracts_ids_and_ignores_query_string(self):
        assert parse_bimdata_viewer_url(self.URL) == ("33617", "2698917", "1674450")

    def test_accepts_trailing_slash_and_fragment(self):
        url = "https://platform.bimdata.io/spaces/1/projects/2/viewer/3/?window=3d#issues"
        assert parse_bimdata_viewer_url(url) == ("1", "2", "3")

    @pytest.mark.parametrize(
        "url",
        [
            "http://platform.bimdata.io/spaces/1/projects/2/viewer/3",
            "https://example.com/spaces/1/projects/2/viewer/3",
            "https://platform.bimdata.io/spaces/1/projects/2",
            "https://platform.bimdata.io/spaces/cloud/projects/2/viewer/3",
            "not-a-url",
        ],
    )
    def test_rejects_non_bimdata_or_malformed_urls(self, url):
        with pytest.raises(ValueError, match="URL BIMData invalide"):
            parse_bimdata_viewer_url(url)


URL = "https://platform.bimdata.io/spaces/33617/projects/2698917/viewer/1674450?window=3d"


class TestResolveBimdataTarget:
    """Le runtime cible par IDs : resolve_bimdata_target ne résout PLUS d'URL
    (plus de résolveur caché). Il passe les IDs tels quels et refuse une URL."""

    def test_passes_explicit_ids_through(self):
        assert resolve_bimdata_target(cloud_id="c", project_id="p", model_id="m") == ("c", "p", "m")

    def test_rejects_url_pasted_into_model_id(self):
        with pytest.raises(ValueError, match="parse_bimdata_target"):
            resolve_bimdata_target(cloud_id=None, project_id=None, model_id=URL)


class TestParseBimdataTargetTool:
    """Nouveau tool : URL viewer → IDs, à appeler AVANT set_active_model."""

    def test_extracts_ids(self):
        assert tools_session.parse_bimdata_target(URL) == {
            "cloud_id": "33617",
            "project_id": "2698917",
            "model_id": "1674450",
        }

    def test_rejects_non_viewer_url(self):
        with pytest.raises(ValueError, match="URL BIMData invalide"):
            tools_session.parse_bimdata_target("https://example.com/nope")


class TestSetActiveModelExplicitIds:
    def test_ids_configure_target(self, _isolated_session):
        with patch.object(tools_session, "BIMDataClient", _FakeClient):
            result = tools_session.set_active_model(
                cloud_id="33617", project_id="2698917", model_id="1674450", phase="AVP"
            )
        assert (result["cloud_id"], result["project_id"], result["model_id"]) == (
            "33617",
            "2698917",
            "1674450",
        )
        assert _isolated_session.client.model_id == "1674450"

    def test_response_says_configured_not_ok(self, _isolated_session):
        # L'auth est CONFIGURÉE, pas prouvée — plus de « auth: ok » trompeur.
        with patch.object(tools_session, "BIMDataClient", _FakeClient):
            result = tools_session.set_active_model(cloud_id="1", project_id="2", model_id="3")
        assert result["auth"] == "configured"
        assert result["auth_status"] == "configured"
        assert result.get("auth") != "ok"
        assert "check_bimdata_access" in result["note"]

    def test_url_in_model_id_is_refused_with_redirect(self, _isolated_session):
        with patch.object(tools_session, "BIMDataClient", _FakeClient):
            with pytest.raises(ValueError, match="parse_bimdata_target"):
                tools_session.set_active_model(model_id=URL, phase="AVP")

    def test_parse_then_set_active_model_flow(self, _isolated_session):
        ids = tools_session.parse_bimdata_target(URL)
        with patch.object(tools_session, "BIMDataClient", _FakeClient):
            result = tools_session.set_active_model(phase="AVP", **ids)
        assert result["model_id"] == "1674450"
        assert _isolated_session.snapshot is None  # caches invalidés


def _wire_client(sess, client):
    sess.client = client
    sess.cloud_id, sess.project_id, sess.model_id = "1", "2", "3"


class TestCheckBimdataAccess:
    """Smoke test cible/auth : prouve l'accès réel via get_project + get_model,
    et donne un diagnostic clair sur 401 (au lieu d'un audit sur du vide)."""

    def test_ok_returns_ids_and_names(self, _isolated_session):
        client = MagicMock()
        client.get_project.return_value = {"name": "Projet X"}
        client.get_model.return_value = {"name": "M.ifc"}
        _wire_client(_isolated_session, client)
        out = tools_session.check_bimdata_access()
        assert out["ok"] is True
        assert (out["cloud_id"], out["project_id"], out["model_id"]) == ("1", "2", "3")
        assert out["project_name"] == "Projet X"
        assert out["model_name"] == "M.ifc"

    def test_401_returns_dict_not_raises(self, _isolated_session):
        # bimdata_read lève BIMDataAuthError (PermissionError), PAS requests.HTTPError,
        # pour 401/403 → le tool doit l'attraper et renvoyer un dict, pas remonter brut.
        client = MagicMock()
        client.get_project.side_effect = BIMDataAuthError(
            "BIMData 401 on /cloud/34140/project/3281472"
        )
        _wire_client(_isolated_session, client)
        out = tools_session.check_bimdata_access()  # ne doit PAS lever
        assert out["ok"] is False
        assert "rejeté" in out["error"] and "401" in out["error"]
        # Diagnostic honnête : la source/le schéma d'auth sont remontés.
        assert "auth_source" in out and "auth_scheme" in out

    def test_403_reports_missing_rights(self, _isolated_session):
        client = MagicMock()
        client.get_project.side_effect = BIMDataAuthError(
            "BIMData 403 on /cloud/34140/project/3281472"
        )
        _wire_client(_isolated_session, client)
        out = tools_session.check_bimdata_access()
        assert out["ok"] is False
        assert "403" in out["error"] and "droits" in out["error"]

    def test_404_reports_target_not_found(self, _isolated_session):
        # 404 passe par raise_for_status → requests.HTTPError (pas BIMDataAuthError).
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        client.get_project.side_effect = requests.HTTPError(response=resp)
        _wire_client(_isolated_session, client)
        out = tools_session.check_bimdata_access()
        assert out["ok"] is False
        assert "404" in out["error"]

    def test_no_client_raises(self, _isolated_session):
        with pytest.raises(RuntimeError):
            tools_session.check_bimdata_access()

    def test_reports_api_key_auth_on_success(self, _isolated_session, monkeypatch):
        # Déploiement clé serveur : seul BIMDATA_API_KEY configuré → ApiKey.
        _set_config_auth(monkeypatch, api_key="svc-key")
        client = MagicMock()
        client.get_project.return_value = {"name": "Projet X"}
        client.get_model.return_value = {"name": "M.ifc"}
        _wire_client(_isolated_session, client)
        out = tools_session.check_bimdata_access()
        assert out["ok"] is True
        assert out["auth_source"] == "BIMDATA_API_KEY"
        assert out["auth_scheme"] == "ApiKey"
        # Le secret lui-même n'est jamais renvoyé.
        assert "svc-key" not in str(out)

    def test_reports_auth_even_on_401(self, _isolated_session, monkeypatch):
        _set_config_auth(monkeypatch, api_key="svc-key")
        client = MagicMock()
        client.get_project.side_effect = BIMDataAuthError("BIMData 401 on /cloud/1/project/2")
        _wire_client(_isolated_session, client)
        out = tools_session.check_bimdata_access()
        assert out["ok"] is False
        assert out["auth_source"] == "BIMDATA_API_KEY"
        assert out["auth_scheme"] == "ApiKey"
        # Le 401 nomme le schéma rejeté (ApiKey) → diagnostic « clé morte » évident.
        assert "rejeté" in out["error"] and "401" in out["error"]
        assert "ApiKey" in out["error"]
        assert "svc-key" not in str(out)


def _set_config_auth(
    monkeypatch, *, access_token=None, api_key=None, client_id=None, client_secret=None
):
    """Fixe la provenance d'auth au niveau de ``config`` (source immuable lue par
    ``_active_auth`` — l'instance client ne fait PAS foi, l'OAuth2 mute son
    access_token dès la construction)."""
    monkeypatch.setattr(tools_session.config, "ACCESS_TOKEN", access_token)
    monkeypatch.setattr(tools_session.config, "API_KEY", api_key)
    monkeypatch.setattr(tools_session.config, "CLIENT_ID", client_id)
    monkeypatch.setattr(tools_session.config, "CLIENT_SECRET", client_secret)


class TestActiveAuth:
    """``_active_auth`` reflète la précédence de bimdata_read (access_token →
    api_key → OAuth2) depuis la **config serveur**, sans divulguer les secrets.
    Lit ``config.*`` et non l'instance client : le flow OAuth2 écrit
    ``client.access_token`` dès la construction, l'attribut ne fait donc pas foi."""

    def test_access_token_wins(self, monkeypatch):
        _set_config_auth(monkeypatch, access_token="t", api_key="k")
        assert tools_session._active_auth() == {
            "auth_source": "BIMDATA_ACCESS_TOKEN",
            "auth_scheme": "Bearer",
        }

    def test_api_key_when_no_token(self, monkeypatch):
        _set_config_auth(monkeypatch, api_key="k")
        assert tools_session._active_auth() == {
            "auth_source": "BIMDATA_API_KEY",
            "auth_scheme": "ApiKey",
        }

    def test_oauth2_when_only_client_creds(self, monkeypatch):
        _set_config_auth(monkeypatch, client_id="i", client_secret="s")
        out = tools_session._active_auth()
        assert out["auth_source"] == "BIMDATA_CLIENT_ID+SECRET"
        assert out["auth_scheme"].startswith("Bearer")

    def test_none_when_no_credential(self, monkeypatch):
        _set_config_auth(monkeypatch)
        assert tools_session._active_auth() == {"auth_source": None, "auth_scheme": None}

    def test_reads_config_not_mutated_client_attr(self, monkeypatch):
        # Régression P1 : un client OAuth2 a access_token déjà peuplé (mutation à
        # la construction). La provenance doit rester OAuth2, pas BIMDATA_ACCESS_TOKEN.
        _set_config_auth(monkeypatch, client_id="i", client_secret="s")
        # même si un client traînait avec un token dérivé, on ne le lit pas :
        out = tools_session._active_auth()
        assert out["auth_source"] == "BIMDATA_CLIENT_ID+SECRET"


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
        with patch.object(tools_session, "extract_snapshot", return_value=snap):
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

    def test_ok_identity_still_reports_non_completed_status(self, _isolated_session):
        _isolated_session.client = _FakeClient(model_id="abc")
        snap = _snapshot_with_model("Maquette BIM - LIFFRÉ - DOE.ifc", model_id="abc", status="I")
        with patch.object(tools_session, "extract_snapshot", return_value=snap):
            res = mcp_server.verify_active_model(expected_model_name="LIFFRE")
        assert res["ok"] is True
        assert res["model_status"] == "I"
        assert res["model_status_label"] == "In Process"
        assert res["snapshot_health"] == "model_not_completed"
        assert "status='I'" in res["snapshot_warning"]
        assert res["extraction_errors"] == []

    def test_ko_when_mismatch_does_not_touch_result(self, _isolated_session):
        _isolated_session.client = _FakeClient(model_id="zzz")
        snap = _snapshot_with_model("Autre projet.ifc", model_id="zzz")
        with patch.object(tools_session, "extract_snapshot", return_value=snap):
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
        with patch.object(tools_session, "extract_snapshot") as m_extract:
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
                tools_session, "cached_extract_snapshot", return_value=(snap, True)
            ) as m_cached,
            patch.object(tools_session, "extract_snapshot") as m_direct,
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
            patch.object(tools_audit, "build_catalog") as m_catalog,
            patch.object(tools_audit, "catalog_usable", return_value=(True, None)),
            patch.object(tools_audit, "set_active_model") as m_set,
            patch.object(tools_audit, "extract_snapshot", return_value=snap),
            patch.object(tools_audit, "run_audit") as m_run,
            patch.object(tools_audit, "write_xlsx_annex") as m_xlsx,
            patch.object(tools_audit, "write_word_report") as m_word,
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
            patch.object(tools_audit, "build_catalog"),
            patch.object(tools_audit, "catalog_usable", return_value=(True, None)),
            patch.object(tools_audit, "set_active_model") as m_set,
            patch.object(tools_audit, "extract_snapshot", return_value=snap),
            patch.object(tools_audit, "run_audit", return_value=_FakeAuditResult()),
            patch.object(tools_audit, "build_report_context") as m_ctx,
            patch.object(tools_audit, "merge_user_context") as m_merge,
            patch.object(tools_audit, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(tools_audit, "write_word_report", return_value=tmp_path / "x.docx"),
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
            patch.object(tools_audit, "build_catalog"),
            patch.object(tools_audit, "catalog_usable", return_value=(True, None)),
            patch.object(tools_audit, "set_active_model") as m_set,
            patch.object(tools_audit, "extract_snapshot", return_value=snap),
            patch.object(tools_audit, "run_audit", return_value=_FakeAuditResult()),
            patch.object(tools_audit, "build_report_context") as m_ctx,
            patch.object(tools_audit, "merge_user_context") as m_merge,
            patch.object(tools_audit, "write_xlsx_annex", return_value=tmp_path / "x.xlsx"),
            patch.object(tools_audit, "write_word_report", return_value=tmp_path / "x.docx"),
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
