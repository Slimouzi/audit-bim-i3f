"""Planner BCF Topics — prepare/apply via :class:`WritePlan`.

Réutilise :func:`audit_bim.bcf.builder.build_bcf_payloads` pour la
construction des payloads, et :meth:`BIMDataClient.create_bcf_full_topic`
pour l'exécution.
"""

from __future__ import annotations

import logging
from typing import Any

from ..audit.engine import AuditResult
from ..bcf.builder import build_bcf_payloads
from ..domain.filters import FindingFilter
from ..domain.write_plan import ActionResult, WritePlan, WritePlanKind
from ..extraction.client import BIMDataClient
from ..query.filtering import finding_matches
from ..security.write_journal import get_journal
from .plans import validate_target

logger = logging.getLogger("audit_bim.actions.bcf")


def prepare_bcf(
    result: AuditResult,
    *,
    finding_filter: FindingFilter | None = None,
    target: dict[str, Any],
    prefix: str = "I3F Audit — ",
    include_overview: bool = True,
) -> WritePlan:
    """Construit et scelle un :class:`WritePlan` pour création BCF Topics.

    Args:
        result: Résultat d'audit en cours.
        finding_filter: Filtre déclaratif sur les findings (défaut =
            tous). Permet de générer une PR BCF ciblée (ex: seulement
            ``severity_min=HIGH``).
        target: Cible BIMData (cloud / project / model + model_name).
        prefix: Préfixe des titres BCF.
        include_overview: Inclure le topic « Vue d'ensemble » en tête.

    Returns:
        Plan **non encore sauvé** ; le caller appelle :func:`save_plan`
        séparément (ou le tool MCP ``prepare_bcf_topics`` le fait).
    """
    # 1. Filtre les findings si demandé (sans pagination — un planner
    # traite tout le périmètre, contrairement aux tools MCP de filtrage
    # qui bornent à MAX_LIMIT).
    if finding_filter is not None:
        filtered = [f for f in result.findings if finding_matches(f, finding_filter)]
    else:
        filtered = list(result.findings)

    # 2. Construit un AuditResult temporaire pour build_bcf_payloads.
    scoped = AuditResult(
        phase=result.phase,
        catalog=result.catalog,
        snapshot=result.snapshot,
        findings=filtered,
    )

    model_id = target.get("model_id")
    payloads = build_bcf_payloads(
        scoped,
        prefix=prefix,
        model_id=model_id,
        include_overview=include_overview,
    )

    # 3. Risks : alertes utiles à la revue manuelle.
    risks: list[str] = []
    if not payloads:
        risks.append("Aucun finding ne matche le filtre — 0 topic à créer.")
    n_findings_with_uuid = sum(1 for f in filtered if f.element_uuid)
    if n_findings_with_uuid == 0 and filtered:
        risks.append(
            f"{len(filtered)} findings filtrés mais aucun n'a d'element_uuid "
            "(anomalies projet uniquement) → topics minimaux."
        )

    summary = {
        "n_topics": len(payloads),
        "n_findings_in_scope": len(filtered),
        "include_overview": include_overview,
        "filter_applied": finding_filter is not None,
        "prefix": prefix,
    }

    return WritePlan(
        kind=WritePlanKind.BCF_TOPICS,
        target=target,
        summary=summary,
        items=payloads,
        risks=risks,
    )


def apply_bcf(
    plan: WritePlan,
    client: BIMDataClient,
    *,
    actual_target: dict[str, Any] | None = None,
) -> ActionResult:
    """Exécute un plan BCF préalablement scellé.

    Args:
        plan: Plan rechargé via :func:`load_plan` (avec scellé vérifié).
        client: Client BIMData authentifié sur la cible attendue.
        actual_target: Cible courante pour validation. Défaut : déduite
            du client.

    Returns:
        :class:`ActionResult` avec compteurs et erreurs (déjà scrubées
        des tokens — le client ne retourne pas de bearer dans ses
        exceptions standard).
    """
    if plan.kind != WritePlanKind.BCF_TOPICS:
        raise ValueError(f"Plan de kind={plan.kind!r}, attendu={WritePlanKind.BCF_TOPICS!r}.")

    if actual_target is None:
        actual_target = {
            "cloud_id": client.cloud_id,
            "project_id": client.project_id,
            "model_id": client.model_id,
        }
    validate_target(plan, actual_target=actual_target)

    succeeded = 0
    failed = 0
    impacted_titles: list[str] = []
    errors: list[dict[str, str]] = []

    for payload in plan.items:
        title = payload.get("title", "?")
        try:
            client.create_bcf_full_topic(payload)
            succeeded += 1
            impacted_titles.append(title)
        except Exception as exc:  # noqa: BLE001 (on capture tout pour journaliser)
            failed += 1
            errors.append({"title": str(title), "message": str(exc)})

    get_journal().record(
        action="apply_bcf_topics",
        plan_id=plan.plan_id,
        plan_kind=plan.kind.value,
        target=plan.target,
        succeeded=succeeded,
        failed=failed,
        impacted_uuids=impacted_titles,
        extra={"errors_sample": errors[:5]},
    )

    return ActionResult(
        plan_id=plan.plan_id,
        kind=plan.kind,
        succeeded=succeeded,
        failed=failed,
        impacted_uuids=impacted_titles,
        errors=errors,
    )
