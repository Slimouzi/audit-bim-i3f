"""Tests de :mod:`audit_bim.actions.plans` — scellé SHA-256 + cible."""

from __future__ import annotations

import json

import pytest

from audit_bim.actions.plans import (
    PlanIntegrityError,
    PlanTargetMismatchError,
    compute_plan_checksum,
    list_plans,
    load_plan,
    save_plan,
    validate_target,
)
from audit_bim.domain.write_plan import WritePlan, WritePlanKind


@pytest.fixture(autouse=True)
def _isolated_export_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    yield tmp_path


def _make_plan(**overrides) -> WritePlan:
    base = dict(
        kind=WritePlanKind.BCF_TOPICS,
        target={"cloud_id": "1", "project_id": "2", "model_id": "3"},
        summary={"n_topics": 2},
        items=[{"title": "T1"}, {"title": "T2"}],
        risks=[],
    )
    base.update(overrides)
    return WritePlan(**base)


class TestComputeChecksum:
    def test_same_content_same_checksum(self):
        p1 = _make_plan()
        p2 = _make_plan()
        assert compute_plan_checksum(p1) == compute_plan_checksum(p2)

    def test_volatile_fields_ignored(self):
        # plan_id et created_at sont auto-générés différemment.
        p1 = _make_plan()
        p2 = _make_plan()
        assert p1.plan_id != p2.plan_id
        assert compute_plan_checksum(p1) == compute_plan_checksum(p2)

    def test_different_items_different_checksum(self):
        p1 = _make_plan(items=[{"title": "A"}])
        p2 = _make_plan(items=[{"title": "B"}])
        assert compute_plan_checksum(p1) != compute_plan_checksum(p2)

    def test_different_target_different_checksum(self):
        p1 = _make_plan(target={"cloud_id": "1"})
        p2 = _make_plan(target={"cloud_id": "9"})
        assert compute_plan_checksum(p1) != compute_plan_checksum(p2)


class TestSaveLoadRoundtrip:
    def test_save_and_load(self, tmp_path):
        plan = _make_plan()
        path = save_plan(plan)
        assert path.exists()
        assert tmp_path in path.parents

        loaded = load_plan(path)
        assert loaded.plan_id == plan.plan_id
        assert loaded.target == plan.target
        assert loaded.kind == plan.kind
        assert len(loaded.items) == 2

    def test_load_rejects_tampered_items(self, tmp_path):
        plan = _make_plan()
        path = save_plan(plan)

        # Trifouille les items sans recalculer le checksum.
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["items"].append({"title": "INJECTED"})
        path.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(PlanIntegrityError, match="altéré"):
            load_plan(path)

    def test_load_rejects_missing_checksum(self, tmp_path):
        plan = _make_plan()
        path = save_plan(plan)

        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("_sealed_sha256", None)
        path.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(PlanIntegrityError):
            load_plan(path)

    def test_load_bypass_checksum_when_disabled(self, tmp_path):
        plan = _make_plan()
        path = save_plan(plan)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("_sealed_sha256", None)
        path.write_text(json.dumps(raw), encoding="utf-8")

        # verify_checksum=False → on accepte sans vérifier (tests / migration).
        loaded = load_plan(path, verify_checksum=False)
        assert loaded.plan_id == plan.plan_id

    def test_load_relative_path_resolves_under_export_root(self, tmp_path):
        plan = _make_plan()
        path = save_plan(plan)
        rel = path.relative_to(tmp_path)
        loaded = load_plan(str(rel))
        assert loaded.plan_id == plan.plan_id


class TestListPlans:
    def test_returns_recent_plans(self):
        p1 = _make_plan()
        p2 = _make_plan(kind=WritePlanKind.SMART_VIEWS)
        save_plan(p1)
        save_plan(p2)

        plans = list_plans()
        assert len(plans) == 2
        kinds = {p["kind"] for p in plans}
        assert kinds == {WritePlanKind.BCF_TOPICS.value, WritePlanKind.SMART_VIEWS.value}

    def test_limit_respected(self):
        for _ in range(5):
            save_plan(_make_plan())
        plans = list_plans(limit=2)
        assert len(plans) == 2

    def test_empty_when_no_plans(self):
        assert list_plans() == []


class TestValidateTarget:
    def test_matching_target_passes(self):
        plan = _make_plan(target={"cloud_id": "1", "project_id": "2", "model_id": "3"})
        validate_target(plan, actual_target={"cloud_id": "1", "project_id": "2", "model_id": "3"})

    def test_mismatching_model_id_raises(self):
        plan = _make_plan(target={"cloud_id": "1", "project_id": "2", "model_id": "3"})
        with pytest.raises(PlanTargetMismatchError, match="model_id"):
            validate_target(
                plan, actual_target={"cloud_id": "1", "project_id": "2", "model_id": "99"}
            )

    def test_str_int_coercion(self):
        plan = _make_plan(target={"cloud_id": 1, "project_id": 2, "model_id": 3})
        # Int et str du même nombre doivent matcher.
        validate_target(plan, actual_target={"cloud_id": "1", "project_id": "2", "model_id": "3"})

    def test_plan_without_target_is_lenient(self):
        plan = _make_plan(target={})
        # Plan sans cible → pas de refus (compatibilité ancien format).
        validate_target(plan, actual_target={"cloud_id": "9"})
