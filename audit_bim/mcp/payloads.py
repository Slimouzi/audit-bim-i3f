"""Helpers partagés entre les modules de tools MCP.

Ce module concentre les utilitaires utilisés par ``tools_query``,
``tools_actions`` et les wrappers legacy :

- :data:`MCP_RESPONSE_INLINE_LIMIT` — seuil overflow disque (256 KB).
- :func:`maybe_dump_to_disk` — applique la stratégie 256 KB / output_path.
- :func:`current_target` — snapshot ``cloud/project/model`` de la session.
- :func:`plan_summary_response` — réponse compacte d'un ``prepare_*``.
- :func:`refused_without_confirm` — refus standardisé d'un ``apply_*``.
- :func:`populate_suggestion_store_from_audit`,
  :func:`ensure_suggestion_store` — lazy-init du store de session.

Pas de tool MCP enregistré ici. Pas de dépendance circulaire vers
``server`` (ce module est importé par ``server.py`` indirectement via
les modules ``tools_*``).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from ..classifier.suggester import suggest as _suggest_for_element
from ..classifier.suggestion_store import (
    ClassificationSuggestionEntry,
    ClassificationSuggestionStore,
)
from ..domain.filters import ConfidenceBand
from ..safe_paths import safe_export_path
from .session import _State

if TYPE_CHECKING:
    from ..domain.write_plan import WritePlan

logger = logging.getLogger("audit_bim.mcp.payloads")


# Seuil au-delà duquel les tools écrivent le détail sur disque au lieu
# de le renvoyer côté canal MCP. Calibré pour rester largement sous la
# limite 1 MB des tool_results MCP.
MCP_RESPONSE_INLINE_LIMIT = 256 * 1024  # 256 KB JSON UTF-8


def maybe_dump_to_disk(
    payload: dict,
    *,
    output_path: str | None,
    default_basename: str,
) -> dict:
    """Si ``output_path`` est fourni OU si le payload sérialisé dépasse
    256 KB, écrit le détail sur disque sous ``AUDIT_OUTPUT_DIR`` et
    retourne un payload compact avec ``items_path`` au lieu de ``items``.

    Garde le contrat MCP < 1 MB.
    """
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    too_big = len(raw.encode("utf-8")) > MCP_RESPONSE_INLINE_LIMIT
    if not output_path and not too_big:
        return payload

    # Détermine le chemin d'écriture (validé sandbox).
    target = output_path or f"{default_basename}.json"
    path = safe_export_path(target, overwrite=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    items = payload.get("items", [])
    compact = {k: v for k, v in payload.items() if k not in ("items", "uuids")}
    compact["items"] = items[:5]  # 5 items en aperçu seulement
    compact["items_path"] = str(path)
    compact["items_truncated"] = True
    compact["items_count_in_response"] = min(5, len(items))
    # ``uuids`` (jeu de sélection complet, ex. filter_bim_objects) peut à
    # lui seul dépasser la limite inline : on l'aperçoit aussi et on expose
    # son cardinal. Le JSON complet (tous les uuids) est dans ``items_path``.
    if "uuids" in payload:
        uuids = payload.get("uuids") or []
        compact["uuids"] = uuids[:50]
        compact["uuids_count"] = len(uuids)
        compact["uuids_truncated"] = len(uuids) > 50
    return compact


def current_target() -> dict[str, Any]:
    """Snapshot de la cible BIMData courante, pour ``WritePlan.target``."""
    model_name = None
    if _State.snapshot is not None:
        model_name = (_State.snapshot.model or {}).get("name")
    return {
        "cloud_id": _State.cloud_id,
        "project_id": _State.project_id,
        "model_id": _State.model_id,
        "model_name": model_name,
    }


def plan_summary_response(plan: WritePlan, path) -> dict[str, Any]:
    """Réponse compacte pour les tools ``prepare_*``."""
    return {
        "plan_id": plan.plan_id,
        "plan_path": str(path),
        "kind": plan.kind.value,
        "target": plan.target,
        "summary": plan.summary,
        "risks": plan.risks,
        "n_items": len(plan.items),
        "requires_confirm": True,
        "created_at": plan.created_at,
    }


def refused_without_confirm(action: str) -> dict[str, Any]:
    """Retour standardisé d'un ``apply_*`` appelé sans ``confirm=True``."""
    return {
        "refused": True,
        "action": action,
        "reason": (
            "confirm=False — exécution refusée. Repassez le tool avec "
            "confirm=True pour exécuter le plan."
        ),
    }


def populate_suggestion_store_from_audit(*, force_refresh: bool = False) -> None:
    """Construit le :class:`ClassificationSuggestionStore` à partir des
    findings ``classification_missing`` / ``classification_invalid``.

    Les entrées existantes en statut ``accepted`` / ``rejected`` /
    ``applied`` sont préservées (sauf ``force_refresh=True``).
    """
    _State.ensure_result()
    if _State.suggestion_store is None or force_refresh:
        _State.suggestion_store = ClassificationSuggestionStore()

    store: ClassificationSuggestionStore = _State.suggestion_store
    snapshot = _State.result.snapshot

    for finding in _State.result.findings:
        et = finding.error_type.value
        if et not in ("classification_missing", "classification_invalid"):
            continue
        uuid = finding.element_uuid
        if not uuid:
            continue
        # Préserve les statuts non-proposed déjà enregistrés.
        existing = store.get(uuid)
        if existing is not None and existing.status.value != "proposed":
            continue

        element = snapshot.element_by_uuid.get(uuid)
        if not element:
            continue
        sugs = _suggest_for_element(element)
        sugs = [s for s in sugs if s.confidence > 0]
        if not sugs:
            continue
        top = sugs[0]

        current = None
        current_system = None
        if finding.actual:
            actual = finding.actual
            if isinstance(actual, dict):
                current = actual.get("code") or actual.get("identifier")
                current_system = actual.get("system") or actual.get("source")
            elif isinstance(actual, str):
                current = actual

        entry = ClassificationSuggestionEntry(
            element_uuid=uuid,
            ifc_type=finding.ifc_type,
            current_classification=current,
            current_classification_system=current_system,
            proposed_classification=top.classification.code,
            proposed_label=top.classification.label,
            proposed_system=(top.classification.system or "uniformat").lower(),
            proposed_level_3=top.classification.code.upper()[:5],
            confidence=round(top.confidence, 3),
            confidence_band=ConfidenceBand.from_score(top.confidence),
            reason_codes=[r.split(" ", 1)[0].lower() for r in top.reasons][:5],
            evidence={"reasons": top.reasons},
            alternatives=[s.as_dict() for s in sugs[1:3]],
            source="audit",
        )
        store.add(entry, replace=True)


def ensure_suggestion_store(*, populate_if_empty: bool = True) -> ClassificationSuggestionStore:
    """Renvoie le store de la session courante, en le peuplant depuis
    l'audit si nécessaire."""
    if _State.suggestion_store is None or (populate_if_empty and len(_State.suggestion_store) == 0):
        populate_suggestion_store_from_audit()
    if _State.suggestion_store is None:  # défensif (ne devrait pas arriver)
        _State.suggestion_store = ClassificationSuggestionStore()
    return _State.suggestion_store


__all__ = [
    "MCP_RESPONSE_INLINE_LIMIT",
    "maybe_dump_to_disk",
    "current_target",
    "plan_summary_response",
    "refused_without_confirm",
    "populate_suggestion_store_from_audit",
    "ensure_suggestion_store",
]
