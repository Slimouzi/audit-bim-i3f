"""Planner Smart Views — prepare/apply via :class:`WritePlan`.

Symétrique de :mod:`bcf_planner` mais sur l'agent Smart Views
(``audit_bim.smartview.builder``). Smart Views = navigation 3D minimale
(coloring uniquement), pas de workflow d'issue.
"""

from __future__ import annotations

import logging
from typing import Any

from ..audit.engine import AuditResult
from ..domain.filters import FindingFilter
from ..domain.write_plan import ActionResult, WritePlan, WritePlanKind
from ..extraction.client import BIMDataClient
from ..query.filtering import finding_matches
from ..security.write_journal import get_journal
from ..smartview.builder import build_smartview_payloads
from .plans import validate_target

logger = logging.getLogger("audit_bim.actions.smartview")


def prepare_smart_views(
    result: AuditResult,
    *,
    finding_filter: FindingFilter | None = None,
    target: dict[str, Any],
    prefix: str = "I3F Audit — ",
    include_overview: bool = True,
) -> WritePlan:
    """Construit un :class:`WritePlan` pour création de Smart Views.

    Mêmes paramètres que :func:`prepare_bcf` ; cf. docstring.
    """
    if finding_filter is not None:
        filtered = [f for f in result.findings if finding_matches(f, finding_filter)]
    else:
        filtered = list(result.findings)

    scoped = AuditResult(
        phase=result.phase,
        catalog=result.catalog,
        snapshot=result.snapshot,
        findings=filtered,
    )

    model_id = target.get("model_id")
    payloads = build_smartview_payloads(
        scoped,
        prefix=prefix,
        model_id=model_id,
        include_overview=include_overview,
    )

    risks: list[str] = []
    if not payloads:
        risks.append("Aucun finding ne matche le filtre — 0 Smart View à créer.")

    summary = {
        "n_smart_views": len(payloads),
        "n_findings_in_scope": len(filtered),
        "include_overview": include_overview,
        "filter_applied": finding_filter is not None,
        "prefix": prefix,
    }

    return WritePlan(
        kind=WritePlanKind.SMART_VIEWS,
        target=target,
        summary=summary,
        items=payloads,
        risks=risks,
    )


def apply_smart_views(
    plan: WritePlan,
    client: BIMDataClient,
    *,
    actual_target: dict[str, Any] | None = None,
) -> ActionResult:
    """Exécute un plan Smart Views préalablement scellé."""
    if plan.kind != WritePlanKind.SMART_VIEWS:
        raise ValueError(f"Plan de kind={plan.kind!r}, attendu={WritePlanKind.SMART_VIEWS!r}.")

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
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append({"title": str(title), "message": str(exc)})

    get_journal().record(
        action="apply_smart_views",
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
