"""Tools MCP du pattern *prepare → validate → apply*.

Tools enregistrés ici :

Préparation (lecture seule, scelle un :class:`WritePlan`) :
- ``prepare_bcf_topics``
- ``prepare_smart_views_plan``
- ``prepare_classification_update_plan``

Exécution (écriture BIMData, exige ``confirm=True``) :
- ``apply_bcf_topics``
- ``apply_smart_views_plan``
- ``apply_classification_update_plan``

Workflow :
- ``list_write_plans`` — liste les plans sous ``AUDIT_OUTPUT_DIR/plans/``.
- ``update_suggestion_status`` — bascule proposed/accepted/rejected/applied.
- ``audit_trail`` — derniers événements du journal d'écritures.

Tous les ``apply_*`` :
1. refusent ``confirm=False`` (retour ``{refused: True, ...}``) ;
2. appellent :func:`ensure_writes_allowed` après confirm ;
3. valident l'intégrité du plan (SHA-256) ;
4. valident la cible BIMData courante ;
5. journalisent via :class:`WriteJournal`.
"""

from __future__ import annotations

from ..actions import (
    PlanIntegrityError,
    PlanTargetMismatchError,
    apply_bcf,
    apply_classification_update,
    apply_smart_views,
    load_plan,
    prepare_bcf,
    prepare_classification_update,
    prepare_smart_views,
    save_plan,
)
from ..actions import list_plans as _list_plans
from ..domain.filters import FindingFilter, SuggestionFilter, SuggestionStatus
from ..security.write_journal import get_journal
from .payloads import (
    current_target,
    ensure_suggestion_store,
    plan_summary_response,
    refused_without_confirm,
)
from .security import ensure_writes_allowed
from .server import mcp
from .session import _State


@mcp.tool()
def prepare_bcf_topics(
    finding_filter: dict | None = None,
    prefix: str = "I3F Audit — ",
    include_overview: bool = True,
) -> dict:
    """Construit et scelle un :class:`WritePlan` BCF Topics — **sans écrire**.

    Args:
        finding_filter: Dict :class:`FindingFilter` pour cibler une sous-
            partie des findings (ex: ``{"severity_min": "HIGH"}``).
        prefix: Préfixe des titres BCF.
        include_overview: Inclure le topic « Vue d'ensemble » en tête.

    Returns:
        Dict compact ``{plan_id, plan_path, kind, target, summary, risks,
        n_items, requires_confirm}``. Réutiliser ``plan_path`` dans
        ``apply_bcf_topics(plan_path=..., confirm=True)``.
    """
    _State.ensure_result()
    _State.ensure_client()
    ff = FindingFilter.model_validate(finding_filter) if finding_filter else None
    plan = prepare_bcf(
        _State.result,
        finding_filter=ff,
        target=current_target(),
        prefix=prefix,
        include_overview=include_overview,
    )
    path = save_plan(plan)
    return plan_summary_response(plan, path)


@mcp.tool()
def apply_bcf_topics(plan_path: str, confirm: bool = False) -> dict:
    """Exécute un plan BCF préalablement préparé.

    Args:
        plan_path: Chemin du plan retourné par ``prepare_bcf_topics``.
        confirm: **Obligatoire** ``True`` pour exécuter. ``False``
            renvoie un refus explicite sans toucher à BIMData.

    Returns:
        :class:`ActionResult` sérialisé (succeeded / failed / errors /
        impacted_uuids).
    """
    if not confirm:
        return refused_without_confirm("apply_bcf_topics")
    _State.ensure_client()
    ensure_writes_allowed("apply_bcf_topics")
    try:
        plan = load_plan(plan_path)
    except (FileNotFoundError, PlanIntegrityError) as exc:
        return {"refused": True, "action": "apply_bcf_topics", "reason": str(exc)}
    try:
        result = apply_bcf(plan, _State.client, actual_target=current_target())
    except PlanTargetMismatchError as exc:
        return {"refused": True, "action": "apply_bcf_topics", "reason": str(exc)}
    return result.model_dump(mode="json")


@mcp.tool()
def prepare_smart_views_plan(
    finding_filter: dict | None = None,
    prefix: str = "I3F Audit — ",
    include_overview: bool = True,
) -> dict:
    """Construit et scelle un :class:`WritePlan` Smart Views — **sans écrire**.

    Idem ``prepare_bcf_topics`` mais format ``bimdata-smartview`` (panneau
    Smart Views du viewer, pas BCF Issues).
    """
    _State.ensure_result()
    _State.ensure_client()
    ff = FindingFilter.model_validate(finding_filter) if finding_filter else None
    plan = prepare_smart_views(
        _State.result,
        finding_filter=ff,
        target=current_target(),
        prefix=prefix,
        include_overview=include_overview,
    )
    path = save_plan(plan)
    return plan_summary_response(plan, path)


@mcp.tool()
def apply_smart_views_plan(plan_path: str, confirm: bool = False) -> dict:
    """Exécute un plan Smart Views préalablement préparé."""
    if not confirm:
        return refused_without_confirm("apply_smart_views_plan")
    _State.ensure_client()
    ensure_writes_allowed("apply_smart_views_plan")
    try:
        plan = load_plan(plan_path)
    except (FileNotFoundError, PlanIntegrityError) as exc:
        return {"refused": True, "action": "apply_smart_views_plan", "reason": str(exc)}
    try:
        result = apply_smart_views(plan, _State.client, actual_target=current_target())
    except PlanTargetMismatchError as exc:
        return {"refused": True, "action": "apply_smart_views_plan", "reason": str(exc)}
    return result.model_dump(mode="json")


@mcp.tool()
def prepare_classification_update_plan(
    suggestion_filter: dict | None = None,
    default_to_accepted_only: bool = True,
) -> dict:
    """Construit et scelle un :class:`WritePlan` d'application de classifications.

    Args:
        suggestion_filter: Dict :class:`SuggestionFilter`. Si absent, on
            filtre implicitement sur ``status=ACCEPTED`` (cf.
            ``default_to_accepted_only``).
        default_to_accepted_only: Quand ``suggestion_filter=None``, prend
            uniquement les suggestions ``accepted`` (recommandé). Mettre
            ``False`` pour considérer toutes les suggestions ; risque
            d'appliquer des codes basse confiance.

    Returns:
        Dict compact (cf. ``prepare_bcf_topics``). ``risks`` signale
        notamment le nombre d'éléments dont la classification serait
        écrasée.
    """
    _State.ensure_client()
    store = ensure_suggestion_store(populate_if_empty=True)
    sf = SuggestionFilter.model_validate(suggestion_filter) if suggestion_filter else None
    scope = SuggestionStatus.ACCEPTED if default_to_accepted_only else None
    plan = prepare_classification_update(
        store,
        suggestion_filter=sf,
        target=current_target(),
        default_status_scope=scope,
    )
    path = save_plan(plan)
    return plan_summary_response(plan, path)


@mcp.tool()
def apply_classification_update_plan(plan_path: str, confirm: bool = False) -> dict:
    """Exécute un plan de classifications préalablement préparé.

    Met à jour les statuts ``proposed/accepted`` → ``applied`` dans le
    store de session pour les éléments effectivement modifiés.
    """
    if not confirm:
        return refused_without_confirm("apply_classification_update_plan")
    _State.ensure_client()
    ensure_writes_allowed("apply_classification_update_plan")
    try:
        plan = load_plan(plan_path)
    except (FileNotFoundError, PlanIntegrityError) as exc:
        return {
            "refused": True,
            "action": "apply_classification_update_plan",
            "reason": str(exc),
        }
    try:
        result = apply_classification_update(
            plan,
            _State.client,
            store=_State.suggestion_store,
            actual_target=current_target(),
        )
    except PlanTargetMismatchError as exc:
        return {
            "refused": True,
            "action": "apply_classification_update_plan",
            "reason": str(exc),
        }
    return result.model_dump(mode="json")


@mcp.tool()
def list_write_plans(limit: int = 20) -> dict:
    """Liste les plans d'écriture sous ``AUDIT_OUTPUT_DIR/plans/``.

    Args:
        limit: Nombre max de plans (les plus récents).

    Returns:
        ``{plans: [...], total: int}`` — chaque plan a ``plan_id``,
        ``kind``, ``created_at``, ``path``, ``summary``, ``n_items``.
    """
    plans = _list_plans(limit=limit)
    return {"plans": plans, "total": len(plans)}


@mcp.tool()
def update_suggestion_status(
    element_uuid: str,
    status: str,
) -> dict:
    """Bascule le statut d'une suggestion (``proposed`` / ``accepted`` /
    ``rejected`` / ``applied``).

    À utiliser avant ``prepare_classification_update_plan`` pour ne
    pousser que ce qui est validé par l'AMO.

    Args:
        element_uuid: UUID IFC.
        status: Cible (``"accepted"``, ``"rejected"``, ``"proposed"``,
            ``"applied"``).

    Returns:
        Suggestion mise à jour sérialisée, ou erreur si UUID inconnu.
    """
    store = ensure_suggestion_store(populate_if_empty=True)
    try:
        new_status = SuggestionStatus(status)
    except ValueError as exc:
        raise ValueError(
            f"status invalide {status!r}. Valeurs admises : {[s.value for s in SuggestionStatus]}."
        ) from exc
    updated = store.update_status(element_uuid, new_status)
    if updated is None:
        raise ValueError(f"UUID inconnu dans le store : {element_uuid!r}.")
    return updated.model_dump(mode="json")


@mcp.tool()
def audit_trail(limit: int = 20) -> dict:
    """Renvoie les ``limit`` dernières entrées du journal d'écritures.

    Permet la revue post-exécution de tous les ``apply_*`` qui ont
    touché BIMData. Lecture seule.
    """
    entries = get_journal().tail(n=limit)
    return {
        "entries": [e.model_dump(mode="json") for e in entries],
        "total_returned": len(entries),
    }
