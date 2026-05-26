"""Tests des 3 planners (BCF, Smart Views, classifications).

Vérifie :
- prepare_* construit un WritePlan cohérent avec la cible et le filtre,
- apply_* refuse les plans dont la cible diffère du client courant,
- apply_* journalise via WriteJournal,
- apply_* met à jour le store de suggestions sur succès.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from audit_bim.actions import (
    PlanTargetMismatchError,
    apply_bcf,
    apply_classification_update,
    apply_smart_views,
    prepare_bcf,
    prepare_classification_update,
    prepare_smart_views,
)
from audit_bim.audit.engine import AuditResult
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.classifier.suggestion_store import (
    ClassificationSuggestionEntry,
    ClassificationSuggestionStore,
)
from audit_bim.domain.filters import (
    ConfidenceBand,
    FindingFilter,
    SuggestionFilter,
    SuggestionStatus,
)
from audit_bim.domain.write_plan import WritePlanKind
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import BIMPhase, RequirementsCatalog
from audit_bim.security import write_journal as journal_mod

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    journal_mod._reset_journal_for_tests()
    yield tmp_path
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


def _two_finding_audit() -> AuditResult:
    snap = ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[
            {"uuid": "W1", "type": "IfcWallStandardCase", "name": "Mur"},
        ],
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
        Finding(
            theme=Theme.PROPERTY_MISSING,
            severity=Severity.HIGH,
            error_type=ErrorType.PROPERTY_MISSING,
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


def _target() -> dict:
    return {
        "cloud_id": "1",
        "project_id": "2",
        "model_id": "3",
        "model_name": "M.ifc",
    }


def _mock_client(success: bool = True):
    client = MagicMock()
    client.cloud_id = "1"
    client.project_id = "2"
    client.model_id = "3"
    if success:
        client.create_bcf_full_topic.return_value = {"guid": "abc"}
    else:
        client.create_bcf_full_topic.side_effect = RuntimeError("boom")
    return client


# ── BCF planner ──────────────────────────────────────────────────────────


class TestPrepareBcf:
    def test_no_filter_includes_all(self):
        plan = prepare_bcf(_two_finding_audit(), target=_target())
        assert plan.kind == WritePlanKind.BCF_TOPICS
        # 1 overview + 2 thèmes = 3 topics.
        assert plan.summary["n_topics"] == 3
        assert plan.summary["n_findings_in_scope"] == 2
        assert plan.target == _target()

    def test_filter_severity_min_reduces_scope(self):
        plan = prepare_bcf(
            _two_finding_audit(),
            finding_filter=FindingFilter(severity_min="HIGH"),
            target=_target(),
        )
        # 1 finding HIGH → 1 overview + 1 thème = 2 topics.
        assert plan.summary["n_findings_in_scope"] == 1
        assert plan.summary["n_topics"] == 2

    def test_empty_scope_triggers_risk(self):
        plan = prepare_bcf(
            _two_finding_audit(),
            finding_filter=FindingFilter(error_types=["spatial_orphan"]),
            target=_target(),
        )
        assert plan.summary["n_topics"] == 0
        assert any("Aucun finding" in r for r in plan.risks)


class TestApplyBcf:
    def test_writes_via_client_and_journals(self, tmp_path):
        plan = prepare_bcf(_two_finding_audit(), target=_target())
        client = _mock_client()
        result = apply_bcf(plan, client)

        assert result.succeeded == plan.summary["n_topics"]
        assert result.failed == 0
        assert client.create_bcf_full_topic.call_count == plan.summary["n_topics"]
        # Journal écrit
        journal_path = tmp_path / "write_log" / "journal.jsonl"
        assert journal_path.exists()
        entries = [json.loads(line) for line in journal_path.read_text("utf-8").splitlines()]
        assert any(e["action"] == "apply_bcf_topics" for e in entries)

    def test_target_mismatch_raises(self):
        plan = prepare_bcf(_two_finding_audit(), target=_target())
        client = _mock_client()
        client.model_id = "99"  # mismatch
        with pytest.raises(PlanTargetMismatchError):
            apply_bcf(plan, client)

    def test_partial_failure_counts(self):
        plan = prepare_bcf(_two_finding_audit(), target=_target())
        client = _mock_client(success=False)
        result = apply_bcf(plan, client)
        assert result.succeeded == 0
        assert result.failed == plan.summary["n_topics"]
        assert len(result.errors) == plan.summary["n_topics"]


# ── Smart Views planner ──────────────────────────────────────────────────


class TestPrepareSmartViews:
    def test_payloads_built(self):
        plan = prepare_smart_views(_two_finding_audit(), target=_target())
        assert plan.kind == WritePlanKind.SMART_VIEWS
        assert plan.summary["n_smart_views"] >= 1


class TestApplySmartViews:
    def test_writes_via_client(self, tmp_path):
        plan = prepare_smart_views(_two_finding_audit(), target=_target())
        client = _mock_client()
        result = apply_smart_views(plan, client)
        assert result.succeeded == plan.summary["n_smart_views"]
        # Journal
        entries = [
            json.loads(line)
            for line in (tmp_path / "write_log" / "journal.jsonl").read_text("utf-8").splitlines()
        ]
        assert any(e["action"] == "apply_smart_views" for e in entries)


# ── Classification planner ──────────────────────────────────────────────


def _store_with_entries() -> ClassificationSuggestionStore:
    store = ClassificationSuggestionStore()
    store.add(
        ClassificationSuggestionEntry(
            element_uuid="W1",
            ifc_type="IfcWall",
            proposed_classification="C1010",
            proposed_label="Partitions",
            proposed_system="uniformat",
            proposed_level_3="C1010",
            confidence=0.65,
            confidence_band=ConfidenceBand.MEDIUM,
            status=SuggestionStatus.ACCEPTED,
        )
    )
    store.add(
        ClassificationSuggestionEntry(
            element_uuid="W2",
            ifc_type="IfcWall",
            proposed_classification="B2010",
            proposed_label="Exterior Walls",
            proposed_system="uniformat",
            proposed_level_3="B2010",
            confidence=0.9,
            confidence_band=ConfidenceBand.HIGH,
            status=SuggestionStatus.PROPOSED,
        )
    )
    store.add(
        ClassificationSuggestionEntry(
            element_uuid="W3",
            ifc_type="IfcWall",
            current_classification="C1010",
            proposed_classification="B2010",
            proposed_label="Exterior Walls",
            proposed_system="uniformat",
            proposed_level_3="B2010",
            confidence=0.85,
            confidence_band=ConfidenceBand.HIGH,
            status=SuggestionStatus.ACCEPTED,
        )
    )
    return store


class TestPrepareClassificationUpdate:
    def test_defaults_to_accepted_only(self):
        plan = prepare_classification_update(_store_with_entries(), target=_target())
        # 2 entries en ACCEPTED (W1 + W3) → 2 items.
        assert plan.summary["n_classifications"] == 2
        uuids = {it["element_uuid"] for it in plan.items}
        assert uuids == {"W1", "W3"}

    def test_default_status_scope_none_includes_all(self):
        plan = prepare_classification_update(
            _store_with_entries(),
            target=_target(),
            default_status_scope=None,
        )
        assert plan.summary["n_classifications"] == 3

    def test_explicit_filter_overrides_default(self):
        plan = prepare_classification_update(
            _store_with_entries(),
            suggestion_filter=SuggestionFilter(min_confidence=0.88),
            target=_target(),
        )
        # Seul W3 (0.85) ... non, 0.85 ≥ 0.88 ? 0.85 < 0.88 → 0 ; W2 = 0.9 → 1.
        # Le filtre n'a pas de contrainte de statut → W2 (PROPOSED) inclus.
        assert plan.summary["n_classifications"] == 1
        assert plan.items[0]["element_uuid"] == "W2"

    def test_overwrite_risk_detected(self):
        plan = prepare_classification_update(_store_with_entries(), target=_target())
        # W3 a une classification existante → écrasement
        assert plan.summary["n_overwrite"] == 1
        assert any("écrasement" in r.lower() for r in plan.risks)


class TestApplyClassificationUpdate:
    def test_calls_apply_classifications_and_journals(self, tmp_path, monkeypatch):
        from audit_bim.actions import classification_planner

        # Mock apply_classifications côté planner pour ne pas exécuter
        # de POST réel. Le contrat retourne désormais linked_uuids /
        # failed_uuids (cf. revue CTO P2).
        fake_api = MagicMock(
            return_value={
                "dry_run": False,
                "n_items": 2,
                "n_classifications_created": 1,
                "n_classifications_reused": 0,
                "n_links_created": 2,
                "link_failed": False,
                "orphan_classifications": [],
                "linked_uuids": ["W1", "W3"],
                "failed_uuids": [],
                "errors": [],
            }
        )
        monkeypatch.setattr(classification_planner, "apply_classifications", fake_api)

        store = _store_with_entries()
        plan = prepare_classification_update(store, target=_target())
        client = _mock_client()
        result = apply_classification_update(plan, client, store=store)

        assert result.succeeded == 2
        assert result.failed == 0
        # Statuts mis à jour vers APPLIED pour les UUIDs réellement liés.
        assert store.get("W1").status == SuggestionStatus.APPLIED
        assert store.get("W3").status == SuggestionStatus.APPLIED
        # W2 (non touché par le plan ACCEPTED-only) reste PROPOSED.
        assert store.get("W2").status == SuggestionStatus.PROPOSED

        entries = [
            json.loads(line)
            for line in (tmp_path / "write_log" / "journal.jsonl").read_text("utf-8").splitlines()
        ]
        assert any(e["action"] == "apply_classification_update" for e in entries)

    def test_link_failed_keeps_statuses(self, monkeypatch):
        from audit_bim.actions import classification_planner

        fake_api = MagicMock(
            return_value={
                "dry_run": False,
                "n_items": 2,
                "n_classifications_created": 1,
                "n_classifications_reused": 0,
                "n_links_created": 0,
                "link_failed": True,
                "orphan_classifications": [],
                "linked_uuids": [],
                "failed_uuids": ["W1", "W3"],
                "errors": ["bulk link failed: 500"],
            }
        )
        monkeypatch.setattr(classification_planner, "apply_classifications", fake_api)

        store = _store_with_entries()
        plan = prepare_classification_update(store, target=_target())
        client = _mock_client()
        apply_classification_update(plan, client, store=store)

        # Sur link_failed, on ne bascule PAS vers APPLIED.
        assert store.get("W1").status == SuggestionStatus.ACCEPTED
        assert store.get("W3").status == SuggestionStatus.ACCEPTED

    def test_partial_creation_failure_only_marks_linked(self, monkeypatch):
        """W1 lié, W3 perdu côté création de sa classification (groupe KO).

        On vérifie que seul W1 passe à APPLIED ; W3 reste ACCEPTED pour
        permettre un rerun ciblé.
        """
        from audit_bim.actions import classification_planner

        fake_api = MagicMock(
            return_value={
                "dry_run": False,
                "n_items": 2,
                "n_classifications_created": 1,
                "n_classifications_reused": 0,
                "n_links_created": 1,
                "link_failed": False,
                "orphan_classifications": [],
                "linked_uuids": ["W1"],
                "failed_uuids": ["W3"],
                "errors": ["create uniformat/B2010: 422 Unprocessable Entity"],
            }
        )
        monkeypatch.setattr(classification_planner, "apply_classifications", fake_api)

        store = _store_with_entries()
        plan = prepare_classification_update(store, target=_target())
        client = _mock_client()
        result = apply_classification_update(plan, client, store=store)

        assert result.succeeded == 1
        assert result.failed == 1
        # W1 effectivement lié → APPLIED
        assert store.get("W1").status == SuggestionStatus.APPLIED
        # W3 KO côté création → conserve ACCEPTED pour rerun
        assert store.get("W3").status == SuggestionStatus.ACCEPTED

    def test_error_messages_redacted_in_action_result(self, monkeypatch):
        """Les exceptions API contenant des secrets ne doivent jamais
        fuiter dans ``ActionResult.errors`` ou dans le journal."""
        from audit_bim.actions import classification_planner

        fake_api = MagicMock(
            return_value={
                "dry_run": False,
                "n_items": 2,
                "n_classifications_created": 1,
                "n_classifications_reused": 0,
                "n_links_created": 0,
                "link_failed": True,
                "orphan_classifications": [],
                "linked_uuids": [],
                "failed_uuids": ["W1", "W3"],
                "errors": [
                    "HTTPError 401 for url: https://api.example/x?access_token=eyJabcdefgh12345678",
                ],
            }
        )
        monkeypatch.setattr(classification_planner, "apply_classifications", fake_api)

        store = _store_with_entries()
        plan = prepare_classification_update(store, target=_target())
        client = _mock_client()
        result = apply_classification_update(plan, client, store=store)

        joined_errors = " ".join(e["message"] for e in result.errors)
        assert "eyJabcdefgh12345678" not in joined_errors
        assert "<scrub:" in joined_errors
