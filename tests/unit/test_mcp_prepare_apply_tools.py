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
from audit_bim.mcp import app as mcp_app
from audit_bim.mcp.session import _Session, current_session
from audit_bim.profiles.i3f.tools_actions import apply_bcf_topics as ta_apply_bcf_topics
from audit_bim.profiles.i3f.tools_actions import (
    apply_classification_update_plan as ta_apply_classification_update_plan,
)
from audit_bim.profiles.i3f.tools_actions import (
    apply_classifications_from_xlsx as ta_apply_classifications_from_xlsx,
)
from audit_bim.profiles.i3f.tools_actions import (
    apply_doe_enrichment_plan as ta_apply_doe_enrichment_plan,
)
from audit_bim.profiles.i3f.tools_actions import apply_smart_views_plan as ta_apply_smart_views_plan
from audit_bim.profiles.i3f.tools_actions import audit_trail as ta_audit_trail
from audit_bim.profiles.i3f.tools_actions import list_write_plans as ta_list_write_plans
from audit_bim.profiles.i3f.tools_actions import prepare_bcf_topics as ta_prepare_bcf_topics
from audit_bim.profiles.i3f.tools_actions import (
    prepare_classification_update_plan as ta_prepare_classification_update_plan,
)
from audit_bim.profiles.i3f.tools_actions import (
    prepare_smart_views_plan as ta_prepare_smart_views_plan,
)
from audit_bim.profiles.i3f.tools_actions import (
    update_suggestion_status as ta_update_suggestion_status,
)
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

        tools = anyio.run(mcp_app.mcp.list_tools)
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
        res = ta_prepare_bcf_topics()
        assert res["kind"] == "bcf_topics"
        assert res["requires_confirm"] is True
        assert res["plan_path"].endswith(".json")
        assert (tmp / "plans").exists()

    def test_apply_refuses_without_confirm(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        prep = ta_prepare_bcf_topics()
        res = ta_apply_bcf_topics(plan_path=prep["plan_path"], confirm=False)
        assert res["refused"] is True
        # Aucun appel vers le client
        assert sess.client.create_bcf_full_topic.call_count == 0

    def test_apply_with_confirm_executes(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        prep = ta_prepare_bcf_topics()
        res = ta_apply_bcf_topics(plan_path=prep["plan_path"], confirm=True)
        assert res.get("succeeded", 0) >= 1
        assert sess.client.create_bcf_full_topic.call_count >= 1

    def test_apply_rejects_tampered_plan(self, _isolated):
        sess, tmp = _isolated
        _wire_session(sess)
        prep = ta_prepare_bcf_topics()
        # Altère le plan sur disque
        from pathlib import Path

        path = Path(prep["plan_path"])
        raw = path.read_text(encoding="utf-8").replace("I3F Audit", "MALICIOUS")
        path.write_text(raw, encoding="utf-8")

        res = ta_apply_bcf_topics(plan_path=prep["plan_path"], confirm=True)
        assert res.get("refused") is True
        assert "altéré" in res["reason"].lower() or "checksum" in res["reason"].lower()

    def test_apply_rejects_target_mismatch(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        prep = ta_prepare_bcf_topics()
        # Change la cible courante après prepare
        sess.model_id = "99"
        sess.client.model_id = "99"
        res = ta_apply_bcf_topics(plan_path=prep["plan_path"], confirm=True)
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

        res = ta_prepare_classification_update_plan()
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

        res = ta_prepare_classification_update_plan(default_to_accepted_only=False)
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

        res = ta_update_suggestion_status(element_uuid="X", status="accepted")
        assert res["status"] == "accepted"

    def test_unknown_uuid_raises(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        sess.suggestion_store = ClassificationSuggestionStore()
        with pytest.raises(ValueError, match="UUID inconnu"):
            ta_update_suggestion_status(element_uuid="NOPE", status="accepted")

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
            ta_update_suggestion_status(element_uuid="X", status="bogus")


# ── audit_trail ──────────────────────────────────────────────────────────


class TestAuditTrail:
    def test_returns_recent_entries(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        # Trigger un apply pour journaliser
        prep = ta_prepare_bcf_topics()
        ta_apply_bcf_topics(plan_path=prep["plan_path"], confirm=True)
        trail = ta_audit_trail(limit=10)
        assert trail["total_returned"] >= 1
        assert any(e["action"] == "apply_bcf_topics" for e in trail["entries"])


# ── Dépréciation douce ───────────────────────────────────────────────────


# ── list_write_plans ─────────────────────────────────────────────────────


class TestListWritePlans:
    def test_empty_when_no_plans(self, _isolated):
        res = ta_list_write_plans()
        assert res["total"] == 0

    def test_lists_after_prepare(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        ta_prepare_bcf_topics()
        ta_prepare_smart_views_plan()
        res = ta_list_write_plans()
        kinds = {p["kind"] for p in res["plans"]}
        assert {"bcf_topics", "smart_views"}.issubset(kinds)


# ── apply_classifications_from_xlsx : prepare → apply (PR3 §3c) ───────────────
class TestApplyClassificationsFromXlsx:
    """Le tool xlsx suit désormais le contrat commun confirm-gate (plus de dry_run)."""

    _ITEMS = [{"uuid": "u1", "code": "C1010", "label": "Mur", "system": "UniFormat II"}]

    def _patched_xlsx(self):
        # Évite un vrai fichier : sandbox + lecture xlsx simulées.
        return patch.multiple(
            "audit_bim.profiles.i3f.tools_actions",
            safe_input_path=MagicMock(return_value="/tmp/audit.xlsx"),
            read_classifications_from_xlsx=MagicMock(return_value=self._ITEMS),
        )

    def test_without_confirm_is_dry_run_no_write(self, _isolated):
        from audit_bim.security.write_journal import get_journal

        sess, _ = _isolated
        _wire_session(sess)
        n_before = len(get_journal().tail(50))
        with self._patched_xlsx():
            res = ta_apply_classifications_from_xlsx("audit.xlsx", confirm=False)
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
            res = ta_apply_classifications_from_xlsx("audit.xlsx", confirm=True)
        assert res.get("succeeded") == 1
        assert res["n_items_read_from_xlsx"] == 1
        # Entrée journal écrite par apply_classification_update.
        last = get_journal().tail(1)[0]
        assert last.action == "apply_classification_update"
        assert last.succeeded == 1


# ── C4 : trio apply (execute / tamper / mismatch) pour les 3 tools non-BCF ────
def _tamper(plan_path: str) -> None:
    from pathlib import Path

    p = Path(plan_path)
    raw = p.read_text(encoding="utf-8")
    # Modifie une valeur du plan sans toucher au checksum → altération détectée.
    p.write_text(raw.replace("model_name", "model_NAME", 1) + " ", encoding="utf-8")


class TestApplySmartViewsPostConfirmC4:
    """C4 — apply_smart_views_plan n'exécutait jamais son corps post-confirm."""

    def test_apply_with_confirm_executes(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        prep = ta_prepare_smart_views_plan()
        res = ta_apply_smart_views_plan(plan_path=prep["plan_path"], confirm=True)
        assert res.get("succeeded", 0) >= 1
        assert sess.client.create_bcf_full_topic.call_count >= 1

    def test_apply_rejects_tampered_plan(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        prep = ta_prepare_smart_views_plan()
        _tamper(prep["plan_path"])
        res = ta_apply_smart_views_plan(plan_path=prep["plan_path"], confirm=True)
        assert res.get("refused") is True

    def test_apply_rejects_target_mismatch(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        prep = ta_prepare_smart_views_plan()
        sess.model_id = "99"
        sess.client.model_id = "99"
        res = ta_apply_smart_views_plan(plan_path=prep["plan_path"], confirm=True)
        assert res.get("refused") is True
        assert "model_id" in res["reason"]


def _store_accepted() -> ClassificationSuggestionStore:
    store = ClassificationSuggestionStore()
    store.add(
        ClassificationSuggestionEntry(
            element_uuid="W1",
            ifc_type="IfcWallStandardCase",
            proposed_classification="C1010",
            proposed_level_3="C1010",
            confidence=0.7,
            confidence_band=ConfidenceBand.MEDIUM,
            status=SuggestionStatus.ACCEPTED,
        )
    )
    return store


class TestApplyClassificationPostConfirmC4:
    """C4 — apply_classification_update_plan n'exécutait jamais son corps post-confirm."""

    def test_apply_with_confirm_executes(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        sess.client.create_classification.return_value = {"id": 1}
        sess.suggestion_store = _store_accepted()
        prep = ta_prepare_classification_update_plan()
        res = ta_apply_classification_update_plan(plan_path=prep["plan_path"], confirm=True)
        assert res.get("succeeded", 0) >= 1
        assert sess.client.assign_classification_elements.call_count >= 1

    def test_apply_rejects_tampered_plan(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        sess.suggestion_store = _store_accepted()
        prep = ta_prepare_classification_update_plan()
        _tamper(prep["plan_path"])
        res = ta_apply_classification_update_plan(plan_path=prep["plan_path"], confirm=True)
        assert res.get("refused") is True

    def test_apply_rejects_target_mismatch(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        sess.suggestion_store = _store_accepted()
        prep = ta_prepare_classification_update_plan()
        sess.model_id = "99"
        sess.client.model_id = "99"
        res = ta_apply_classification_update_plan(plan_path=prep["plan_path"], confirm=True)
        assert res.get("refused") is True
        assert "model_id" in res["reason"]


def _doe_plan_path(sess) -> str:
    """Construit + scelle un plan DOE (bypass parse fichier) pour la cible session."""
    from audit_bim.actions.doe_planner import prepare_doe_enrichment
    from audit_bim.actions.plans import save_plan
    from audit_bim.doe.models import DoeRecord, Match

    match = Match(
        record=DoeRecord(
            source="doe.xlsx",
            row_index=1,
            uuid_hint="W1",
            properties={"Pset_3F": {"Fabricant": "ACME"}},
        ),
        ifc_uuid="W1",
        ifc_type="IfcWallStandardCase",
        ifc_name="Mur",
        confidence=1.0,
        strategy="guid",
    )
    plan = prepare_doe_enrichment(
        [match],
        snapshot=sess.snapshot,
        target={"cloud_id": "1", "project_id": "2", "model_id": "3", "model_name": "M.ifc"},
        on_conflict="overwrite",
    )
    return str(save_plan(plan))


class TestApplyDoePostConfirmC4:
    """C4 — apply_doe_enrichment_plan n'exécutait jamais son corps post-confirm."""

    def test_apply_with_confirm_executes(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        sess.client.write_element_propertyset.return_value = {}
        path = _doe_plan_path(sess)
        res = ta_apply_doe_enrichment_plan(plan_path=path, confirm=True)
        assert res.get("succeeded", 0) >= 1
        assert sess.client.write_element_propertyset.call_count >= 1

    def test_apply_rejects_tampered_plan(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        path = _doe_plan_path(sess)
        _tamper(path)
        res = ta_apply_doe_enrichment_plan(plan_path=path, confirm=True)
        assert res.get("refused") is True

    def test_apply_rejects_target_mismatch(self, _isolated):
        sess, _ = _isolated
        _wire_session(sess)
        path = _doe_plan_path(sess)
        sess.model_id = "99"
        sess.client.model_id = "99"
        res = ta_apply_doe_enrichment_plan(plan_path=path, confirm=True)
        assert res.get("refused") is True
        assert "model_id" in res["reason"]
