"""Persistance et intégrité des :class:`WritePlan`.

Un plan est écrit en JSON sous ``AUDIT_OUTPUT_DIR/plans/<plan_id>.json``
avec un **scellé SHA-256** calculé sur le payload — hors champs volatiles
(``plan_id``, ``created_at``). ``load_plan`` recalcule le scellé et
refuse les plans altérés (sauf bypass explicite pour les tests).

Pourquoi un scellé
------------------

Le pattern *prepare → apply* sépare la décision (humain ou agent qui
valide le plan) de l'exécution. Entre les deux, le fichier peut être
édité — volontairement ou non. Le scellé garantit qu'``apply`` exécute
**exactement** ce qui a été validé.

Validation de cible
-------------------

Avant exécution, on vérifie que le client BIMData actif pointe sur la
**même** cible (cloud + project + model) que le plan. Un AMO peut avoir
changé de maquette entre ``prepare`` et ``apply`` ; on refuse plutôt
que d'écrire dans le mauvais modèle.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..domain.write_plan import WritePlan
from ..safe_paths import (
    get_export_root,
    safe_export_dir,
    safe_export_path,
    safe_export_read_path,
)

PLANS_SUBDIR = "plans"

CHECKSUM_FIELD = "_sealed_sha256"


class PlanIntegrityError(ValueError):
    """Le scellé du plan ne correspond pas — fichier altéré."""


class PlanTargetMismatchError(ValueError):
    """Le client BIMData actif ne pointe pas sur la cible du plan."""


# ── Sérialisation scellée ────────────────────────────────────────────────


def _canonical_payload(plan: WritePlan) -> dict[str, Any]:
    """Payload utilisé pour le calcul du checksum.

    Exclut les champs volatiles (``plan_id``, ``created_at``) : un même
    contenu logique produit le même scellé même s'il est re-prepare à
    quelques secondes d'écart.
    """
    raw = plan.model_dump(mode="json")
    raw.pop("plan_id", None)
    raw.pop("created_at", None)
    return raw


def compute_plan_checksum(plan: WritePlan) -> str:
    """Calcule le SHA-256 hexadécimal d'un :class:`WritePlan`.

    Le checksum est stable pour un même contenu (sérialisation canonique
    triée par clé).
    """
    payload = _canonical_payload(plan)
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _plans_dir() -> Path:
    """Racine des plans (créée si absente, sous AUDIT_OUTPUT_DIR)."""
    return safe_export_dir(PLANS_SUBDIR)


def save_plan(plan: WritePlan) -> Path:
    """Sérialise le plan sur disque (sandbox) et retourne le chemin.

    Le fichier contient le payload du plan **plus** le champ
    ``_sealed_sha256`` calculé. La présence d'un ``items_path`` séparé
    est conservée — le scellé porte sur la référence, pas sur le détail.
    """
    plans_dir = _plans_dir()
    target = plans_dir / f"{plan.plan_id}.json"
    # safe_export_path valide qu'on reste sous AUDIT_OUTPUT_DIR.
    final_path = safe_export_path(target.relative_to(get_export_root()), overwrite=True)

    payload = plan.model_dump(mode="json")
    payload[CHECKSUM_FIELD] = compute_plan_checksum(plan)
    final_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return final_path


def load_plan(path: str | Path, *, verify_checksum: bool = True) -> WritePlan:
    """Recharge un plan depuis le disque.

    Args:
        path: Chemin (absolu ou relatif à ``AUDIT_OUTPUT_DIR``) du
            fichier plan.
        verify_checksum: Si ``True`` (défaut), refuse les plans dont le
            scellé ne matche pas (:class:`PlanIntegrityError`). Bypass
            uniquement pour les tests ou la migration de fichiers
            anciens.

    Raises:
        FileNotFoundError: Plan inexistant.
        PlanIntegrityError: Checksum invalide.
        UnsafePathError: Chemin hors ``AUDIT_OUTPUT_DIR`` ou contenant ``..``.
    """
    # Sandbox strict : tout chemin (absolu ou relatif) doit être
    # contenu sous AUDIT_OUTPUT_DIR. Un client MCP ne doit pas pouvoir
    # faire pointer apply_* vers un fichier hors racine via plan_path.
    p = safe_export_read_path(path, must_exist=True)
    payload = json.loads(p.read_text(encoding="utf-8"))
    stored_checksum = payload.pop(CHECKSUM_FIELD, None)
    plan = WritePlan.model_validate(payload)
    if verify_checksum:
        recomputed = compute_plan_checksum(plan)
        if stored_checksum is None or stored_checksum != recomputed:
            raise PlanIntegrityError(
                f"Plan {p.name} altéré ou non scellé : "
                f"checksum stocké={stored_checksum!r}, recalculé={recomputed!r}."
            )
    return plan


def list_plans(*, limit: int = 20) -> list[dict[str, Any]]:
    """Liste les plans récents avec résumé compact.

    Args:
        limit: Nombre maximum de plans retournés (les plus récents).

    Returns:
        Liste de dicts ``{plan_id, kind, created_at, path, summary,
        n_items, requires_confirm}`` triée par ``created_at`` décroissant.
    """
    plans_dir = _plans_dir()
    items: list[dict[str, Any]] = []
    for child in plans_dir.glob("*.json"):
        try:
            raw = json.loads(child.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append(
            {
                "plan_id": raw.get("plan_id"),
                "kind": raw.get("kind"),
                "created_at": raw.get("created_at"),
                "path": str(child),
                "summary": raw.get("summary") or {},
                "n_items": len(raw.get("items") or []) or (raw.get("summary") or {}).get("n_items"),
                "requires_confirm": raw.get("requires_confirm", True),
            }
        )
    items.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    return items[:limit]


# ── Validation de cible ──────────────────────────────────────────────────


def validate_target(plan: WritePlan, *, actual_target: dict[str, Any]) -> None:
    """Vérifie que la cible courante matche celle du plan.

    On compare ``cloud_id``, ``project_id`` et ``model_id`` (str-cast).
    Tout mismatch lève :class:`PlanTargetMismatchError`.
    """
    expected = plan.target or {}

    def _norm(d: dict[str, Any], key: str) -> str | None:
        v = d.get(key)
        return None if v is None else str(v)

    for key in ("cloud_id", "project_id", "model_id"):
        e = _norm(expected, key)
        a = _norm(actual_target, key)
        if e is None:
            # Plan sans cible explicite — on ne refuse pas (compat).
            continue
        if e != a:
            raise PlanTargetMismatchError(
                f"Cible {key} ne correspond pas au plan : plan={e!r}, courant={a!r}."
            )
