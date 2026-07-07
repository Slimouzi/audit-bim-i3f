"""Squelette commun des ``apply_*`` des planners (PR4 §4b).

Les 4 planners (``bcf``/``smartview``/``doe``/``classification``) répétaient le
**même cadre** : contrôle de ``kind`` → cible par défaut (déduite du client) →
``validate_target`` → journal → ``ActionResult``. Ce cadre est factorisé ici :
chaque planner ne garde que **son exécuteur** (traitement des items, spécifique)
qui renvoie un :class:`ApplyOutcome`. Enjeu : un futur 5ᵉ planner ne peut plus
oublier ``validate_target`` ni la journalisation.

Contrainte : **payloads byte-identiques** (les tests MCP et les goldens y sont
accrochés) — ``run_apply`` reproduit exactement l'ordre et les champs d'origine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..domain.write_plan import ActionResult, WritePlan, WritePlanKind
from ..extraction.client import BIMDataClient
from ..security.write_journal import get_journal
from .plans import validate_target


@dataclass
class ApplyOutcome:
    """Résultat du traitement des items par un exécuteur de planner.

    ``impacted`` = titres (BCF/Smart Views) **ou** UUIDs (DOE/classif), tel que
    journalisé sous ``impacted_uuids``. ``result_errors`` = liste d'erreurs
    **déjà scrubée** telle qu'attendue dans ``ActionResult.errors``. ``extra`` =
    bloc ``extra`` du journal (déjà complet, ``errors_sample`` inclus)."""

    succeeded: int
    failed: int
    impacted: list[str]
    result_errors: list[dict] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def run_apply(
    plan: WritePlan,
    client: BIMDataClient,
    *,
    expected_kind: WritePlanKind,
    action: str,
    actual_target: dict[str, Any] | None,
    executor: Callable[[WritePlan, BIMDataClient], ApplyOutcome],
) -> ActionResult:
    """Cadre commun : contrôle ``kind`` → cible → ``validate_target`` → exécuteur
    → journal → ``ActionResult``.

    Args:
        expected_kind: kind attendu du plan (rejet sinon).
        action: nom d'action pour le journal.
        actual_target: cible courante (défaut : déduite du client).
        executor: callable ``(plan, client) -> ApplyOutcome`` portant le
            traitement spécifique des items.
    """
    if plan.kind != expected_kind:
        raise ValueError(f"Plan de kind={plan.kind!r}, attendu={expected_kind!r}.")

    if actual_target is None:
        actual_target = {
            "cloud_id": client.cloud_id,
            "project_id": client.project_id,
            "model_id": client.model_id,
        }
    validate_target(plan, actual_target=actual_target)

    outcome = executor(plan, client)

    get_journal().record(
        action=action,
        plan_id=plan.plan_id,
        plan_kind=plan.kind.value,
        target=plan.target,
        succeeded=outcome.succeeded,
        failed=outcome.failed,
        impacted_uuids=outcome.impacted,
        extra=outcome.extra,
    )

    return ActionResult(
        plan_id=plan.plan_id,
        kind=plan.kind,
        succeeded=outcome.succeeded,
        failed=outcome.failed,
        impacted_uuids=outcome.impacted,
        errors=outcome.result_errors,
    )
