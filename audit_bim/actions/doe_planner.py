"""Planner DOE → IFC — prepare/apply via :class:`WritePlan`.

Réutilise :

- :func:`audit_bim.doe.matcher.match_doe_records` côté matching ;
- :func:`audit_bim.doe.conflicts.detect_conflicts` côté pré-calcul ;
- :func:`audit_bim.doe.enricher.apply_matches_to_model` côté écriture
  (en interne dans :func:`apply_doe_enrichment`).

Pré-calcul des conflits côté ``prepare`` : on classifie chaque
propriété DOE comme ``MATCH`` / ``NEW`` / ``UPGRADE`` / ``CONFLICT``
avant exécution, ce qui permet à l'AMO de :

1. Voir les risques d'écrasement dans le ``WritePlan.risks`` ;
2. Décider du ``on_conflict`` (``report`` par défaut, ``overwrite`` si
   le DOE est autoritaire).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from ..doe.conflicts import (
    ConflictReport,
    ConflictType,
    detect_conflicts,
    summarize_conflicts,
)
from ..doe.models import Match
from ..domain.write_plan import ActionResult, WritePlan, WritePlanKind
from ..extraction.client import BIMDataClient
from ..extraction.model_data import ModelSnapshot
from ..security.redaction import redact_secrets
from ..security.write_journal import get_journal
from .plans import validate_target

logger = logging.getLogger("audit_bim.actions.doe")


def _infer_value_type(value) -> str:
    """Type IFC inféré depuis la valeur Python (cf. enricher._infer_value_type)."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    return "string"


def _build_pset_payload(pset_name: str, props: dict[str, Any]) -> dict[str, Any]:
    """Construit le payload BIMData POST /element/{uuid}/propertyset."""
    return {
        "name": pset_name,
        "description": "Enrichissement automatique depuis DOE (audit-bim-i3f)",
        "properties": [
            {
                "definition": {
                    "name": str(prop_name),
                    "value_type": _infer_value_type(value),
                    "type": "IfcPropertySingleValue",
                },
                "value": value,
            }
            for prop_name, value in props.items()
        ],
    }


def _filter_props_by_conflict(
    pset_name: str,
    props: dict,
    reports: list[ConflictReport],
    *,
    on_conflict: str,
) -> tuple[dict, list[str]]:
    """Reproduit la logique de
    :func:`audit_bim.doe.enricher._filter_props_by_conflict`.

    Pourquoi dupliquer : le planner doit pouvoir matérialiser ce qui sera
    écrit **avant** d'appeler ``apply_*`` (le plan contient le détail).
    Centraliser cette logique dans un helper partagé entraînerait un
    cycle d'import (actions ↔ doe). On préfère la duplication explicite
    (≤ 30 LoC) — couverte par les tests d'enricher existants et par les
    tests dédiés au planner.
    """
    by_prop = {r.property: r for r in reports if r.pset == pset_name and r.property in props}
    to_write: dict = {}
    skipped: list[str] = []
    for prop_name, doe_value in props.items():
        rep = by_prop.get(prop_name)
        if rep is None:
            to_write[prop_name] = doe_value
            continue
        if rep.type == ConflictType.MATCH:
            skipped.append(prop_name)
            continue
        if rep.type == ConflictType.CONFLICT and on_conflict != "overwrite":
            skipped.append(prop_name)
            continue
        to_write[prop_name] = doe_value
    return to_write, skipped


def prepare_doe_enrichment(
    matches: Iterable[Match],
    *,
    snapshot: ModelSnapshot,
    target: dict[str, Any],
    on_conflict: str = "report",
    source_label: str | None = None,
) -> WritePlan:
    """Construit un :class:`WritePlan` d'enrichissement DOE — **sans écrire**.

    Args:
        matches: Itérable de :class:`Match` produit par ``match_doe_records``.
        snapshot: ``ModelSnapshot`` pour pré-calcul des conflits.
        target: Cible BIMData (cloud/project/model + nom).
        on_conflict: ``"report"`` (défaut, prudent) / ``"skip"`` / ``"overwrite"``.
            Voir :func:`audit_bim.doe.enricher.apply_matches_to_model`.
        source_label: Étiquette du fichier DOE source (debug / journal).

    Returns:
        :class:`WritePlan` (kind=``DOE_ENRICHMENT``) avec ``items`` ::

            [{
                "element_uuid": "...",
                "ifc_type": "...",
                "ifc_name": "...",
                "pset_name": "Pset_3F",
                "payload": {...},   # tel quel pour POST
                "props_to_write": {"Fabricant": "BOSCH", ...},
                "skipped_properties": ["Reference"],  # conflits non écrasés
                "confidence": 0.92,
                "strategy": "guid",
            }, ...]

    ``risks`` mentionne notamment :
        - le nombre d'éléments non matchés (record DOE sans IFC) ;
        - le nombre de conflits CONFLICT (≠ entre maquette et DOE) ;
        - les conséquences de ``on_conflict=overwrite``.
    """
    matches_list = list(matches)
    matched = [m for m in matches_list if m.is_matched()]
    n_unmatched = len(matches_list) - len(matched)

    # Pré-calcul des conflits
    conflict_reports = detect_conflicts(matched, snapshot)
    reports_by_uuid: dict[str, list[ConflictReport]] = {}
    for r in conflict_reports:
        reports_by_uuid.setdefault(r.element_uuid, []).append(r)
    conflicts_summary = summarize_conflicts(conflict_reports)

    items: list[dict[str, Any]] = []
    n_props_to_write = 0
    n_props_skipped = 0
    for m in matched:
        match_reports = reports_by_uuid.get(m.ifc_uuid or "", [])
        for pset_name, props in (m.record.properties or {}).items():
            if not props:
                continue
            props_to_write, skipped_names = _filter_props_by_conflict(
                pset_name, props, match_reports, on_conflict=on_conflict
            )
            n_props_skipped += len(skipped_names)
            if not props_to_write:
                continue
            payload = _build_pset_payload(pset_name, props_to_write)
            items.append(
                {
                    "element_uuid": m.ifc_uuid,
                    "ifc_type": m.ifc_type,
                    "ifc_name": m.ifc_name,
                    "pset_name": pset_name,
                    "payload": payload,
                    "props_to_write": props_to_write,
                    "skipped_properties": skipped_names,
                    "confidence": m.confidence,
                    "strategy": m.strategy,
                }
            )
            n_props_to_write += len(props_to_write)

    # ``summarize_conflicts`` renvoie ``{n_total, by_type: {match, new,
    # upgrade, conflict}}`` — on cherche dans ``by_type``.
    n_conflicts = (conflicts_summary or {}).get("by_type", {}).get(ConflictType.CONFLICT.value, 0)

    risks: list[str] = []
    if not items and n_unmatched == 0 and not matched:
        risks.append("Aucun match DOE — 0 Pset à écrire.")
    if n_unmatched > 0:
        risks.append(f"{n_unmatched} record(s) DOE non rapproché(s) à un élément IFC — ignorés.")
    if n_conflicts > 0:
        if on_conflict == "overwrite":
            risks.append(
                f"on_conflict='overwrite' : {n_conflicts} valeur(s) existante(s) "
                "seront écrasées par la valeur DOE."
            )
        else:
            risks.append(
                f"{n_conflicts} conflit(s) détecté(s) — propriétés non écrasées "
                f"(on_conflict='{on_conflict}'). Voir audit_trail après apply."
            )

    summary = {
        "n_matched": len(matched),
        "n_unmatched": n_unmatched,
        "n_psets_planned": len(items),
        "n_properties_planned": n_props_to_write,
        "n_properties_skipped": n_props_skipped,
        "on_conflict": on_conflict,
        "conflicts_summary": conflicts_summary,
        "source": source_label,
    }

    return WritePlan(
        kind=WritePlanKind.DOE_ENRICHMENT,
        target=target,
        summary=summary,
        items=items,
        risks=risks,
    )


def apply_doe_enrichment(
    plan: WritePlan,
    client: BIMDataClient,
    *,
    actual_target: dict[str, Any] | None = None,
) -> ActionResult:
    """Exécute un plan d'enrichissement DOE préalablement scellé.

    Pour chaque item du plan, POST le Pset sur l'élément IFC matché.
    Journalise via :class:`WriteJournal` ; scrub des erreurs API via
    :func:`redact_secrets`.

    Args:
        plan: Plan rechargé via :func:`load_plan` (intégrité vérifiée).
        client: Client BIMData authentifié.
        actual_target: Cible courante pour validation. Défaut : déduite
            du client.

    Returns:
        :class:`ActionResult` (succeeded / failed / errors / impacted_uuids).
    """
    if plan.kind != WritePlanKind.DOE_ENRICHMENT:
        raise ValueError(f"Plan de kind={plan.kind!r}, attendu={WritePlanKind.DOE_ENRICHMENT!r}.")

    if actual_target is None:
        actual_target = {
            "cloud_id": client.cloud_id,
            "project_id": client.project_id,
            "model_id": client.model_id,
        }
    validate_target(plan, actual_target=actual_target)

    succeeded = 0
    failed = 0
    impacted_uuids: list[str] = []
    errors: list[dict[str, str]] = []
    seen_uuids: set[str] = set()

    for item in plan.items:
        element_uuid = item.get("element_uuid")
        pset_name = item.get("pset_name")
        payload = item.get("payload") or {}
        if not element_uuid or not payload:
            continue
        try:
            client.write_element_propertyset(element_uuid, payload)
            succeeded += 1
            if element_uuid not in seen_uuids:
                seen_uuids.add(element_uuid)
                impacted_uuids.append(element_uuid)
        except Exception as exc:  # noqa: BLE001 (capture pour journal)
            failed += 1
            errors.append(
                {
                    "element_uuid": str(element_uuid),
                    "pset": str(pset_name),
                    "message": redact_secrets(str(exc)),
                }
            )

    get_journal().record(
        action="apply_doe_enrichment",
        plan_id=plan.plan_id,
        plan_kind=plan.kind.value,
        target=plan.target,
        succeeded=succeeded,
        failed=failed,
        impacted_uuids=impacted_uuids,
        extra={
            "n_psets_pushed": succeeded,
            "n_psets_failed": failed,
            "on_conflict": (plan.summary or {}).get("on_conflict"),
            "source": (plan.summary or {}).get("source"),
            "errors_sample": errors[:5],
        },
    )

    return ActionResult(
        plan_id=plan.plan_id,
        kind=plan.kind,
        succeeded=succeeded,
        failed=failed,
        impacted_uuids=impacted_uuids,
        errors=[
            {"uuid": e.get("element_uuid", "?"), "message": e.get("message", "")} for e in errors
        ],
    )
