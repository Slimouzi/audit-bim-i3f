"""Tools MCP — audit + consultation de findings de session (PR2 §2b)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ..audit.comparator import compare_audits_from_files
from ..audit.engine import run_audit
from ..doe import match_doe_records, parse_doe, summarize_matches
from ..enrichment import enrich_with_public_data as _enrich_with_public_data
from ..extraction.model_data import extract_snapshot
from ..reporting.context import build_report_context, merge_user_context
from ..reporting.word_report import write_word_report
from ..reporting.xlsx_annex import write_xlsx_annex
from ..requirements.catalog import build_catalog
from ..requirements.models import BIMPhase
from ..safe_paths import safe_export_path, safe_input_path
from .app import mcp
from .model_identity import model_matches_expected
from .phase import (
    _VALID_PHASES,
    _detect_snapshot_phase,
    _snapshot_address_suggestion,
    _snapshot_description,
    _validate_audit_context,
)
from .security import ensure_access_token_param_allowed
from .session import _State

# Orchestration inter-modules : full_audit ré-utilise des tools/aides voisins.
from .tools_actions import prepare_bcf_topics, prepare_smart_views_plan
from .tools_reporting import _default_output_paths
from .tools_session import set_active_model

_server_logger = logging.getLogger("audit_bim.mcp.tools_audit")


@mcp.tool()
def run_audit_tool() -> dict:
    """Joue toutes les règles d'audit et renvoie un résumé des findings."""
    _State.ensure_catalog()
    _State.ensure_snapshot()
    if _State.phase is None:
        _State.phase = BIMPhase.PRO
    _State.result = run_audit(_State.snapshot, _State.catalog, _State.phase)
    return _State.result.summary()


@dataclass
class _AuditContext:
    """Contexte résolu de ``full_audit`` (étape 1) : soit un ``refusal``
    (``needs_context``), soit la phase effective + l'état de cible."""

    effective_phase: str
    target_loaded: bool
    refusal: dict | None = None


def _fa_resolve_target_and_context(
    *,
    cloud_id,
    project_id,
    model_id,
    bimdata_url,
    phase,
    access_token,
    project_address,
    auditor_name,
    project_description,
    confirm_context,
) -> _AuditContext:
    """Étape 1 — résolution de cible + contexte projet.

    Anti-contamination multi-modèle (P1) : une cible **explicite** (URL/IDs) est
    activée et SON snapshot chargé AVANT tout calcul de suggestions (sinon, en
    session multi-modèle, phase/adresse/description viendraient du modèle
    précédent). Résout ensuite la phase effective (source de vérité unique) puis
    valide le contexte obligatoire (adresse/phase/auditeur/description). Renvoie un
    ``_AuditContext`` porteur d'un ``refusal`` si une info manque et que
    ``confirm_context`` n'est pas ``True``.
    """
    explicit_target = any(v is not None for v in (cloud_id, project_id, model_id, bimdata_url))
    target_loaded = False
    if explicit_target:
        set_active_model(
            cloud_id=cloud_id,
            project_id=project_id,
            model_id=model_id,
            bimdata_url=bimdata_url,
            phase=(phase.strip() if isinstance(phase, str) and phase.strip() else "PRO"),
            access_token=access_token,
        )
        _State.snapshot = extract_snapshot(_State.client)
        target_loaded = True

    explicit_phase = phase.strip() if isinstance(phase, str) and phase.strip() else None
    detected_raw, detected_mapped = _detect_snapshot_phase()
    if explicit_phase:
        effective_phase = explicit_phase
    elif target_loaded:
        effective_phase = detected_mapped  # phase du modèle actif (nouvelle cible)
    elif _State.phase is not None:
        effective_phase = _State.phase.value
    else:
        effective_phase = detected_mapped  # peut être None (démarrage à froid)
    require_phase_confirmation = explicit_phase is None
    suggested_phase = (
        effective_phase
        if effective_phase and effective_phase.upper() in _VALID_PHASES
        else detected_mapped
    )

    context_refusal = _validate_audit_context(
        project_address=project_address,
        project_phase=effective_phase,
        auditor_name=auditor_name,
        project_description=project_description,
        require_description=_State.snapshot is not None,
        suggested_address=_snapshot_address_suggestion(),
        suggested_description=_snapshot_description(),
        suggested_phase=suggested_phase,
        detected_phase_raw=detected_raw,
        require_phase_confirmation=require_phase_confirmation,
        confirm_context=confirm_context,
    )
    if context_refusal is not None:
        return _AuditContext(
            effective_phase="", target_loaded=target_loaded, refusal=context_refusal
        )
    # Filet de sécurité pour l'énumération (confirm_context peut passer à froid).
    return _AuditContext(effective_phase=effective_phase or "PRO", target_loaded=target_loaded)


def _fa_resolve_push_mode(push_mode: str) -> str | dict:
    """Résout ``push_mode`` : renvoie le mode validé (``bcf``/``smartview``/``both``/
    ``none``), ou le dict-question ``needs_user_choice`` si ``ask``. ``ValueError``
    si invalide."""
    mode = (push_mode or "ask").lower()
    if mode == "ask":
        return {
            "status": "needs_user_choice",
            "question": (
                "Quels plans de publication préparer ? (aucune écriture — "
                "full_audit prépare des WritePlan scellés ; la publication se "
                "fait ensuite via apply_* après revue.)"
            ),
            "options": {
                "bcf": "Préparer un plan BCF Topics (panneau BCF Issues) — "
                "appliquer ensuite avec apply_bcf_topics(confirm=True).",
                "smartview": "Préparer un plan Smart Views (panneau Smart Views) — "
                "appliquer ensuite avec apply_smart_views_plan(confirm=True).",
                "both": "Préparer les deux plans (BCF + Smart Views).",
                "none": "Ne préparer aucun plan de publication.",
            },
            "next_step": ("Re-appeler full_audit avec push_mode=<bcf|smartview|both|none>."),
        }
    if mode not in ("bcf", "smartview", "both", "none"):
        raise ValueError(
            f"push_mode invalide : {push_mode!r}. Attendu : "
            "'ask' | 'bcf' | 'smartview' | 'both' | 'none'."
        )
    return mode


def _fa_prepare_catalog() -> None:
    """Étape 2 — (re)charge le catalogue d'exigences depuis les 3 documents MOA."""
    _State.catalog = build_catalog(
        cch_pdf=_State.cch_pdf,
        data_spec_xlsx=_State.data_spec_xlsx,
        naming_spec_xlsx=_State.naming_spec_xlsx,
    )


def _fa_finalize_target(
    ctx: _AuditContext, *, cloud_id, project_id, model_id, bimdata_url, access_token
) -> None:
    """Étape 3a — politique de préservation de cible + alignement de ``_State.phase``
    sur la phase effective (audit et rapport partagent la même source de vérité).

    Sans ce garde, ``full_audit()`` (model_id=None) écraserait silencieusement une
    cible posée par ``set_active_model`` + ``verify_active_model`` avec le ``.env``.
    """
    effective_bim_phase = BIMPhase(ctx.effective_phase.upper())
    if ctx.target_loaded:
        _State.phase = effective_bim_phase
    elif _State.client is None:
        set_active_model(
            cloud_id=cloud_id,
            project_id=project_id,
            model_id=model_id,
            bimdata_url=bimdata_url,
            phase=ctx.effective_phase,
            access_token=access_token,
        )
    else:
        _State.phase = effective_bim_phase


def _fa_extract_snapshot(target_loaded: bool, force_refresh_snapshot: bool) -> None:
    """Étape 3b — extraction du snapshot (refresh forcé par défaut pour ne pas
    auditer un cache périmé ; sauté si la cible explicite a déjà été chargée
    fraîchement en étape 1)."""
    if not target_loaded and (force_refresh_snapshot or _State.snapshot is None):
        _State.snapshot = extract_snapshot(_State.client)


def _fa_assert_expected_model(expected_model_name: str | None) -> None:
    """Étape 3c — garde-fou d'identité : bloque (``ValueError``) AVANT tout livrable
    si le modèle actif ne correspond pas au nom attendu."""
    if not expected_model_name:
        return
    actual_name = (_State.snapshot.model or {}).get("name")
    if not model_matches_expected(actual_name, expected_model_name):
        actual_id = (_State.snapshot.model or {}).get("id") or _State.model_id
        raise ValueError(
            f"Modèle actif inattendu : attendu '{expected_model_name}', "
            f"reçu '{actual_name}' (model_id={actual_id}). Audit interrompu."
        )


def _fa_write_deliverables(
    *, output_dir, effective_phase, project_address, auditor_name, project_description
):
    """Étape 5 — livrables (xlsx + Word avec contexte enrichi), tous resandboxés
    sous ``AUDIT_OUTPUT_DIR``. Renvoie ``(word_written, xlsx_written, word_path)``."""
    raw_word, raw_xlsx = _default_output_paths()
    if output_dir:
        raw_word = Path(output_dir) / raw_word
        raw_xlsx = Path(output_dir) / raw_xlsx
    word_path = safe_export_path(raw_word)
    xlsx_path = safe_export_path(raw_xlsx)
    xlsx_written = write_xlsx_annex(_State.result, xlsx_path)

    base_ctx = build_report_context(_State.result)
    full_ctx = merge_user_context(
        base_ctx,
        project_address=project_address,
        project_phase=effective_phase,
        auditor_name=auditor_name,
        project_description=project_description,
    )
    word_written = write_word_report(
        _State.result,
        word_path,
        auditor=auditor_name or "AMO BIM (audit automatisé)",
        xlsx_annex_path=xlsx_written,
        context=full_ctx,
    )
    return word_written, xlsx_written, word_path


def _fa_prepare_publication(mode: str) -> dict:
    """Étape 6 — préparation des plans de publication (WritePlan scellés), aucune
    écriture directe (workflow prepare → review → apply)."""
    publication: dict = {"push_mode": mode}
    if mode in ("bcf", "both"):
        publication["bcf_plan"] = prepare_bcf_topics()
    if mode in ("smartview", "both"):
        publication["smart_views_plan"] = prepare_smart_views_plan()
    return publication


def _fa_write_findings_json(word_path: Path) -> Path:
    """Étape 7a — export JSON machine des findings (lecture seule, resandboxé)."""
    findings_json = safe_export_path(word_path.with_name(word_path.stem + "_findings.json"))
    findings_json.write_text(
        json.dumps(
            [f.model_dump(mode="json") for f in _State.result.findings],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return findings_json


def _fa_build_payload(mode, word_written, xlsx_written, findings_json, publication) -> dict:
    """Étape 7b — **payload de réponse** (forme gelée : clients + tests)."""
    out: dict = {
        "summary": _State.result.summary(),
        "deliverables": {
            "word": str(word_written),
            "xlsx": str(xlsx_written),
            "findings_json": str(findings_json),
        },
        "publication": publication,
    }
    if mode in ("bcf", "smartview", "both"):
        out["next_step"] = (
            "Aucune écriture BIMData effectuée. Revoir le(s) plan(s) préparé(s) "
            "(champ « publication »), puis publier via apply_bcf_topics / "
            "apply_smart_views_plan avec confirm=True."
        )
    return out


@mcp.tool()
def full_audit(
    cloud_id: str | None = None,
    project_id: str | None = None,
    model_id: str | None = None,
    bimdata_url: str | None = None,
    phase: str | None = None,
    output_dir: str | None = None,
    push_mode: str = "ask",
    access_token: str | None = None,
    project_address: str | None = None,
    auditor_name: str | None = None,
    project_description: str | None = None,
    confirm_context: bool = False,
    expected_model_name: str | None = None,
    force_refresh_snapshot: bool = True,
) -> dict:
    """Orchestrateur : parse documents → extract modèle → audit → reports.

    Publication : depuis la v0.5.0, ``full_audit`` **n'écrit jamais** dans
    BIMData. ``push_mode`` sélectionne les **plans à préparer** (``WritePlan``
    scellés, renvoyés sous ``publication``) ; la publication se fait ensuite
    **exclusivement** via ``apply_bcf_topics`` / ``apply_smart_views_plan`` avec
    ``confirm=True`` après revue (workflow prepare → review → apply) :

    - ``"bcf"`` : prépare un plan **BCF Topics** (panneau *BCF Issues*).
    - ``"smartview"`` : prépare un plan **Smart Views** (panneau dédié).
    - ``"both"`` : prépare les deux plans.
    - ``"none"`` : ne prépare aucun plan de publication.
    - ``"ask"`` (défaut) : renvoie une question à l'utilisateur pour qu'il
      choisisse — Claude doit demander avant de ré-appeler ``full_audit`` avec
      une valeur explicite.

    .. warning::
       ``access_token`` est déconseillé en transport réseau — cf. note
       sur :func:`set_active_model`. Préférer la config serveur ou
       l'injection par reverse-proxy.

    Args:
        cloud_id, project_id, model_id: cible BIMData (fallback ``.env``).
            ``model_id`` accepte aussi une URL viewer complète.
        bimdata_url: URL viewer BIMData. Permet de lancer l'audit sur
            n'importe quel modèle sans modifier la configuration locale.
        phase: phase BIM auditée.
        output_dir: dossier de sortie (fallback ``AUDIT_OUTPUT_DIR`` env).
        push_mode: ``"ask"`` | ``"bcf"`` | ``"smartview"`` | ``"both"`` | ``"none"``.
        access_token: bearer optionnel.
        project_address: **obligatoire** — adresse du projet (affichée
            dans le rapport Word comme donnée fournie par l'utilisateur).
            Si manquant et ``confirm_context=False``, le tool retourne
            ``{status: needs_context, ...}`` sans lancer l'audit.
        auditor_name: **obligatoire** — nom de l'auditeur (page de garde
            + section *Contexte de la mission*). Idem validation.
        project_description: description du projet affichée dans la
            section *Description du projet* du rapport Word. Si absente,
            le tool propose la description extraite de la maquette
            (``project.description``) et demande validation ; passer
            ``confirm_context=True`` pour accepter la valeur suggérée.
        confirm_context: ``True`` pour passer outre la validation et
            lancer malgré les champs manquants (déconseillé — le
            rapport affichera ``Information non disponible``).
        expected_model_name: si fourni, vérifie après extraction du
            snapshot que ``model.name`` contient ce fragment (insensible
            à casse / accents / espaces multiples). L'audit est
            interrompu (``ValueError``) avant toute génération de
            livrable en cas de mismatch.
        force_refresh_snapshot: si ``True`` (défaut), force une
            extraction sans cache pour s'assurer que la maquette
            auditée est bien la version active côté BIMData. Mettre à
            ``False`` pour réutiliser ``_State.snapshot`` ou le cache
            (déconseillé quand ``expected_model_name`` est fourni).
            **Exception (sécurité)** : fournir une **nouvelle cible
            explicite** (``bimdata_url`` ou IDs) force **toujours** une
            extraction fraîche de *ce* modèle, quel que soit ce paramètre —
            on ne peut pas réutiliser le snapshot d'un autre modèle. Le
            drapeau ne s'applique donc qu'aux cibles préservées / au
            fallback ``.env``.
    """
    if access_token:
        ensure_access_token_param_allowed()

    # Étape 1 — cible + contexte (peut refuser : needs_context).
    ctx = _fa_resolve_target_and_context(
        cloud_id=cloud_id,
        project_id=project_id,
        model_id=model_id,
        bimdata_url=bimdata_url,
        phase=phase,
        access_token=access_token,
        project_address=project_address,
        auditor_name=auditor_name,
        project_description=project_description,
        confirm_context=confirm_context,
    )
    if ctx.refusal is not None:
        return ctx.refusal
    mode = _fa_resolve_push_mode(push_mode)
    if isinstance(mode, dict):  # needs_user_choice (ask)
        return mode

    _fa_prepare_catalog()  # étape 2
    _fa_finalize_target(  # étape 3a — cible préservée/activée + phase alignée
        ctx,
        cloud_id=cloud_id,
        project_id=project_id,
        model_id=model_id,
        bimdata_url=bimdata_url,
        access_token=access_token,
    )
    _fa_extract_snapshot(ctx.target_loaded, force_refresh_snapshot)  # étape 3b
    _fa_assert_expected_model(expected_model_name)  # étape 3c — contrôle d'identité

    _State.result = run_audit(_State.snapshot, _State.catalog, _State.phase)  # étape 4

    word_written, xlsx_written, word_path = _fa_write_deliverables(  # étape 5
        output_dir=output_dir,
        effective_phase=ctx.effective_phase,
        project_address=project_address,
        auditor_name=auditor_name,
        project_description=project_description,
    )
    publication = _fa_prepare_publication(mode)  # étape 6
    findings_json = _fa_write_findings_json(word_path)  # étape 7a
    return _fa_build_payload(
        mode, word_written, xlsx_written, findings_json, publication
    )  # étape 7b


@mcp.tool()
def query_findings(
    theme: str | None = None,
    severity: str | None = None,
    error_type: str | None = None,
    ifc_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Filtre les findings de l'audit courant."""
    _State.ensure_result()
    items = _State.result.filter(
        theme=theme, severity=severity, error_type=error_type, ifc_type=ifc_type
    )
    return [f.model_dump(mode="json") for f in items[:limit]]


@mcp.tool()
def import_preliminary_findings(
    inventory_json: str | None = None,
    space_clash_json: str | None = None,
    surface_loss_json: str | None = None,
    boundaries_json: str | None = None,
    openings_json: str | None = None,
) -> dict:
    """Importe les findings de l'audit préliminaire géométrique produits par
    le serveur MCP ``ifc-geometry`` et les fusionne dans l'audit courant.

    Les findings importés alimentent ensuite automatiquement le rapport Word,
    l'annexe XLSX, les topics BCF et les Smart Views (thème « Cohérence
    géométrique » + thèmes Quantités / Hiérarchie / Nommage Pièce).

    Args:
        inventory_json: Fichier ``*_space_inventory.json``
            (outil ``extract_space_inventory``) — pièces trop petites,
            écarts de surface, pièces sans zone, typologies de zones,
            nommage, fraîcheur du modèle.
        space_clash_json: Fichier ``*_space_clash_findings.json``
            (outil ``run_space_clash_audit``) — doublons de pièces,
            chevauchements, placards double-modélisés.
        surface_loss_json: Fichier ``*_surface_loss.json``
            (outil ``compute_surface_loss``) — m² perdus par pièce.
        boundaries_json: Fichier ``*_boundaries.json``
            (outil ``check_space_boundaries``) — limites manquantes entre
            pièces adjacentes.
        openings_json: Fichier ``*_openings_check.json``
            (outil ``check_opening_correspondence``) — ouvertures structure
            sans correspondance archi.

    Returns:
        Nombre de findings importés par source + nouveau résumé de l'audit.
    """
    from ..audit.findings import Severity
    from ..audit.rules import load_preliminary_findings

    _State.ensure_result()
    if not any(
        (inventory_json, space_clash_json, surface_loss_json, boundaries_json, openings_json)
    ):
        raise ValueError("Fournir au moins un fichier JSON à importer.")

    def _load(path: str | None) -> dict | None:
        if not path:
            return None
        safe = safe_input_path(path, allowed_extensions={".json"})
        return json.loads(Path(safe).read_text(encoding="utf-8"))

    sources = {
        "inventory": _load(inventory_json),
        "space_clash": _load(space_clash_json),
        "surface_loss": _load(surface_loss_json),
        "boundaries": _load(boundaries_json),
        "openings": _load(openings_json),
    }
    by_source = {
        k: len(load_preliminary_findings(**{k: v})) if v else 0 for k, v in sources.items()
    }
    # Nom des fichiers JSON par source → tracé dans ref_cch (provenance opposable).
    source_files = {
        "inventory": Path(inventory_json).name if inventory_json else None,
        "space_clash": Path(space_clash_json).name if space_clash_json else None,
        "surface_loss": Path(surface_loss_json).name if surface_loss_json else None,
        "boundaries": Path(boundaries_json).name if boundaries_json else None,
        "openings": Path(openings_json).name if openings_json else None,
    }
    imported = load_preliminary_findings(**sources, source_files=source_files)

    _State.result.findings.extend(imported)
    # Même tri stable que run_audit (sévérité décroissante, thème, type)
    sev_order = {s: i for i, s in enumerate(Severity.ordered())}
    _State.result.findings.sort(
        key=lambda f: (
            sev_order.get(f.severity, 99),
            f.theme.value,
            f.error_type.value,
            f.ifc_type or "",
            f.name or "",
        )
    )

    return {
        "imported": len(imported),
        "by_source": by_source,
        "audit_summary": _State.result.summary(),
    }


@mcp.tool()
def compare_with_previous_audit(
    previous_findings_json: str,
    current_findings_json: str | None = None,
) -> dict:
    """Compare l'audit courant (ou un fichier JSON) avec une version précédente.

    Compare 2 jeux de findings ``audit_*_findings.json`` (généré par
    ``full_audit`` ou ``cli``). Renvoie le bilan d'évolution : anomalies
    résolues, nouvelles, persistantes, ventilation par sévérité/thème,
    et un *progress score* entre -1 et +1.

    Args:
        previous_findings_json: Chemin du fichier JSON de la version
            précédente (livraison MOE n-1, audit du mois passé, etc.).
        current_findings_json: Chemin du fichier JSON de la version
            actuelle. Si ``None``, on utilise l'audit en cours (doit
            avoir tourné via ``run_audit_tool`` ou ``full_audit``).

    Returns:
        Dict ``{old_source, new_source, summary, entries_sample,
        n_old_findings, n_new_findings}``.
    """
    prev_safe = safe_input_path(previous_findings_json, allowed_extensions={".json"})
    if current_findings_json is None:
        _State.ensure_result()
        # Persiste l'audit courant dans un fichier temporaire pour
        # réutiliser compare_audits_from_files.
        import json as _json
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_findings.json", delete=False, encoding="utf-8"
        ) as tmp:
            _json.dump(
                [f.model_dump(mode="json") for f in _State.result.findings],
                tmp,
                ensure_ascii=False,
            )
            current_findings_json = tmp.name
        current_safe = current_findings_json
    else:
        current_safe = str(safe_input_path(current_findings_json, allowed_extensions={".json"}))
    return compare_audits_from_files(str(prev_safe), current_safe)


@mcp.tool()
def enrich_with_public_data(
    address_override: str | None = None,
    address_override_source: str = "override",
    doe_path: str | None = None,
    include_dpe: bool = True,
    include_plu: bool = True,
    include_georisques: bool = True,
    radius_dpe_m: int = 50,
    radius_georisques_m: int = 1000,
) -> dict:
    """Enrichit la maquette avec les open data publiques françaises.

    Pipeline de résolution de l'adresse projet :

    1. ``address_override`` (texte libre prioritaire).
    2. ``IfcBuilding.BuildingAddress`` du snapshot.
    3. ``IfcSite.SiteAddress`` du snapshot.
    4. **Auto-extraction DOE** si ``doe_path`` est fourni : scan des
       en-têtes xlsx, page de garde PDF, ou OCR (regex CP + voie).
    5. Erreur sinon.

    L'adresse est ensuite validée par la **BAN** (data.gouv.fr) :
    géocodage exact, code INSEE, score de confiance. Sans match BAN,
    les autres sources sont court-circuitées.

    Sources interrogées en parallèle après validation BAN :

    - **DPE ADEME** : diagnostics énergétiques connus dans
      ``radius_dpe_m`` mètres (dataset ``dpe-v2-logements-existants``,
      post juillet 2021).
    - **PLU/GPU IGN** : zonage urbanisme applicable au point.
    - **Géorisques** : aléas naturels et ICPE à proximité.

    Toutes les APIs sont publiques (pas d'authentification requise).

    Args:
        address_override: Adresse libre prioritaire sur l'adresse IFC/DOE.
        address_override_source: ``override`` (défaut) ou ``doe`` pour
            tracer l'origine dans le rapport.
        doe_path: Chemin du fichier DOE pour fallback auto-extraction.
        include_dpe / include_plu / include_georisques: désactive
            individuellement une source.
        radius_dpe_m: Rayon de recherche DPE (mètres).
        radius_georisques_m: Rayon de recherche Géorisques (mètres).

    Returns:
        ``EnrichmentReport`` sérialisé : adresse + géocodage + DPE +
        zonage PLU + risques + ``sources_used`` + ``sources_errors``.
    """
    _State.ensure_snapshot()
    # Validation du DOE optionnel : même politique que doe_enrich_model
    # / doe_match_only — racine, extension, taille, traversal.
    safe_doe = str(safe_input_path(doe_path)) if doe_path else None
    report = _enrich_with_public_data(
        _State.snapshot,
        address_override=address_override,
        address_override_source=address_override_source,
        doe_path=safe_doe,
        include_dpe=include_dpe,
        include_plu=include_plu,
        include_georisques=include_georisques,
        radius_dpe_m=radius_dpe_m,
        radius_georisques_m=radius_georisques_m,
    )
    return report.model_dump(mode="json")


@mcp.tool()
def doe_match_only(
    doe_path: str,
    name_min_score: int = 75,
    limit: int = 50,
    ocr_fallback: bool = True,
    ocr_lang: str = "fra",
) -> dict:
    """Variante read-only de l'enrichissement DOE.

    Parse + matche mais n'enrichit *jamais* la maquette. Utile pour
    valider la qualité des matches avant d'appliquer.

    Args:
        doe_path: Chemin du fichier DOE (.xlsx / .xlsm / .pdf).
        name_min_score: Seuil fuzzy 0–100 pour le matching par nom.
        limit: Nombre max de matches échantillonnés dans la réponse
            (les stats globales couvrent l'intégralité).
        ocr_fallback: OCR sur PDF scanné (défaut ``True``).
        ocr_lang: Langue Tesseract (défaut ``"fra"``).
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
    }
