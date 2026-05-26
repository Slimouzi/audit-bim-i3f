"""Aliases orientés métier pour le pattern prepare/apply.

Ces tools sont des **alias** stricts des tools du module
``tools_actions`` — même signature, même comportement. Ils donnent juste
un vocabulaire plus parlant à l'utilisateur final AMO :

================================================  ===================================
Alias métier                                      Tool sous-jacent
================================================  ===================================
``prepare_bcf_from_findings``                     :func:`prepare_bcf_topics`
``apply_bcf_plan``                                :func:`apply_bcf_topics`
``prepare_smartviews_from_findings``              :func:`prepare_smart_views_plan`
``apply_smartviews_plan``                         :func:`apply_smart_views_plan`
``prepare_classification_corrections``            :func:`prepare_classification_update_plan`
``apply_classification_corrections``              :func:`apply_classification_update_plan`
================================================  ===================================

Workflow type côté AMO BIM :

1. ``list_audit_findings`` / ``list_classification_suggestions`` →
   filtrer le périmètre.
2. ``prepare_*`` ou alias ``prepare_*_from_findings`` /
   ``prepare_*_corrections`` → calculer le plan, scellé sur disque.
3. Revue manuelle du plan (chemin renvoyé dans ``plan_path``).
4. ``apply_*`` ou alias ``apply_*_plan`` /
   ``apply_*_corrections`` avec ``confirm=True``.

Les aliases délèguent à 100 % aux tools cibles — ne pas dupliquer la
logique, juste re-dispatcher.
"""

from __future__ import annotations

from .server import mcp
from .tools_actions import (
    apply_bcf_topics,
    apply_classification_update_plan,
    apply_smart_views_plan,
    prepare_bcf_topics,
    prepare_classification_update_plan,
    prepare_smart_views_plan,
)


@mcp.tool()
def prepare_bcf_from_findings(
    finding_filter: dict | None = None,
    prefix: str = "I3F Audit — ",
    include_overview: bool = True,
) -> dict:
    """Alias métier de :func:`prepare_bcf_topics` — prépare un plan de
    création de BCF Topics à partir des findings filtrés.

    Workflow lisible pour l'AMO BIM : ``filter findings → prepare BCF
    from findings → review plan → apply BCF plan``.
    """
    return prepare_bcf_topics(
        finding_filter=finding_filter,
        prefix=prefix,
        include_overview=include_overview,
    )


@mcp.tool()
def apply_bcf_plan(plan_path: str, confirm: bool = False) -> dict:
    """Alias métier de :func:`apply_bcf_topics` — exécute le plan BCF
    préparé.
    """
    return apply_bcf_topics(plan_path=plan_path, confirm=confirm)


@mcp.tool()
def prepare_smartviews_from_findings(
    finding_filter: dict | None = None,
    prefix: str = "I3F Audit — ",
    include_overview: bool = True,
) -> dict:
    """Alias métier de :func:`prepare_smart_views_plan` — prépare un
    plan de création de Smart Views à partir des findings filtrés.
    """
    return prepare_smart_views_plan(
        finding_filter=finding_filter,
        prefix=prefix,
        include_overview=include_overview,
    )


@mcp.tool()
def apply_smartviews_plan(plan_path: str, confirm: bool = False) -> dict:
    """Alias métier de :func:`apply_smart_views_plan` — exécute le plan
    Smart Views préparé.
    """
    return apply_smart_views_plan(plan_path=plan_path, confirm=confirm)


@mcp.tool()
def prepare_classification_corrections(
    suggestion_filter: dict | None = None,
    default_to_accepted_only: bool = True,
) -> dict:
    """Alias métier de :func:`prepare_classification_update_plan` —
    prépare un plan de correction des classifications IFC à partir des
    suggestions acceptées.
    """
    return prepare_classification_update_plan(
        suggestion_filter=suggestion_filter,
        default_to_accepted_only=default_to_accepted_only,
    )


@mcp.tool()
def apply_classification_corrections(plan_path: str, confirm: bool = False) -> dict:
    """Alias métier de :func:`apply_classification_update_plan` —
    exécute le plan de correction des classifications.
    """
    return apply_classification_update_plan(plan_path=plan_path, confirm=confirm)
