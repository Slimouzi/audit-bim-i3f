"""Tests des tools MCP ``prepare_*`` / ``apply_*`` (tranche 2).

Couvre :
- enregistrement des nouveaux tools côté FastMCP ;
- refus explicite quand ``confirm=False`` (aucune écriture) ;
- refus quand le plan a été altéré ;
- refus quand la cible courante diffère ;
- propagation correcte du store de suggestions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
from audit_bim.mcp.session import _Session, current_session
from audit_bim.requirements.models import BIMPhase, RequirementsCatalog
from audit_bim.security import write_journal as journal_mod

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    # Les tests exercent apply_*, qui passe par ensure_writes_allowed.
    # En unit on n'expose pas de transport HTTP — on autorise les
    # écritures explicitement (équivalent du mode stdio par défaut).
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
        cch_source_pdf="test://cch.pdf",
        data_spec_source="test://data.xlsx",
        naming_spec_source="test://naming.xlsx",
        properties=[],
        naming_rules=[],
        storey_names=[],
        zone_specs=[],
        room_specs=[],
    )


def _result() -> AuditResult:
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


def _wire_session(sess, *, snapshot=True, audit=True, client=True):
    if snapshot or audit:
        r = _result()
        sess.snapshot = r.snapshot
        if audit:
            sess.result = r
    if client:
        c = MagicMock()
        c.cloud_id = "1"
        c.project_id = "2"
        c.model_id = "3"
        c.create_bcf_full_topic.return_value = {"guid": "g"}
        sess.client = c
        sess.cloud_id = "1"
        sess.project_id = "2"
        sess.model_id = "3"


# ── Enregistrement ───────────────────────────────────────────────────────


class TestNewToolsRegistered:
    def test_prepare_apply_tools_registered(self):
        # Synchrone via ``anyio.run`` (déjà transitivement dispo) pour
        # éviter pytest-asyncio.
        import anyio

        tools = anyio.run(mcp_server.mcp.list_tools)
        names = {t.name for t in tools}
        for name in (
            "prepare_bcf_topics",
            "apply_bcf_topics",
            "prepare_smart_views_plan",
            "apply_smart_views_plan",
            "prepare_classification_update_plan",
            "apply_classification_update_plan",
            "list_write_plans",
            "update_suggestion_status",
            "audit_trail",
        ):
            assert name in names, f"tool manquant : {name}"


# ── prepare_bcf_topics / apply_bcf_topics ────────────────────────────────


class TestPrepareApplyBcf:
    def test_prepare_returns_plan_path(self, _isolated):
        sess, tmp = _isolated
        _wire_session(sess)
        res = mcp_server.prepare_bcf_topics()
        assert res["kind"] == "bcf_topics"
        assert res["requires_confirm"] is True
        assert res["plan_path"].endswith(".json")
        assert (tmp / "plans").exists()

    def test_apply_refuses_without_confirm(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        prep = mcp_server.prepare_bcf_topics()
        res = mcp_server.apply_bcf_topics(plan_path=prep["plan_path"], confirm=False)
        assert res["refused"] is True
        # Aucun appel vers le client
        assert sess.client.create_bcf_full_topic.call_count == 0

    def test_apply_with_confirm_executes(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        prep = mcp_server.prepare_bcf_topics()
        res = mcp_server.apply_bcf_topics(plan_path=prep["plan_path"], confirm=True)
        assert res.get("succeeded", 0) >= 1
        assert sess.client.create_bcf_full_topic.call_count >= 1

    def test_apply_rejects_tampered_plan(self, _isolated):
        sess, tmp = _isolated
        _wire_session(sess)
        prep = mcp_server.prepare_bcf_topics()
        # Altère le plan sur disque
        from pathlib import Path

        path = Path(prep["plan_path"])
        raw = path.read_text(encoding="utf-8").replace("I3F Audit", "MALICIOUS")
        path.write_text(raw, encoding="utf-8")

        res = mcp_server.apply_bcf_topics(plan_path=prep["plan_path"], confirm=True)
        assert res.get("refused") is True
        assert "altéré" in res["reason"].lower() or "checksum" in res["reason"].lower()

    def test_apply_rejects_target_mismatch(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        prep = mcp_server.prepare_bcf_topics()
        # Change la cible courante après prepare
        sess.model_id = "99"
        sess.client.model_id = "99"
        res = mcp_server.apply_bcf_topics(plan_path=prep["plan_path"], confirm=True)
        assert res.get("refused") is True
        assert "model_id" in res["reason"]


# ── prepare_classification_update_plan ──────────────────────────────────


class TestPrepareApplyClassification:
    def test_prepare_uses_store_accepted_by_default(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        # Pré-rempli avec 1 ACCEPTED + 1 PROPOSED
        store = ClassificationSuggestionStore()
        store.add(
            ClassificationSuggestionEntry(
                element_uuid="A",
                ifc_type="IfcWall",
                proposed_classification="C1010",
                proposed_level_3="C1010",
                confidence=0.7,
                confidence_band=ConfidenceBand.MEDIUM,
                status=SuggestionStatus.ACCEPTED,
            )
        )
        store.add(
            ClassificationSuggestionEntry(
                element_uuid="B",
                ifc_type="IfcWall",
                proposed_classification="B2010",
                proposed_level_3="B2010",
                confidence=0.9,
                confidence_band=ConfidenceBand.HIGH,
                status=SuggestionStatus.PROPOSED,
            )
        )
        sess.suggestion_store = store

        res = mcp_server.prepare_classification_update_plan()
        # Seul A est ACCEPTED → 1 item.
        assert res["summary"]["n_classifications"] == 1

    def test_default_to_accepted_only_false(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        store = ClassificationSuggestionStore()
        for uid, st in [("A", SuggestionStatus.ACCEPTED), ("B", SuggestionStatus.PROPOSED)]:
            store.add(
                ClassificationSuggestionEntry(
                    element_uuid=uid,
                    ifc_type="IfcWall",
                    proposed_classification="C1010",
                    proposed_level_3="C1010",
                    confidence=0.7,
                    confidence_band=ConfidenceBand.MEDIUM,
                    status=st,
                )
            )
        sess.suggestion_store = store

        res = mcp_server.prepare_classification_update_plan(default_to_accepted_only=False)
        assert res["summary"]["n_classifications"] == 2


# ── update_suggestion_status ─────────────────────────────────────────────


class TestUpdateSuggestionStatus:
    def test_basculer_proposed_vers_accepted(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        store = ClassificationSuggestionStore()
        store.add(
            ClassificationSuggestionEntry(
                element_uuid="X",
                proposed_classification="C1010",
                proposed_level_3="C1010",
                confidence=0.6,
                confidence_band=ConfidenceBand.MEDIUM,
            )
        )
        sess.suggestion_store = store

        res = mcp_server.update_suggestion_status(element_uuid="X", status="accepted")
        assert res["status"] == "accepted"

    def test_unknown_uuid_raises(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        sess.suggestion_store = ClassificationSuggestionStore()
        with pytest.raises(ValueError, match="UUID inconnu"):
            mcp_server.update_suggestion_status(element_uuid="NOPE", status="accepted")

    def test_invalid_status_raises(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        store = ClassificationSuggestionStore()
        store.add(
            ClassificationSuggestionEntry(
                element_uuid="X",
                proposed_classification="C1010",
                proposed_level_3="C1010",
                confidence=0.6,
                confidence_band=ConfidenceBand.MEDIUM,
            )
        )
        sess.suggestion_store = store
        with pytest.raises(ValueError, match="status invalide"):
            mcp_server.update_suggestion_status(element_uuid="X", status="bogus")


# ── audit_trail ──────────────────────────────────────────────────────────


class TestAuditTrail:
    def test_returns_recent_entries(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        # Trigger un apply pour journaliser
        prep = mcp_server.prepare_bcf_topics()
        mcp_server.apply_bcf_topics(plan_path=prep["plan_path"], confirm=True)
        trail = mcp_server.audit_trail(limit=10)
        assert trail["total_returned"] >= 1
        assert any(e["action"] == "apply_bcf_topics" for e in trail["entries"])


# ── Dépréciation douce ───────────────────────────────────────────────────


# ── list_write_plans ─────────────────────────────────────────────────────


class TestListWritePlans:
    def test_empty_when_no_plans(self, _isolated):
        res = mcp_server.list_write_plans()
        assert res["total"] == 0

    def test_lists_after_prepare(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        mcp_server.prepare_bcf_topics()
        mcp_server.prepare_smart_views_plan()
        res = mcp_server.list_write_plans()
        kinds = {p["kind"] for p in res["plans"]}
        assert {"bcf_topics", "smart_views"}.issubset(kinds)


# ── apply_classifications_from_xlsx : prepare → apply (PR3 §3c) ───────────────
class TestApplyClassificationsFromXlsx:
    """Le tool xlsx suit désormais le contrat commun confirm-gate (plus de dry_run)."""

    _ITEMS = [{"uuid": "u1", "code": "C1010", "label": "Mur", "system": "UniFormat II"}]

    def _patched_xlsx(self):
        # Évite un vrai fichier : sandbox + lecture xlsx simulées.
        return patch.multiple(
            "audit_bim.mcp.tools_actions",
            safe_input_path=MagicMock(return_value="/tmp/audit.xlsx"),
            read_classifications_from_xlsx=MagicMock(return_value=self._ITEMS),
        )

    def test_without_confirm_is_dry_run_no_write(self, _isolated):
        from audit_bim.security.write_journal import get_journal

        sess, _ = _isolated
        _wire_session(sess)
        n_before = len(get_journal().tail(50))
        with self._patched_xlsx():
            res = mcp_server.apply_classifications_from_xlsx("audit.xlsx", confirm=False)
        assert res["refused"] is True
        assert res["plan"]["summary"]["n_classifications"] == 1
        assert res["n_items_read_from_xlsx"] == 1
        # Aucune écriture / entrée journal sans confirm.
        assert len(get_journal().tail(50)) == n_before

    def test_with_confirm_applies_and_journals(self, _isolated):
        from audit_bim.security.write_journal import get_journal

        sess, _ = _isolated
        _wire_session(sess)
        with (
            self._patched_xlsx(),
            patch(
                "audit_bim.actions.classification_planner.apply_classifications",
                return_value={"linked_uuids": ["u1"], "failed_uuids": [], "errors": []},
            ),
        ):
            res = mcp_server.apply_classifications_from_xlsx("audit.xlsx", confirm=True)
        assert res.get("succeeded") == 1
        assert res["n_items_read_from_xlsx"] == 1
        # Entrée journal écrite par apply_classification_update.
        last = get_journal().tail(1)[0]
        assert last.action == "apply_classification_update"
        assert last.succeeded == 1
