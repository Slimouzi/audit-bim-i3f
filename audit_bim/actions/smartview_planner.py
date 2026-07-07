"""Planner Smart Views — prepare/apply via :class:`WritePlan`.

Symétrique de :mod:`bcf_planner` mais sur l'agent Smart Views
(``audit_bim.smartview.builder``). Smart Views = navigation 3D minimale
(coloring uniquement), pas de workflow d'issue.
"""

from __future__ import annotations

import logging
from typing import Any

from bim_publication import DEFAULT_FILTER_SMARTVIEW_COLOR
from bim_publication import prepare_smart_view_from_filter as _pub_prepare_svff
from bim_publication import prepare_smart_views as _pub_prepare_sv

from ..audit.engine import AuditResult
from ..domain.filters import FindingFilter
from ..domain.write_plan import ActionResult, WritePlan, WritePlanKind
from ..extraction.client import BIMDataClient
from ..security.redaction import redact_secrets
from ._apply_runtime import ApplyOutcome, run_apply

logger = logging.getLogger("audit_bim.actions.smartview")


def prepare_smart_view_from_filter(
    uuids: list[str],
    *,
    name: str,
    target: dict[str, Any],
    description: str | None = None,
    color: str = DEFAULT_FILTER_SMARTVIEW_COLOR,
    element_by_uuid: dict | None = None,
) -> WritePlan:
    """Construit un :class:`WritePlan` (kind=SMART_VIEWS) colorant une
    sélection libre d'UUID — la matérialisation durable d'une sélection
    ``filter_bim_objects`` en Smart View BIMData.

    Une seule Smart View (un groupe de coloring, couleur unique) est produite.
    Réutilise le pipeline apply existant (:func:`apply_smart_views`) : aucun
    chemin d'écriture spécifique. ``description`` est conservée **uniquement**
    dans le ``summary`` du plan (à des fins de traçabilité) et n'est pas
    injectée dans le payload : un champ ``description`` ferait disparaître la
    Smart View du panneau dédié du viewer.

    Args:
        uuids: Jeu de sélection complet à colorer (cf.
            :func:`resolve_object_selection`).
        name: Titre de la Smart View (utilisé tel quel, sans préfixe).
        target: Cible BIMData (``cloud_id``/``project_id``/``model_id``) ;
            scellée dans le plan et revalidée à l'apply.
        description: Note libre tracée dans le plan (hors payload).
        color: Couleur hex ``#RRGGBB`` du coloring (défaut ``#FF3D1E``).
        element_by_uuid: Index ``uuid -> élément`` du snapshot (noms Revit).

    Façade → ``bim_publication.prepare_smart_view_from_filter`` (signature
    identique, aucun ``AuditResult`` en jeu).
    """
    return _pub_prepare_svff(
        uuids,
        name=name,
        target=target,
        description=description,
        color=color,
        element_by_uuid=element_by_uuid,
    )


def prepare_smart_views(
    result: AuditResult,
    *,
    finding_filter: FindingFilter | None = None,
    target: dict[str, Any],
    prefix: str = "I3F Audit — ",
    include_overview: bool = True,
) -> WritePlan:
    """Construit un :class:`WritePlan` pour création de Smart Views.

    Mêmes paramètres que :func:`prepare_bcf` ; cf. docstring. Façade →
    ``bim_publication.prepare_smart_views`` : adapte l'``AuditResult``
    (``findings`` + ``phase`` + ``element_by_uuid`` du snapshot).
    """
    element_by_uuid = getattr(result.snapshot, "element_by_uuid", None) or {}
    return _pub_prepare_sv(
        result.findings,
        phase=result.phase.value,
        target=target,
        finding_filter=finding_filter,
        prefix=prefix,
        include_overview=include_overview,
        element_by_uuid=element_by_uuid,
    )


def apply_smart_views(
    plan: WritePlan,
    client: BIMDataClient,
    *,
    actual_target: dict[str, Any] | None = None,
) -> ActionResult:
    """Exécute un plan Smart Views préalablement scellé."""

    def _execute(plan: WritePlan, client: BIMDataClient) -> ApplyOutcome:
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
                errors.append({"title": str(title), "message": redact_secrets(str(exc))})
        return ApplyOutcome(
            succeeded,
            failed,
            impacted_titles,
            result_errors=errors,
            extra={"errors_sample": errors[:5]},
        )

    return run_apply(
        plan,
        client,
        expected_kind=WritePlanKind.SMART_VIEWS,
        action="apply_smart_views",
        actual_target=actual_target,
        executor=_execute,
    )
