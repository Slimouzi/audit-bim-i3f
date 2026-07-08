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

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.write_plan import ActionResult, WritePlan, WritePlanKind
from ..extraction.client import BIMDataClient
from ..security.write_journal import get_journal
from .plans import validate_target


def _applied_dir() -> Path:
    """Dossier des marqueurs d'idempotence, à côté du journal (sandbox)."""
    d = get_journal().path.parent / "applied"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    force: bool = False,
) -> ActionResult:
    """Cadre commun : contrôle ``kind`` → cible → ``validate_target`` →
    **garde d'idempotence (C3)** → intent → exécuteur → completed + sidecar →
    ``ActionResult``.

    Args:
        expected_kind: kind attendu du plan (rejet sinon).
        action: nom d'action pour le journal.
        actual_target: cible courante (défaut : déduite du client).
        executor: callable ``(plan, client) -> ApplyOutcome`` portant le
            traitement spécifique des items.
        force: rejoue un plan déjà appliqué / interrompu (risque de doublons).

    C3 — sans garde, un crash au milieu de la boucle d'items laissait le journal
    vide (« rien ne s'est passé ») alors que des items étaient déjà écrits chez le
    client ; le plan restant applicable, un re-run rejouait TOUT → doublons. On
    trace donc l'**intent** (marqueur ``<plan_id>.started`` + entrée journal
    ``status=started``) AVANT la boucle, un **completed** (marqueur
    ``<plan_id>.applied.json`` + entrée journal) APRÈS, et on **refuse** un second
    apply du même ``plan_id`` (sauf ``force``).
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

    # ── Garde d'idempotence (C3) ─────────────────────────────────────────────
    applied_dir = _applied_dir()
    started_marker = applied_dir / f"{plan.plan_id}.started"
    applied_marker = applied_dir / f"{plan.plan_id}.applied.json"
    if started_marker.exists() and not force:
        already = applied_marker.exists()
        raise ValueError(
            f"REFUS : le plan {plan.plan_id} a déjà été "
            + ("appliqué" if already else "amorcé (tentative précédente interrompue)")
            + ". Un second apply dupliquerait les écritures. "
            + (
                f"Items déjà appliqués : {applied_marker}. "
                if already
                else "Reprends manuellement les items manquants. "
            )
            + "Passe force=True pour rejouer malgré tout (au risque de doublons)."
        )
    started_marker.write_text(plan.plan_id, encoding="utf-8")

    # Intent : trace AVANT la boucle → un crash laisse une preuve dans le journal.
    get_journal().record(
        action=action,
        plan_id=plan.plan_id,
        plan_kind=plan.kind.value,
        target=plan.target,
        extra={"status": "started"},
    )

    outcome = executor(plan, client)

    # Completed : sidecar des items appliqués + entrée journal (forme d'origine).
    applied_marker.write_text(
        json.dumps({"plan_id": plan.plan_id, "impacted": outcome.impacted}, ensure_ascii=False),
        encoding="utf-8",
    )
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
