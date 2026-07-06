"""Cœur CI hors-ligne du replay A1 (`scripts/a1_replay/run_replay.py`).

Teste, sans réseau : les helpers purs (``assert_write_target``, ``inspect_plan``)
et les **4 refus** exigés par le scope (``docs/scope-a1-replay.md`` §2) — confirm
absent, plan altéré, cible de plan ≠ cible effective, cible ≠ modèle jetable.
Le runner est chargé par chemin (imports ``audit_bim`` tardifs dans ``main``).
"""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest

from audit_bim.actions.plans import (
    PlanIntegrityError,
    PlanTargetMismatchError,
    load_plan,
    validate_target,
)
from audit_bim.domain.write_plan import WritePlan, WritePlanKind
from audit_bim.mcp.tools_actions import apply_bcf_topics

_RUNNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "a1_replay" / "run_replay.py"
_spec = importlib.util.spec_from_file_location("a1_replay_runner", _RUNNER_PATH)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

TARGET = {"cloud_id": "33617", "project_id": "2698917", "model_id": "1674450"}
PFX = "REPLAY-BIM-PUBLICATION-20260706 — "


def _plan(items, *, target=None, risks=None):
    return types.SimpleNamespace(items=items, risks=risks or [], target=target or TARGET)


# ── Garde cible jetable ────────────────────────────────────────────────────


def test_write_target_accepts_disposable():
    runner.assert_write_target({"model_id": "1674450"}, "1674450")  # ne lève pas


def test_write_target_refuses_other_model():
    with pytest.raises(SystemExit):
        runner.assert_write_target({"model_id": "1726110"}, "1674450")


def test_write_target_refuses_unset_env():
    with pytest.raises(SystemExit):
        runner.assert_write_target({"model_id": "1674450"}, None)


# ── Revue de plan (inspect_plan) ───────────────────────────────────────────


def test_inspect_plan_ok():
    r = runner.inspect_plan(
        _plan([{"title": PFX + "Nommage Pièce"}]), effective_target=TARGET, title_prefix=PFX
    )
    assert r["ok"] is True
    assert r["n_items"] == 1 and not r["has_risks"] and r["target_matches"] and r["prefix_ok"]


def test_inspect_plan_zero_items():
    r = runner.inspect_plan(_plan([]), effective_target=TARGET, title_prefix=PFX)
    assert r["ok"] is False


def test_inspect_plan_with_risks():
    r = runner.inspect_plan(
        _plan([{"title": PFX + "X"}], risks=["écrasement silencieux"]),
        effective_target=TARGET,
        title_prefix=PFX,
    )
    assert r["has_risks"] is True and r["ok"] is False


def test_inspect_plan_bad_prefix():
    r = runner.inspect_plan(
        _plan([{"title": "I3F Audit — X"}]), effective_target=TARGET, title_prefix=PFX
    )
    assert r["prefix_ok"] is False and r["ok"] is False


def test_inspect_plan_target_mismatch():
    r = runner.inspect_plan(
        _plan([{"title": PFX + "X"}], target={"cloud_id": "1", "project_id": "2", "model_id": "3"}),
        effective_target=TARGET,
        title_prefix=PFX,
    )
    assert r["target_matches"] is False and r["ok"] is False


# ── Les 4 refus (scope §2) ─────────────────────────────────────────────────


def test_refusal_apply_without_confirm():
    # apply(confirm=False) → refus (early-return, aucune session requise).
    res = apply_bcf_topics("n-importe-quoi.json", confirm=False)
    assert res.get("refused") is True


def test_refusal_plan_integrity(tmp_path, monkeypatch):
    # Vrai scellé (save_plan) puis altération après coup → PlanIntegrityError.
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    from audit_bim.actions.plans import save_plan

    plan = WritePlan(kind=WritePlanKind.BCF_TOPICS, target=TARGET, items=[{"title": PFX + "X"}])
    path = save_plan(plan)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data["items"] = [{"title": "TAMPERED"}]  # modifie le contenu après le scellé
    Path(path).write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PlanIntegrityError):
        load_plan(path)


def test_refusal_plan_target_mismatch():
    plan = WritePlan(kind=WritePlanKind.BCF_TOPICS, target=TARGET, items=[])
    with pytest.raises(PlanTargetMismatchError):
        validate_target(plan, actual_target={"cloud_id": "X", "project_id": "Y", "model_id": "Z"})


def test_refusal_write_target_is_the_fourth_guard():
    # 4ᵉ refus : cible ≠ modèle jetable (déjà couvert, rappelé ici pour le contrat).
    with pytest.raises(SystemExit):
        runner.assert_write_target({"model_id": "1726110"}, "1674450")


# ── Vérification journal (étape 9) — helper pur ────────────────────────────


def _entry(action, plan_id, succeeded, failed=0):
    return types.SimpleNamespace(action=action, plan_id=plan_id, succeeded=succeeded, failed=failed)


def test_journal_confirms_match():
    entries = [_entry("apply_bcf_topics", "p1", 1)]
    assert (
        runner.journal_confirms(
            entries, action="apply_bcf_topics", plan_id="p1", expected_succeeded=1
        )
        is True
    )


def test_journal_confirms_wrong_count():
    entries = [_entry("apply_bcf_topics", "p1", 2)]
    assert (
        runner.journal_confirms(
            entries, action="apply_bcf_topics", plan_id="p1", expected_succeeded=1
        )
        is False
    )


def test_journal_confirms_failed_nonzero():
    entries = [_entry("apply_smart_views", "p2", 1, failed=1)]
    assert (
        runner.journal_confirms(
            entries, action="apply_smart_views", plan_id="p2", expected_succeeded=1
        )
        is False
    )


def test_journal_confirms_missing_entry():
    entries = [_entry("apply_smart_views", "pX", 1)]
    assert (
        runner.journal_confirms(
            entries, action="apply_bcf_topics", plan_id="p1", expected_succeeded=1
        )
        is False
    )
