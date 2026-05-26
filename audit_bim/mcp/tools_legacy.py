"""Tools MCP dépréciés — wrappers sécurisés vers le pattern prepare/apply.

Tools conservés ici pour **compatibilité** seulement. Tous portent
``deprecated=True`` + ``use_instead`` + ``removal_version`` dans leur
retour, et logguent un INFO côté serveur à chaque appel.

Comportement par défaut (``legacy_execute=False``) — **non destructif** :

- ``create_bcf_topics`` → délègue à :func:`prepare_bcf` + :func:`save_plan`
  et retourne le plan compact. Aucune écriture BIMData.
- ``create_smart_views`` → délègue à :func:`prepare_smart_views` +
  :func:`save_plan` (idem).
- ``apply_suggested_classifications`` → bascule les suggestions matchant
  ``min_confidence`` en ``ACCEPTED`` dans le store, puis délègue à
  :func:`prepare_classification_update` + :func:`save_plan`. Aucune
  écriture BIMData.

Comportement legacy explicite (``legacy_execute=True``) :

- exécute l'ancien flux (push direct via les builders),
- appelle :func:`ensure_writes_allowed` côté écriture,
- ajoute un ``legacy_execute_warning`` fort dans le retour,
- log INFO additionnel.

Ce mode sera supprimé à partir de la version indiquée dans
``removal_version`` (cf. :data:`audit_bim.mcp.deprecation.DEPRECATIONS`).

``suggest_classifications`` est conservé en lecture seule (pas de
mode legacy_execute) — c'est juste un alias historique de
``list_classification_suggestions`` avec un format de sortie différent.
"""

from __future__ import annotations

from ..actions import (
    prepare_bcf,
    prepare_classification_update,
    prepare_doe_enrichment,
    prepare_smart_views,
    save_plan,
)
from ..bcf.builder import push_bcf_topics as _push_bcf_topics
from ..classifier import (
    apply_classifications as _apply_classifications,
)
from ..classifier import (
    items_from_suggestions as _items_from_suggestions,
)
from ..classifier import (
    suggest_for_findings as _suggest_for_findings,
)
from ..doe import (
    apply_matches_to_model as _apply_matches_to_model,
)
from ..doe import (
    match_doe_records as _match_doe_records,
)
from ..doe import (
    parse_doe as _parse_doe,
)
from ..doe import (
    summarize_matches as _summarize_matches,
)
from ..domain.filters import SuggestionStatus
from ..safe_paths import safe_input_path
from ..smartview.builder import push_smart_views as _push_smart_views
from .deprecation import (
    add_deprecation_marker,
    get_deprecation,
    log_deprecated_tool_call,
)
from .payloads import (
    current_target,
    ensure_suggestion_store,
    plan_summary_response,
)
from .security import ensure_writes_allowed
from .server import mcp
from .session import _State

# ── suggest_classifications (lecture seule) ──────────────────────────────


@mcp.tool()
def suggest_classifications(
    min_confidence: float = 0.4,
    top_n: int = 3,
    limit: int = 200,
) -> list[dict]:
    """[DÉPRÉCIÉ] Pour chaque élément avec ``classification_missing``, propose
    1-3 codes UniFormat II.

    .. deprecated::
        Utiliser :func:`list_classification_suggestions` qui expose un
        store indexé filtrable, avec statuts accepted/rejected/applied.

    Args:
        min_confidence: seuil de confiance (0..1) sous lequel on n'expose pas
            de suggestion.
        top_n: nombre maximum de suggestions par élément.
        limit: cap du nombre d'éléments retournés (pour préserver le canal MCP).
    """
    info = get_deprecation("suggest_classifications")
    log_deprecated_tool_call(info)

    _State.ensure_result()
    out = _suggest_for_findings(
        _State.result.findings,
        _State.result.snapshot,
        min_confidence=min_confidence,
        top_n=top_n,
    )
    # Contrat historique : list[dict]. On préserve ce shape tout en
    # garantissant que le marqueur de dépréciation est **toujours
    # détectable** côté client (review CTO PR #9) — même quand l'audit
    # ne produit aucune suggestion (liste vide).
    meta = {
        "deprecated": True,
        "use_instead": info.use_instead,
        "removal_version": info.removal_version,
        "migration_hint": info.migration_hint,
    }
    if not out:
        # Cas liste vide : on retourne une entrée *sentinel* unique qui
        # ne porte QUE le marqueur de dépréciation (pas d'``element_uuid``,
        # pas de ``suggestions`` — le caller doit traiter ``_meta.empty_result``
        # comme « rien à proposer »).
        return [{"_meta": {**meta, "empty_result": True}}]
    # Cas non vide : on injecte le marqueur sur la 1ère entrée.
    out[0] = dict(out[0])
    out[0].setdefault("_meta", {})
    out[0]["_meta"].update(meta)
    return out[:limit]


# ── create_bcf_topics (wrapper prepare/apply par défaut) ────────────────


@mcp.tool()
def create_bcf_topics(
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
    legacy_execute: bool = False,
) -> dict:
    """[DÉPRÉCIÉ] Crée des BCF Topics — désormais wrapper vers prepare/apply.

    .. deprecated::
        Utiliser :func:`prepare_bcf_topics` puis :func:`apply_bcf_topics`.

    Args:
        prefix: Préfixe des titres BCF.
        dry_run: Ignoré quand ``legacy_execute=False`` (le pattern prepare
            est *toujours* en dry-run du point de vue BIMData). Honoré en
            mode legacy_execute pour rétrocompatibilité.
        legacy_execute: Si ``True``, exécute l'**ancien comportement**
            (push direct via :func:`push_bcf_topics`). À ne plus utiliser
            — réservé aux scripts existants en transition. Sera supprimé
            à la version ``0.3.0``.

    Returns:
        Par défaut (``legacy_execute=False``) : payload ``prepare_*`` (plan_id,
        plan_path, summary, …) avec marqueur de dépréciation.
        En ``legacy_execute=True`` : ancien format ``{n_topics, dry_run,
        topics}`` + ``legacy_execute_warning``.
    """
    info = get_deprecation("create_bcf_topics")
    log_deprecated_tool_call(info, extra={"legacy_execute": legacy_execute})

    _State.ensure_result()
    _State.ensure_client()

    if not legacy_execute:
        # Mode sûr par défaut : on prépare un plan, l'AMO devra ensuite
        # appeler apply_bcf_topics(plan_path=..., confirm=True).
        plan = prepare_bcf(
            _State.result,
            finding_filter=None,
            target=current_target(),
            prefix=prefix,
            include_overview=True,
        )
        path = save_plan(plan)
        payload = plan_summary_response(plan, path)
        payload["next_step"] = f"apply_bcf_topics(plan_path={str(path)!r}, confirm=True)"
        return add_deprecation_marker(payload, info)

    # Mode legacy explicite : ancien push direct.
    if not dry_run:
        ensure_writes_allowed("create_bcf_topics")
    out = _push_bcf_topics(_State.result, _State.client, prefix=prefix, dry_run=dry_run)
    payload = {
        "n_topics": len(out),
        "dry_run": dry_run,
        "topics": out,
        "legacy_execute_warning": (
            "legacy_execute=True utilise l'ancien chemin (push direct) qui sera "
            f"supprimé à la version {info.removal_version}. Migrer vers "
            "prepare_bcf_topics / apply_bcf_topics."
        ),
    }
    return add_deprecation_marker(payload, info)


# ── create_smart_views (wrapper prepare/apply par défaut) ───────────────


@mcp.tool()
def create_smart_views(
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
    legacy_execute: bool = False,
) -> dict:
    """[DÉPRÉCIÉ] Crée des Smart Views — désormais wrapper vers prepare/apply.

    .. deprecated::
        Utiliser :func:`prepare_smart_views_plan` puis
        :func:`apply_smart_views_plan`.

    Args:
        prefix: Préfixe des titres.
        dry_run: Idem ``create_bcf_topics``.
        legacy_execute: Idem ``create_bcf_topics``.
    """
    info = get_deprecation("create_smart_views")
    log_deprecated_tool_call(info, extra={"legacy_execute": legacy_execute})

    _State.ensure_result()
    _State.ensure_client()

    if not legacy_execute:
        plan = prepare_smart_views(
            _State.result,
            finding_filter=None,
            target=current_target(),
            prefix=prefix,
            include_overview=True,
        )
        path = save_plan(plan)
        payload = plan_summary_response(plan, path)
        payload["next_step"] = f"apply_smart_views_plan(plan_path={str(path)!r}, confirm=True)"
        return add_deprecation_marker(payload, info)

    if not dry_run:
        ensure_writes_allowed("create_smart_views")
    out = _push_smart_views(_State.result, _State.client, prefix=prefix, dry_run=dry_run)
    payload = {
        "n_views": len(out),
        "dry_run": dry_run,
        "views": out,
        "legacy_execute_warning": (
            "legacy_execute=True utilise l'ancien chemin (push direct) qui sera "
            f"supprimé à la version {info.removal_version}. Migrer vers "
            "prepare_smart_views_plan / apply_smart_views_plan."
        ),
    }
    return add_deprecation_marker(payload, info)


# ── apply_suggested_classifications (wrapper prepare/apply par défaut) ──


@mcp.tool()
def apply_suggested_classifications(
    min_confidence: float = 0.5,
    dry_run: bool = True,
    legacy_execute: bool = False,
) -> dict:
    """[DÉPRÉCIÉ] Applique automatiquement les classifications proposées.

    .. deprecated::
        Workflow recommandé : ``list_classification_suggestions`` →
        ``update_suggestion_status(uuid, 'accepted')`` →
        ``prepare_classification_update_plan`` →
        ``apply_classification_update_plan(plan_path=..., confirm=True)``.

    Comportement par défaut (``legacy_execute=False``) :
    le tool bascule en mémoire les suggestions avec
    ``confidence >= min_confidence`` vers ``ACCEPTED`` dans le store de
    session, puis prépare un plan. **Aucune écriture BIMData.**

    Comportement legacy (``legacy_execute=True``) :
    ancien flux d'écrasement automatique (sera supprimé à la version
    ``0.3.0``).

    Args:
        min_confidence: Seuil de confiance.
        dry_run: Honoré en mode legacy_execute uniquement.
        legacy_execute: Si ``True``, exécute l'ancien comportement
            destructif. À éviter.
    """
    info = get_deprecation("apply_suggested_classifications")
    log_deprecated_tool_call(info, extra={"legacy_execute": legacy_execute})

    _State.ensure_result()
    _State.ensure_client()

    if not legacy_execute:
        # 1. Peuple le store depuis l'audit (préserve les statuts non-proposed).
        store = ensure_suggestion_store(populate_if_empty=True)
        # 2. Bascule en ACCEPTED toutes les entrées au-dessus du seuil
        # qui sont encore en PROPOSED (les autres restent intactes).
        n_accepted = 0
        for entry in list(store):
            if entry.status == SuggestionStatus.PROPOSED and entry.confidence >= min_confidence:
                store.update_status(entry.element_uuid, SuggestionStatus.ACCEPTED)
                n_accepted += 1
        # 3. Prépare un plan sur ces ACCEPTED.
        plan = prepare_classification_update(
            store,
            suggestion_filter=None,
            target=current_target(),
            default_status_scope=SuggestionStatus.ACCEPTED,
        )
        path = save_plan(plan)
        payload = plan_summary_response(plan, path)
        payload["n_auto_accepted"] = n_accepted
        payload["min_confidence_applied"] = min_confidence
        payload["next_step"] = (
            f"apply_classification_update_plan(plan_path={str(path)!r}, confirm=True)"
        )
        return add_deprecation_marker(payload, info)

    # Mode legacy explicite : ancien push direct sans revue par UUID.
    if not dry_run:
        ensure_writes_allowed("apply_suggested_classifications")
    suggestions = _suggest_for_findings(
        _State.result.findings,
        _State.result.snapshot,
        min_confidence=min_confidence,
        top_n=1,
    )
    items = _items_from_suggestions(suggestions, min_confidence=min_confidence)
    api_payload = _apply_classifications(_State.client, items, dry_run=dry_run)
    api_payload["legacy_execute_warning"] = (
        "legacy_execute=True utilise l'ancien chemin (push direct, sans revue par UUID) "
        f"qui sera supprimé à la version {info.removal_version}. Migrer vers le workflow "
        "list_classification_suggestions → update_suggestion_status → "
        "prepare_classification_update_plan → apply_classification_update_plan."
    )
    return add_deprecation_marker(api_payload, info)


# ── doe_enrich_model (wrapper prepare/apply par défaut) ─────────────────


@mcp.tool()
def doe_enrich_model(
    doe_path: str,
    dry_run: bool = True,
    name_min_score: int = 75,
    on_conflict: str = "report",
    ocr_fallback: bool = True,
    ocr_lang: str = "fra",
    legacy_execute: bool = False,
) -> dict:
    """[DÉPRÉCIÉ] Agent DOE → IFC — désormais wrapper vers prepare/apply.

    .. deprecated::
        Workflow recommandé : ``match_doe_to_ifc`` puis
        ``prepare_doe_enrichment_plan`` puis
        ``apply_doe_enrichment_plan(plan_path=..., confirm=True)``.

    Comportement par défaut (``legacy_execute=False``) :
    parse le DOE, match les éléments, **prépare un WritePlan scellé**.
    Aucune écriture BIMData. Retour avec ``plan_path`` et marqueur
    ``deprecated=True``.

    Comportement legacy (``legacy_execute=True``) :
    ancien flux (parse + match + push direct) avec
    ``legacy_execute_warning`` fort, log INFO additionnel, et passage
    par ``ensure_writes_allowed`` côté écriture. À éviter — sera
    supprimé à la version ``0.3.0``.

    Args:
        doe_path: Chemin du fichier DOE (.xlsx / .xlsm / .pdf).
        dry_run: Ignoré en mode legacy_execute=False. Honoré en mode
            legacy_execute=True pour rétrocompatibilité.
        name_min_score: Seuil fuzzy 0-100 (défaut 75).
        on_conflict: ``"report"`` (défaut, n'écrase pas) / ``"skip"`` /
            ``"overwrite"``.
        ocr_fallback / ocr_lang: Cf. ``extract_doe_records``.
        legacy_execute: Si ``True``, exécute l'ancien comportement.
    """
    info = get_deprecation("doe_enrich_model")
    log_deprecated_tool_call(info, extra={"legacy_execute": legacy_execute})

    _State.ensure_client()
    _State.ensure_snapshot()
    safe_doe = safe_input_path(doe_path)
    records = _parse_doe(str(safe_doe), ocr_fallback=ocr_fallback, ocr_lang=ocr_lang)
    matches = _match_doe_records(records, _State.snapshot, name_min_score=name_min_score)

    if not legacy_execute:
        # Mode sûr par défaut : prépare un plan, aucune écriture BIMData.
        plan = prepare_doe_enrichment(
            matches,
            snapshot=_State.snapshot,
            target=current_target(),
            on_conflict=on_conflict,
            source_label=str(safe_doe),
        )
        path = save_plan(plan)
        payload = plan_summary_response(plan, path)
        payload["source"] = str(safe_doe)
        payload["next_step"] = f"apply_doe_enrichment_plan(plan_path={str(path)!r}, confirm=True)"
        return add_deprecation_marker(payload, info)

    # Mode legacy explicite : ancien push direct.
    if not dry_run:
        ensure_writes_allowed("doe_enrich_model")
    summary = _summarize_matches(matches)
    application = _apply_matches_to_model(
        _State.client,
        matches,
        dry_run=dry_run,
        snapshot=_State.snapshot,
        on_conflict=on_conflict,
    )
    payload = {
        "source": str(safe_doe),
        "summary": summary,
        "application": application,
        "legacy_execute_warning": (
            "legacy_execute=True utilise l'ancien chemin (push direct) qui sera "
            f"supprimé à la version {info.removal_version}. Migrer vers "
            "match_doe_to_ifc → prepare_doe_enrichment_plan → "
            "apply_doe_enrichment_plan."
        ),
    }
    return add_deprecation_marker(payload, info)
