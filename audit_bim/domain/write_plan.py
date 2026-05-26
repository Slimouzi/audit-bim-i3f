"""Squelettes :class:`WritePlan` et :class:`ActionResult` — pattern prepare/apply.

Ces modèles sont introduits en *tranche 1* mais ne sont pas encore
utilisés par les tools MCP (tranche 2). Ils sont publiés ici pour figer
leur interface tôt — les `prepare_*` / `apply_*` à venir produiront /
consommeront exactement ces objets.

Cycle de vie attendu (tranche 2)
--------------------------------

1. ``prepare_X(filter, …) → WritePlan`` — calcule mais n'écrit rien.
   Sérialisé sur disque sous ``AUDIT_OUTPUT_DIR``, retour MCP compact
   (résumé + chemin).
2. ``validate_X(plan_path) → bool`` (interne) — recharge le plan,
   vérifie cohérence, modèle cible, taille, permissions.
3. ``apply_X(plan_path, confirm=True) → ActionResult`` — exécute les
   appels API et journalise.

L'utilisateur doit **explicitement** passer ``confirm=True`` pour
qu'``apply_*`` aille au-delà du dry-run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class WritePlanKind(str, Enum):
    """Type d'opération encapsulée dans un :class:`WritePlan`."""

    CLASSIFICATION_UPDATE = "classification_update"
    BCF_TOPICS = "bcf_topics"
    SMART_VIEWS = "smart_views"
    DOE_ENRICHMENT = "doe_enrichment"
    PROPERTY_INJECTION = "property_injection"


class WritePlan(BaseModel):
    """Description d'une opération d'écriture, **sans exécution**.

    Sérialisable JSON, persistable sur disque, rechargeable pour `apply_*`.
    Les champs sont conçus pour que la revue manuelle (humain ou agent)
    suffise à valider le plan avant d'autoriser ``confirm=True``.

    Attributes:
        plan_id: Identifiant unique du plan (uuid4).
        kind: Type d'opération (cf. :class:`WritePlanKind`).
        created_at: Timestamp UTC ISO 8601 de génération.
        target: Référence du modèle cible (cloud/project/model + nom).
        summary: Résumé compact pour exposition MCP (nb d'objets touchés,
            nb d'appels API, risques détectés).
        items: Détail des opérations unitaires (UUID, ancien état, nouvel
            état). Volumineux — souvent écrit sur disque séparément, et
            référencé via ``items_path``.
        items_path: Chemin sur disque vers les items si non inlinés.
        risks: Liste de risques identifiés à la validation (ex: « 3
            éléments ont déjà une classification UniFormat — écrasement
            silencieux »).
        requires_confirm: Toujours True — sécurité explicite.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: WritePlanKind
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    target: dict[str, Any] = Field(
        default_factory=dict,
        description="cloud_id / project_id / model_id / model_name.",
    )

    summary: dict[str, Any] = Field(default_factory=dict)

    items: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Items détaillés (vide si stockés sur disque, cf. items_path).",
    )
    items_path: str | None = Field(
        None,
        description="Chemin absolu vers le JSON détaillé sous AUDIT_OUTPUT_DIR.",
    )

    risks: list[str] = Field(default_factory=list)
    requires_confirm: bool = True


class ActionResult(BaseModel):
    """Résultat d'une opération ``apply_*``.

    Toujours retourné même en cas d'échec partiel — les tools MCP
    présentent les compteurs et les erreurs sans rejeter d'exception.

    Attributes:
        plan_id: Référence vers le :class:`WritePlan` source.
        kind: Type d'opération exécutée.
        succeeded: Nombre d'items exécutés avec succès.
        failed: Nombre d'items en erreur.
        skipped: Nombre d'items volontairement ignorés (déjà à l'état
            cible, conflit non résolu …).
        executed_at: Timestamp UTC ISO 8601 d'exécution.
        impacted_uuids: UUIDs des éléments effectivement modifiés
            (pour traçabilité et journal d'audit).
        errors: Erreurs unitaires ``{uuid, message}`` — message déjà
            scrubé des secrets.
        rollback_available: True si ``apply_*`` a stocké de quoi
            rollback (rare — la plupart des actions sont append-only).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    plan_id: str
    kind: WritePlanKind
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    executed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    impacted_uuids: list[str] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    rollback_available: bool = False
