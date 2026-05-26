"""Tests du DOE planner (``audit_bim.actions.doe_planner``)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from audit_bim.actions.doe_planner import apply_doe_enrichment, prepare_doe_enrichment
from audit_bim.actions.plans import PlanTargetMismatchError
from audit_bim.doe.models import DoeRecord, Match
from audit_bim.domain.write_plan import WritePlanKind
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.security import write_journal as journal_mod


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    journal_mod._reset_journal_for_tests()
    yield tmp_path
    journal_mod._reset_journal_for_tests()


def _snapshot_with_walls() -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[
            {
                "uuid": "W1",
                "type": "IfcWallStandardCase",
                "name": "Mur ext",
                "property_sets": [],
            },
            {
                "uuid": "W2",
                "type": "IfcWallStandardCase",
                "name": "Cloison",
                "property_sets": [
                    {
                        "name": "Pset_3F",
                        "properties": [
                            {
                                "definition": {"name": "Fabricant"},
                                "value": "ACME",
                            }
                        ],
                    }
                ],
            },
        ],
    ).index()


def _matched(uuid: str, props: dict | None = None) -> Match:
    return Match(
        record=DoeRecord(
            source="doe.xlsx",
            row_index=1,
            uuid_hint=uuid,
            properties=props or {},
        ),
        ifc_uuid=uuid,
        ifc_type="IfcWallStandardCase",
        ifc_name=f"Element {uuid}",
        confidence=1.0,
        strategy="guid",
    )


def _unmatched() -> Match:
    return Match(
        record=DoeRecord(
            source="doe.xlsx",
            row_index=2,
            tag_hint="UNKNOWN",
            properties={"Pset_3F": {"Fabricant": "X"}},
        ),
        ifc_uuid=None,
        reason="no candidate",
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
        client._post.return_value = {}
    else:
        client._post.side_effect = RuntimeError("HTTP 500")
    return client


# ── prepare_doe_enrichment ──────────────────────────────────────────────


class TestPrepareDoeEnrichment:
    def test_empty_matches_returns_zero_items(self):
        plan = prepare_doe_enrichment([], snapshot=_snapshot_with_walls(), target=_target())
        assert plan.kind == WritePlanKind.DOE_ENRICHMENT
        assert plan.summary["n_matched"] == 0
        assert plan.summary["n_psets_planned"] == 0
        assert len(plan.items) == 0

    def test_single_match_creates_pset_item(self):
        m = _matched(
            "W1",
            props={"Pset_3F": {"Fabricant": "BOSCH", "Reference": "X42"}},
        )
        plan = prepare_doe_enrichment([m], snapshot=_snapshot_with_walls(), target=_target())
        assert plan.summary["n_matched"] == 1
        assert plan.summary["n_psets_planned"] == 1
        assert plan.summary["n_properties_planned"] == 2
        item = plan.items[0]
        assert item["element_uuid"] == "W1"
        assert item["pset_name"] == "Pset_3F"
        assert item["payload"]["name"] == "Pset_3F"
        names_in_payload = {p["definition"]["name"] for p in item["payload"]["properties"]}
        assert names_in_payload == {"Fabricant", "Reference"}

    def test_unmatched_records_signalled_in_risks(self):
        plan = prepare_doe_enrichment(
            [_unmatched(), _unmatched()],
            snapshot=_snapshot_with_walls(),
            target=_target(),
        )
        assert plan.summary["n_unmatched"] == 2
        assert any("non rapproché" in r for r in plan.risks)

    def test_conflict_skipped_in_report_mode(self):
        """W2 a déjà Pset_3F.Fabricant=ACME ; DOE propose BOSCH → CONFLICT.
        En mode 'report' (défaut), la propriété est skippée."""
        m = _matched("W2", props={"Pset_3F": {"Fabricant": "BOSCH"}})
        plan = prepare_doe_enrichment(
            [m], snapshot=_snapshot_with_walls(), target=_target(), on_conflict="report"
        )
        # Aucun item à écrire (la seule prop est en conflit).
        assert plan.summary["n_psets_planned"] == 0
        # Le risque est signalé.
        assert any("conflit" in r.lower() for r in plan.risks)

    def test_conflict_overwritten_in_overwrite_mode(self):
        m = _matched("W2", props={"Pset_3F": {"Fabricant": "BOSCH"}})
        plan = prepare_doe_enrichment(
            [m],
            snapshot=_snapshot_with_walls(),
            target=_target(),
            on_conflict="overwrite",
        )
        assert plan.summary["n_psets_planned"] == 1
        assert any("overwrite" in r and "écras" in r for r in plan.risks)


# ── apply_doe_enrichment ────────────────────────────────────────────────


class TestApplyDoeEnrichment:
    def test_pushes_each_pset_and_journals(self, tmp_path):
        m = _matched(
            "W1",
            props={"Pset_3F": {"Fabricant": "BOSCH", "Reference": "X42"}},
        )
        plan = prepare_doe_enrichment([m], snapshot=_snapshot_with_walls(), target=_target())
        client = _mock_client()
        result = apply_doe_enrichment(plan, client)

        assert result.succeeded == 1
        assert result.failed == 0
        assert "W1" in result.impacted_uuids
        # Un seul POST sur /element/W1/propertyset
        assert client._post.call_count == 1
        # Journal écrit
        journal_path = tmp_path / "write_log" / "journal.jsonl"
        assert journal_path.exists()
        entries = [json.loads(line) for line in journal_path.read_text("utf-8").splitlines()]
        assert any(e["action"] == "apply_doe_enrichment" for e in entries)

    def test_target_mismatch_refused(self):
        plan = prepare_doe_enrichment(
            [_matched("W1", {"Pset_3F": {"Fabricant": "BOSCH"}})],
            snapshot=_snapshot_with_walls(),
            target=_target(),
        )
        client = _mock_client()
        client.model_id = "99"
        with pytest.raises(PlanTargetMismatchError):
            apply_doe_enrichment(plan, client)

    def test_partial_failure_counts(self):
        m1 = _matched("W1", {"Pset_3F": {"A": "1"}})
        m2 = _matched("W3", {"Pset_3F": {"B": "2"}})  # W3 n'existe pas mais ok côté plan
        plan = prepare_doe_enrichment([m1, m2], snapshot=_snapshot_with_walls(), target=_target())
        client = _mock_client()
        # 2e appel échoue
        calls = [0]

        def _fail_second(url, payload):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError("Bearer abcd12345678 - 500")
            return {}

        client._post.side_effect = _fail_second
        result = apply_doe_enrichment(plan, client)
        assert result.succeeded == 1
        assert result.failed == 1
        # Vérifie scrubbing
        joined = " ".join(e["message"] for e in result.errors)
        assert "abcd12345678" not in joined
        assert "<scrub:" in joined

    def test_wrong_plan_kind_raises(self):
        from audit_bim.domain.write_plan import WritePlan

        bad = WritePlan(kind=WritePlanKind.BCF_TOPICS, target=_target(), items=[])
        client = _mock_client()
        with pytest.raises(ValueError, match="attendu"):
            apply_doe_enrichment(bad, client)
