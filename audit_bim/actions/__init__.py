"""Actions de sortie — pattern *prepare → validate → apply*.

Toute opération qui modifie BIMData passe par ce package :

1. ``prepare_*`` calcule un :class:`audit_bim.domain.WritePlan` et le
   sérialise sous ``AUDIT_OUTPUT_DIR/plans/<plan_id>.json``.
2. ``apply_*`` recharge le plan, vérifie son intégrité (scellé SHA-256
   sur les items + cible), exécute les appels API, puis journalise via
   :class:`audit_bim.security.WriteJournal`.

Aucune écriture BIMData n'est faite sans ``confirm=True`` côté tool MCP,
et sans qu'un :class:`WritePlan` ait été validé.
"""

from __future__ import annotations

from .bcf_planner import apply_bcf, prepare_bcf
from .classification_planner import (
    apply_classification_update,
    prepare_classification_update,
)
from .doe_planner import apply_doe_enrichment, prepare_doe_enrichment
from .plans import (
    PlanIntegrityError,
    PlanTargetMismatchError,
    compute_plan_checksum,
    list_plans,
    load_plan,
    save_plan,
    validate_target,
)
from .smartview_planner import (
    apply_smart_views,
    prepare_smart_view_from_filter,
    prepare_smart_views,
)

__all__ = [
    "compute_plan_checksum",
    "save_plan",
    "load_plan",
    "list_plans",
    "validate_target",
    "PlanIntegrityError",
    "PlanTargetMismatchError",
    "prepare_bcf",
    "apply_bcf",
    "prepare_smart_views",
    "prepare_smart_view_from_filter",
    "apply_smart_views",
    "prepare_classification_update",
    "apply_classification_update",
    "prepare_doe_enrichment",
    "apply_doe_enrichment",
]
