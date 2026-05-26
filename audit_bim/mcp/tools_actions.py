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
    apply_doe_enrichment,
    apply_smart_views,
    load_plan,
    prepare_bcf,
    prepare_classification_update,
    prepare_doe_enrichment,
    prepare_smart_views,
    save_plan,
)
from ..actions import list_plans as _list_plans
from ..doe import match_doe_records, parse_doe, summarize_matches
from ..domain.filters import FindingFilter, SuggestionFilter, SuggestionStatus
from ..safe_paths import safe_input_path
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


# ── DOE → IFC enrichment (prepare/apply) ──────────────────────────────────


@mcp.tool()
def extract_doe_records(
    doe_path: str,
    ocr_fallback: bool = True,
    ocr_lang: str = "fra",
    limit: int = 50,
) -> dict:
    """Parse un fichier DOE (Excel/PDF) et retourne les ``DoeRecord`` extraits.

    Étape pure de **lecture** : pas de matching IFC, pas d'écriture.

    Args:
        doe_path: Chemin du fichier DOE (.xlsx / .xlsm / .pdf), sandbox
            ``AUDIT_INPUT_DIR`` si défini.
        ocr_fallback: Active OCR Tesseract sur PDF scanné (défaut ``True``).
        ocr_lang: Langue Tesseract.
        limit: Nombre max d'enregistrements retournés (défaut 50). Le
            ``total`` reste exact même si la liste est tronquée.

    Returns:
        ``{source, total, n_returned, records: [...], _meta: {limit}}``.
        Chaque record contient ``row_index, uuid_hint, tag_hint,
        name_hint, type_hint, storey_hint, zone_hint, properties``.
    """
    safe_doe = safe_input_path(doe_path)
    records = parse_doe(str(safe_doe), ocr_fallback=ocr_fallback, ocr_lang=ocr_lang)
    return {
        "source": str(safe_doe),
        "total": len(records),
        "n_returned": min(limit, len(records)),
        "records": [r.model_dump(mode="json") for r in records[:limit]],
        "_meta": {"limit": limit},
    }


@mcp.tool()
def match_doe_to_ifc(
    doe_path: str,
    name_min_score: int = 75,
    ocr_fallback: bool = True,
    ocr_lang: str = "fra",
    limit: int = 50,
) -> dict:
    """Parse + rapproche un DOE aux éléments IFC du snapshot actif.

    Pas d'écriture BIMData — utiliser ensuite
    :func:`prepare_doe_enrichment_plan` puis
    :func:`apply_doe_enrichment_plan`.

    Args:
        doe_path: Chemin du fichier DOE.
        name_min_score: Seuil fuzzy 0-100 (défaut 75).
        ocr_fallback / ocr_lang: Idem ``extract_doe_records``.
        limit: Échantillon de matches retourné (le résumé reste exhaustif).

    Returns:
        ``{source, summary, sample_matches, _meta: {limit}}``.
    """
    _State.ensure_snapshot()
    safe_doe = safe_input_path(doe_path)
    records = parse_doe(str(safe_doe), ocr_fallback=ocr_fallback, ocr_lang=ocr_lang)
    matches = match_doe_records(records, _State.snapshot, name_min_score=name_min_score)
    summary = summarize_matches(matches)
    sample = [m.model_dump(mode="json") for m in matches[:limit]]
    return {
        "source": str(safe_doe),
        "n_records": len(records),
        "summary": summary,
        "sample_matches": sample,
        "_meta": {"limit": limit},
    }


@mcp.tool()
def prepare_doe_enrichment_plan(
    doe_path: str,
    on_conflict: str = "report",
    name_min_score: int = 75,
    ocr_fallback: bool = True,
    ocr_lang: str = "fra",
) -> dict:
    """Construit et scelle un :class:`WritePlan` d'enrichissement DOE — **sans écrire**.

    Étapes internes :

    1. Parse le DOE (Excel / PDF, OCR si scanné).
    2. Match les records aux éléments IFC du snapshot actif.
    3. Pré-calcule les conflits maquette ↔ DOE (``MATCH`` / ``NEW`` /
       ``UPGRADE`` / ``CONFLICT``).
    4. Filtre les propriétés selon ``on_conflict`` (cf.
       :func:`audit_bim.doe.enricher.apply_matches_to_model`).
    5. Scelle le plan SHA-256 sous ``AUDIT_OUTPUT_DIR/plans/``.

    Args:
        doe_path: Chemin du fichier DOE source.
        on_conflict: ``"report"`` (défaut, n'écrase pas) / ``"skip"`` /
            ``"overwrite"`` (DOE autoritaire).
        name_min_score: Seuil fuzzy 0-100 (défaut 75).
        ocr_fallback / ocr_lang: Cf. ``extract_doe_records``.

    Returns:
        Dict compact ``{plan_id, plan_path, kind="doe_enrichment",
        target, summary, risks, n_items, requires_confirm}``.
        ``summary.conflicts_summary`` détaille MATCH/NEW/UPGRADE/CONFLICT.
    """
    _State.ensure_snapshot()
    _State.ensure_client()
    safe_doe = safe_input_path(doe_path)
    records = parse_doe(str(safe_doe), ocr_fallback=ocr_fallback, ocr_lang=ocr_lang)
    matches = match_doe_records(records, _State.snapshot, name_min_score=name_min_score)

    plan = prepare_doe_enrichment(
        matches,
        snapshot=_State.snapshot,
        target=current_target(),
        on_conflict=on_conflict,
        source_label=str(safe_doe),
    )
    path = save_plan(plan)
    return plan_summary_response(plan, path)


@mcp.tool()
def apply_doe_enrichment_plan(plan_path: str, confirm: bool = False) -> dict:
    """Exécute un plan d'enrichissement DOE préalablement préparé.

    Pour chaque item du plan, POST le Pset sur l'élément IFC matché.
    Journalise via ``WriteJournal``, scrub les erreurs API.

    Args:
        plan_path: Chemin du plan retourné par
            ``prepare_doe_enrichment_plan``.
        confirm: ``True`` obligatoire pour exécuter. ``False`` retourne
            un refus explicite sans toucher BIMData.

    Returns:
        :class:`ActionResult` sérialisé.
    """
    if not confirm:
        return refused_without_confirm("apply_doe_enrichment_plan")
    _State.ensure_client()
    ensure_writes_allowed("apply_doe_enrichment_plan")
    try:
        plan = load_plan(plan_path)
    except (FileNotFoundError, PlanIntegrityError) as exc:
        return {
            "refused": True,
            "action": "apply_doe_enrichment_plan",
            "reason": str(exc),
        }
    try:
        result = apply_doe_enrichment(plan, _State.client, actual_target=current_target())
    except PlanTargetMismatchError as exc:
        return {
            "refused": True,
            "action": "apply_doe_enrichment_plan",
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
