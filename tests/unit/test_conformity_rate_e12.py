"""E12 (audit profond 2ᵉ passe) — verrou du ``conformity_rate``.

Trou de mutation : changer un poids (CRITICAL 5 / HIGH 3 / MEDIUM 1 / LOW 0.3 /
INFO 0) ou le dénominateur (``n_éléments × 3``) ne faisait échouer aucun test,
alors que ce taux pilote la décision au **seuil 0.7** dans les livrables. On épingle
donc des **valeurs exactes** + le comportement au seuil.
"""

from __future__ import annotations

import pytest

from audit_bim.audit.engine import AuditResult
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import BIMPhase, RequirementsCatalog


def _snapshot(n_elements: int) -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[{"uuid": f"E{i}", "type": "IfcWall"} for i in range(n_elements)],
    ).index()


def _finding(sev: Severity) -> Finding:
    return Finding(
        theme=Theme.PROPERTY_MISSING,
        severity=sev,
        error_type=ErrorType.PROPERTY_MISSING,
        ifc_type="IfcWall",
    )


def _rate(n_elements: int, severities: list[Severity]) -> float:
    result = AuditResult(
        phase=BIMPhase.PRO,
        catalog=RequirementsCatalog(),
        snapshot=_snapshot(n_elements),
        findings=[_finding(s) for s in severities],
    )
    return result.conformity_rate()


# ── Valeur exacte (poids composés) ────────────────────────────────────────────
def test_exact_value_mixed_severities():
    # 10 éléments → dénominateur 30. Pondéré = 5+3+1+0.3 = 9.3. 1 - 9.3/30 = 0.69.
    r = _rate(10, [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW])
    assert r == pytest.approx(0.69)


# ── Chaque poids est verrouillé (100 éléments → dénominateur 300) ─────────────
@pytest.mark.parametrize(
    "sev,expected",
    [
        (Severity.CRITICAL, 1 - 5 / 300),
        (Severity.HIGH, 1 - 3 / 300),
        (Severity.MEDIUM, 1 - 1 / 300),
        (Severity.LOW, 1 - 0.3 / 300),
        (Severity.INFO, 1.0),  # poids 0 → n'affecte pas
    ],
)
def test_each_weight_is_locked(sev, expected):
    assert _rate(100, [sev]) == pytest.approx(expected)


# ── Dénominateur = n_éléments × 3 ─────────────────────────────────────────────
def test_denominator_scales_with_elements():
    assert _rate(10, [Severity.MEDIUM]) == pytest.approx(1 - 1 / 30)
    assert _rate(20, [Severity.MEDIUM]) == pytest.approx(1 - 1 / 60)


# ── Bornes [0, 1] ─────────────────────────────────────────────────────────────
def test_perfect_when_no_findings():
    assert _rate(10, []) == 1.0


def test_clamped_to_zero_when_overwhelmed():
    # 1 élément, dénominateur 3, 10 CRITICAL (50) → 1 - 50/3 < 0 → borné à 0.
    assert _rate(1, [Severity.CRITICAL] * 10) == 0.0


def test_empty_snapshot_denominator_at_least_one():
    # n_elements = max(1, ...) : pas de division par zéro.
    assert _rate(0, [Severity.MEDIUM]) == pytest.approx(1 - 1 / 3)


# ── Seuil 0.7 (décision livrable) ─────────────────────────────────────────────
def test_threshold_exactly_070_is_not_below():
    # 10 éléments, 3 HIGH → pondéré 9, 1 - 9/30 = 0.70 pile.
    r = _rate(10, [Severity.HIGH] * 3)
    assert r == pytest.approx(0.70)
    assert not (r < 0.7)


def test_threshold_just_below_070():
    r = _rate(10, [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW])
    assert r < 0.7  # 0.69
