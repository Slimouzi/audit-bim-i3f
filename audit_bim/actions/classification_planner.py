"""Planner classifications — prepare/apply via :class:`WritePlan`.

Consomme :class:`ClassificationSuggestionStore` et
:class:`SuggestionFilter` pour ne traiter qu'un sous-ensemble explicite
de suggestions (statut ``accepted`` par défaut). Délègue l'exécution à
:func:`audit_bim.classifier.applier.apply_classifications`.

Cycle de vie attendu côté MCP :

1. ``list_classification_suggestions`` — l'AMO BIM filtre / revoit.
2. ``accept_classification_suggestion`` / ``reject_*`` — bascule les
   statuts (tool MCP à venir, peut être déjà couvert via
   :meth:`ClassificationSuggestionStore.update_status`).
3. ``prepare_classification_update(suggestion_filter=...)`` — calcule
   le plan, sceller.
4. ``apply_classification_update(plan_path, confirm=True)`` — pousse.
"""

from __future__ import annotations

import logging
from typing import Any

from ..classifier.applier import apply_classifications
from ..classifier.suggestion_store import ClassificationSuggestionStore
from ..domain.filters import SuggestionFilter, SuggestionStatus
from ..domain.write_plan import ActionResult, WritePlan, WritePlanKind
from ..extraction.client import BIMDataClient
from ..query.filtering import suggestion_matches
from ..security.redaction import redact_secrets
from ._apply_runtime import ApplyOutcome, run_apply

logger = logging.getLogger("audit_bim.actions.classification")


def prepare_classification_update(
    store: ClassificationSuggestionStore,
    *,
    suggestion_filter: SuggestionFilter | None = None,
    target: dict[str, Any],
    default_status_scope: SuggestionStatus | None = SuggestionStatus.ACCEPTED,
) -> WritePlan:
    """Construit un :class:`WritePlan` pour application de classifications.

    Args:
        store: Store de suggestions de la session.
        suggestion_filter: Filtre déclaratif. Si ``None``, on filtre
            implicitement sur ``default_status_scope`` (par défaut
            ``ACCEPTED``) — règle saine : on ne pousse que ce qui a été
            explicitement validé.
        target: Cible BIMData.
        default_status_scope: Statut implicite quand
            ``suggestion_filter`` est ``None``. ``None`` désactive le
            défaut (= pousse tout ce qui matche).

    Returns:
        :class:`WritePlan` (kind=CLASSIFICATION_UPDATE). Les ``items``
        contiennent ``{element_uuid, code, label, system,
        confidence, current_classification, mismatch}`` — détail
        complet pour la revue manuelle.
    """
    f = suggestion_filter
    if f is None:
        if default_status_scope is None:
            f = SuggestionFilter()
        else:
            f = SuggestionFilter(statuses=[default_status_scope])

    # Pas de pagination — un planner traite tout le périmètre filtré.
    matched = [e for e in store.all() if suggestion_matches(e, f)]

    items: list[dict[str, Any]] = []
    n_overwrite = 0
    for entry in matched:
        will_overwrite = (
            entry.current_classification is not None and entry.current_classification.strip() != ""
        )
        if will_overwrite:
            n_overwrite += 1
        items.append(
            {
                "element_uuid": entry.element_uuid,
                "ifc_type": entry.ifc_type,
                "code": entry.proposed_classification,
                "label": entry.proposed_label or entry.proposed_classification,
                "system": entry.proposed_system,
                "confidence": entry.confidence,
                "confidence_band": entry.confidence_band.value,
                "current_classification": entry.current_classification,
                "current_classification_system": entry.current_classification_system,
                "mismatch": entry.is_mismatch,
                "status": entry.status.value,
            }
        )

    risks: list[str] = []
    if not items:
        risks.append("Aucune suggestion ne matche le filtre — 0 classification à pousser.")
    if n_overwrite:
        risks.append(
            f"{n_overwrite} éléments ont déjà une classification — "
            "écrasement par la valeur proposée à l'apply."
        )

    summary = {
        "n_classifications": len(items),
        "n_overwrite": n_overwrite,
        "n_missing_current": sum(1 for i in items if not i.get("current_classification")),
        "filter_applied": suggestion_filter is not None,
        "default_status_scope": (default_status_scope.value if default_status_scope else None),
    }

    return WritePlan(
        kind=WritePlanKind.CLASSIFICATION_UPDATE,
        target=target,
        summary=summary,
        items=items,
        risks=risks,
    )


def apply_classification_update(
    plan: WritePlan,
    client: BIMDataClient,
    *,
    store: ClassificationSuggestionStore | None = None,
    actual_target: dict[str, Any] | None = None,
) -> ActionResult:
    """Exécute un plan de classifications préalablement scellé.

    Args:
        plan: Plan rechargé via :func:`load_plan`.
        client: Client BIMData authentifié.
        store: Si fourni, les statuts des entrées correspondantes
            passent à ``APPLIED`` après succès.
        actual_target: Cible courante pour validation.

    Returns:
        :class:`ActionResult`.
    """

    def _execute(plan: WritePlan, client: BIMDataClient) -> ApplyOutcome:
        # Mappe les items vers la signature attendue par apply_classifications.
        api_items = [
            {
                "uuid": it["element_uuid"],
                "code": it["code"],
                "label": it.get("label") or it["code"],
                "system": it.get("system") or "uniformat",
            }
            for it in plan.items
        ]

        api_result = apply_classifications(client, api_items, dry_run=False)

        # ``apply_classifications`` expose désormais ``linked_uuids`` /
        # ``failed_uuids`` — on ne bascule en APPLIED que ceux réellement
        # liés (cf. revue CTO : éviter de marquer APPLIED un UUID dont la
        # création de classification a échoué mais qui était dans le plan).
        linked_uuids: list[str] = list(api_result.get("linked_uuids") or [])
        failed_uuids: list[str] = list(api_result.get("failed_uuids") or [])

        # Met à jour le store : seuls les UUIDs réellement liés passent en
        # APPLIED. Les autres conservent leur statut (ACCEPTED en général)
        # pour permettre un rerun ciblé.
        if store is not None:
            for uid in linked_uuids:
                store.update_status(uid, SuggestionStatus.APPLIED)

        # Scrub des erreurs avant journal/retour MCP : un message HTTP peut
        # contenir une URL signée ou un en-tête Authorization.
        scrubbed_errors = [redact_secrets(str(e)) for e in (api_result.get("errors") or [])]

        return ApplyOutcome(
            len(linked_uuids),
            len(failed_uuids),
            linked_uuids,
            result_errors=[{"uuid": "?", "message": msg} for msg in scrubbed_errors],
            extra={
                "n_classifications_created": api_result.get("n_classifications_created"),
                "n_classifications_reused": api_result.get("n_classifications_reused"),
                "link_failed": api_result.get("link_failed"),
                "failed_uuids_count": len(failed_uuids),
                "errors_sample": scrubbed_errors[:5],
            },
        )

    return run_apply(
        plan,
        client,
        expected_kind=WritePlanKind.CLASSIFICATION_UPDATE,
        action="apply_classification_update",
        actual_target=actual_target,
        executor=_execute,
    )
