"""Tests des wrappers legacy ``tools_legacy`` (refactorisation review CTO).

Couvre :

- Marqueurs de dépréciation systématiques (deprecated, use_instead, removal_version).
- Mode par défaut ``legacy_execute=False`` ne fait **aucune** écriture
  BIMData — renvoie un plan compatible apply_*.
- Mode ``legacy_execute=True`` exécute l'ancien flux + warning fort.
- ``apply_suggested_classifications(legacy_execute=False)`` ne pousse pas
  vers BIMData mais bascule en ``ACCEPTED`` dans le store.
- ``ensure_writes_allowed`` est respecté en mode legacy_execute.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from audit_bim.audit.engine import AuditResult
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.classifier.suggestion_store import (
    ClassificationSuggestionEntry,
    ClassificationSuggestionStore,
)
from audit_bim.domain.filters import ConfidenceBand, SuggestionStatus
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp import tools_legacy
from audit_bim.mcp.session import _Session, current_session
from audit_bim.requirements.models import BIMPhase, RequirementsCatalog
from audit_bim.security import write_journal as journal_mod


@pytest.fixture
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_BIM_ALLOW_WRITES", "true")
    journal_mod._reset_journal_for_tests()
    sess = _Session()
    token = current_session.set(sess)
    try:
        yield sess, tmp_path
    finally:
        current_session.reset(token)
        journal_mod._reset_journal_for_tests()


def _empty_catalog() -> RequirementsCatalog:
    return RequirementsCatalog(
        cch_version="3.6",
        cch_source_pdf="t://c.pdf",
        data_spec_source="t://d.xlsx",
        naming_spec_source="t://n.xlsx",
        properties=[],
        naming_rules=[],
        storey_names=[],
        zone_specs=[],
        room_specs=[],
    )


def _two_finding_result() -> AuditResult:
    snap = ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[{"uuid": "W1", "type": "IfcWallStandardCase", "name": "Mur"}],
    ).index()
    findings = [
        Finding(
            theme=Theme.CLASSIFICATION,
            severity=Severity.MEDIUM,
            error_type=ErrorType.CLASSIFICATION_MISSING,
            element_uuid="W1",
            ifc_type="IfcWallStandardCase",
            name="Mur",
        ),
    ]
    return AuditResult(
        phase=BIMPhase.PRO,
        catalog=_empty_catalog(),
        snapshot=snap,
        findings=findings,
    )


def _wire_session(sess):
    r = _two_finding_result()
    sess.snapshot = r.snapshot
    sess.result = r
    c = MagicMock()
    c.cloud_id = "1"
    c.project_id = "2"
    c.model_id = "3"
    c.create_bcf_full_topic.return_value = {"guid": "g"}
    sess.client = c
    sess.cloud_id = "1"
    sess.project_id = "2"
    sess.model_id = "3"


# ── Marqueurs de dépréciation ───────────────────────────────────────────


class TestDeprecationMarkers:
    def test_suggest_classifications_marked(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        out = mcp_server.suggest_classifications()
        # Le contrat historique est list[dict] ; le marker est sur out[0]._meta.
        # Si pas de suggestions, on accepte une liste vide.
        if out:
            meta = out[0].get("_meta", {})
            assert meta.get("deprecated") is True
            assert "list_classification_suggestions" in meta.get("use_instead", "")
            assert meta.get("removal_version") == "0.3.0"

    def test_create_bcf_topics_marked(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        res = mcp_server.create_bcf_topics()
        assert res["deprecated"] is True
        assert "prepare_bcf_topics" in res["use_instead"]
        assert res["removal_version"] == "0.3.0"
        assert "migration_hint" in res

    def test_create_smart_views_marked(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        res = mcp_server.create_smart_views()
        assert res["deprecated"] is True
        assert "prepare_smart_views_plan" in res["use_instead"]
        assert res["removal_version"] == "0.3.0"

    def test_apply_suggested_marked(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        res = mcp_server.apply_suggested_classifications()
        assert res["deprecated"] is True
        assert "prepare_classification_update_plan" in res["use_instead"]


# ── Mode par défaut (legacy_execute=False) : aucune écriture BIMData ─────


class TestLegacyDefaultNoWrite:
    def test_create_bcf_topics_default_returns_plan_no_api_call(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        res = mcp_server.create_bcf_topics()
        # Le plan a été préparé → kind, plan_id, plan_path présents.
        assert res.get("kind") == "bcf_topics"
        assert res.get("requires_confirm") is True
        assert "plan_path" in res
        assert "next_step" in res
        # Aucun appel vers le client.
        assert sess.client.create_bcf_full_topic.call_count == 0

    def test_create_smart_views_default_returns_plan_no_api_call(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        res = mcp_server.create_smart_views()
        assert res.get("kind") == "smart_views"
        assert res.get("requires_confirm") is True
        assert "plan_path" in res
        assert sess.client.create_bcf_full_topic.call_count == 0

    def test_apply_suggested_default_returns_plan_no_api_call(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        # Pré-rempli avec 1 suggestion en PROPOSED avec confidence > seuil.
        store = ClassificationSuggestionStore()
        store.add(
            ClassificationSuggestionEntry(
                element_uuid="W1",
                ifc_type="IfcWallStandardCase",
                proposed_classification="C1010",
                proposed_level_3="C1010",
                confidence=0.7,
                confidence_band=ConfidenceBand.MEDIUM,
            )
        )
        sess.suggestion_store = store

        res = mcp_server.apply_suggested_classifications(min_confidence=0.5)
        assert res.get("kind") == "classification_update"
        assert res.get("requires_confirm") is True
        assert res["n_auto_accepted"] == 1
        # Suggestion basculée en ACCEPTED
        assert store.get("W1").status == SuggestionStatus.ACCEPTED
        # Pas d'appel API
        assert sess.client._post.call_count == 0


# ── Mode legacy_execute=True : ancien comportement + warning ────────────


class TestLegacyExecuteFlag:
    def test_create_bcf_topics_legacy_execute_calls_push(self, _isolated, monkeypatch):
        sess, _ = _isolated
        _wire_session(sess)
        # Mock pour intercepter l'ancien chemin.
        fake_push = MagicMock(return_value=[{"payload": {}, "response": {}}])
        monkeypatch.setattr(tools_legacy, "_push_bcf_topics", fake_push)

        res = mcp_server.create_bcf_topics(legacy_execute=True, dry_run=True)
        assert fake_push.call_count == 1
        assert res["deprecated"] is True
        # Warning fort
        assert "legacy_execute_warning" in res
        assert "0.3.0" in res["legacy_execute_warning"]

    def test_create_smart_views_legacy_execute_calls_push(self, _isolated, monkeypatch):
        sess, _ = _isolated
        _wire_session(sess)
        fake_push = MagicMock(return_value=[])
        monkeypatch.setattr(tools_legacy, "_push_smart_views", fake_push)

        res = mcp_server.create_smart_views(legacy_execute=True, dry_run=True)
        assert fake_push.call_count == 1
        assert "legacy_execute_warning" in res

    def test_apply_suggested_legacy_execute_calls_api(self, _isolated, monkeypatch):
        sess, _ = _isolated
        _wire_session(sess)
        fake_api = MagicMock(
            return_value={
                "dry_run": True,
                "n_items": 0,
                "preview": [],
            }
        )
        monkeypatch.setattr(tools_legacy, "_apply_classifications", fake_api)
        monkeypatch.setattr(tools_legacy, "_suggest_for_findings", MagicMock(return_value=[]))
        monkeypatch.setattr(tools_legacy, "_items_from_suggestions", MagicMock(return_value=[]))

        res = mcp_server.apply_suggested_classifications(legacy_execute=True, dry_run=True)
        assert fake_api.call_count == 1
        assert "legacy_execute_warning" in res


# ── ensure_writes_allowed gate ───────────────────────────────────────────


class TestEnsureWritesAllowedRespected:
    """En mode legacy_execute=True, l'écriture réelle DOIT passer par
    ``ensure_writes_allowed``."""

    def test_create_bcf_topics_writes_blocked_in_http_mode(self, tmp_path, monkeypatch):
        # Force HTTP mode (le défaut hors stdio) ET désactive l'opt-in.
        monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("AUDIT_BIM_ALLOW_WRITES", "false")
        monkeypatch.setenv("AUDIT_BIM_TRANSPORT", "http")
        journal_mod._reset_journal_for_tests()
        sess = _Session()
        token = current_session.set(sess)
        try:
            _wire_session(sess)
            # legacy_execute=True + dry_run=False → doit appeler ensure_writes_allowed
            # qui lèvera WritesDisabledError.
            from audit_bim.mcp.security import WritesDisabledError

            with pytest.raises(WritesDisabledError):
                mcp_server.create_bcf_topics(legacy_execute=True, dry_run=False)
        finally:
            current_session.reset(token)
            journal_mod._reset_journal_for_tests()


# ── Aliases métier : présence côté FastMCP + délégation ─────────────────


class TestAliasesRegisteredAndDelegate:
    def test_all_6_aliases_registered(self):
        import anyio

        tools = anyio.run(mcp_server.mcp.list_tools)
        names = {t.name for t in tools}
        for alias in (
            "prepare_bcf_from_findings",
            "apply_bcf_plan",
            "prepare_smartviews_from_findings",
            "apply_smartviews_plan",
            "prepare_classification_corrections",
            "apply_classification_corrections",
        ):
            assert alias in names, f"alias manquant : {alias}"

    def test_prepare_bcf_from_findings_delegates(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        # Alias produit le même type de plan que prepare_bcf_topics.
        res = mcp_server.prepare_bcf_from_findings()
        assert res["kind"] == "bcf_topics"
        assert res["requires_confirm"] is True

    def test_apply_bcf_plan_refuses_without_confirm(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        prep = mcp_server.prepare_bcf_from_findings()
        res = mcp_server.apply_bcf_plan(plan_path=prep["plan_path"], confirm=False)
        assert res.get("refused") is True

    def test_prepare_classification_corrections_delegates(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        sess.suggestion_store = ClassificationSuggestionStore()
        res = mcp_server.prepare_classification_corrections()
        assert res["kind"] == "classification_update"


# ── Snapshot list_tools : statut actif/déprécié ─────────────────────────


class TestListToolsSnapshot:
    """Snapshot léger pour détecter les régressions d'enregistrement."""

    EXPECTED_DEPRECATED = {
        "suggest_classifications",
        "apply_suggested_classifications",
        "create_bcf_topics",
        "create_smart_views",
    }
    EXPECTED_NEW_ALIASES = {
        "prepare_bcf_from_findings",
        "apply_bcf_plan",
        "prepare_smartviews_from_findings",
        "apply_smartviews_plan",
        "prepare_classification_corrections",
        "apply_classification_corrections",
    }
    EXPECTED_PREPARE_APPLY = {
        "prepare_bcf_topics",
        "apply_bcf_topics",
        "prepare_smart_views_plan",
        "apply_smart_views_plan",
        "prepare_classification_update_plan",
        "apply_classification_update_plan",
        "list_write_plans",
        "update_suggestion_status",
        "audit_trail",
    }
    EXPECTED_QUERY = {
        "filter_bim_objects",
        "list_audit_findings",
        "get_object_detail",
        "list_classification_suggestions",
    }

    def _all_tool_names(self) -> set[str]:
        import anyio

        tools = anyio.run(mcp_server.mcp.list_tools)
        return {t.name for t in tools}

    def test_all_categories_present(self):
        names = self._all_tool_names()
        for category in (
            self.EXPECTED_DEPRECATED,
            self.EXPECTED_NEW_ALIASES,
            self.EXPECTED_PREPARE_APPLY,
            self.EXPECTED_QUERY,
        ):
            missing = category - names
            assert not missing, f"manquants : {missing}"

    def test_deprecated_tools_in_registry(self):
        from audit_bim.mcp.deprecation import DEPRECATIONS

        # Tous les tools dépréciés enregistrés doivent être dans le
        # registre DEPRECATIONS (et inversement).
        registry_names = set(DEPRECATIONS.keys())
        assert registry_names == self.EXPECTED_DEPRECATED, (
            f"registry mismatch : {registry_names ^ self.EXPECTED_DEPRECATED}"
        )


# ── Test global : tous les apply_* refusent confirm=False ────────────────


class TestAllApplyToolsRefuseWithoutConfirm:
    APPLY_TOOLS = [
        "apply_bcf_topics",
        "apply_smart_views_plan",
        "apply_classification_update_plan",
        "apply_bcf_plan",  # alias
        "apply_smartviews_plan",  # alias
        "apply_classification_corrections",  # alias
    ]

    @pytest.mark.parametrize("tool_name", APPLY_TOOLS)
    def test_refuse_without_confirm(self, _isolated, tool_name):
        sess, _ = _isolated
        _wire_session(sess)
        fn = getattr(mcp_server, tool_name)
        # plan_path quelconque — le tool doit refuser AVANT toute lecture.
        res = fn(plan_path="plans/dummy.json", confirm=False)
        assert res.get("refused") is True, f"{tool_name} n'a pas refusé sans confirm"
