"""Serveur MCP « Audit BIM I3F » — orchestrateur AMO BIM piloté par Claude.

Le serveur conserve un *état de session* léger en mémoire :
- catalogue d'exigences (chargé depuis les 3 documents MOA),
- client BIMData (auth),
- snapshot du modèle,
- résultat d'audit courant.

Chaque outil MCP travaille sur cet état et renvoie des structures
sérialisables (dict / list) compatibles avec FastMCP.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

from .. import config
from ..audit.comparator import compare_audits_from_files
from ..audit.engine import AuditResult, run_audit
from ..bcf.builder import push_bcf_topics
from ..classifier import (
    apply_classifications,
    items_from_suggestions,
    read_classifications_from_xlsx,
    suggest_for_findings,
)
from ..doe import (
    apply_matches_to_model,
    match_doe_records,
    parse_doe,
    summarize_matches,
)
from ..enrichment import enrich_with_public_data as _enrich_with_public_data
from ..extraction.client import BIMDataClient
from ..extraction.model_data import ModelSnapshot, extract_snapshot
from ..extraction.snapshot_cache import cached_extract_snapshot
from ..reporting.word_report import write_word_report
from ..reporting.xlsx_annex import write_xlsx_annex
from ..requirements.catalog import build_catalog
from ..requirements.models import BIMPhase, RequirementsCatalog
from ..safe_paths import safe_export_dir, safe_export_path, safe_input_path
from ..smartview.builder import push_smart_views
from .middleware import ApiKeyMiddleware, SessionBindingMiddleware
from .prompts import AMO_BIM_I3F_PROMPT
from .security import ensure_writes_allowed
from .session import _State

# Annotations conservées pour les imports externes (tests, scripts) qui
# référenceraient encore ces noms.
_ = (AuditResult, BIMDataClient, ModelSnapshot, RequirementsCatalog)


# ── Application MCP ────────────────────────────────────────────────────────


mcp = FastMCP("audit-bim-i3f")
# Middleware d'isolation de session (bind ``_State`` au client MCP courant)
# et d'authentification optionnelle. En stdio, les deux sont des no-ops
# transparents.
mcp.add_middleware(SessionBindingMiddleware())
mcp.add_middleware(ApiKeyMiddleware())


# Note : le bootstrap des chemins par défaut depuis l'env est fait dans
# ``_Session.__init__`` (cf. ``session.py``) — chaque session HTTP repart
# avec les mêmes pointeurs CCH/annexes qu'en stdio.


# ── Tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def project_context_questions() -> dict:
    """Inspecte l'état de la session et renvoie la **liste des questions** à
    poser à l'utilisateur si du contexte projet manque (phase, référentiel
    classification, CCH, disponibilité DOE).

    À appeler en début de session AVANT ``run_audit_tool`` pour s'assurer
    que l'audit est cadré. Renvoie une liste vide si tout est déjà connu.

    Returns:
        Dict ``{ready: bool, missing: [...], questions: [{key, question,
        suggestion}]}``.
    """
    questions: list[dict] = []
    missing: list[str] = []

    if _State.phase is None:
        missing.append("phase")
        questions.append(
            {
                "key": "phase",
                "question": (
                    "À quelle phase projet correspond cette maquette ? "
                    "APS, AVP, PRO, DCE, EXE, DOE ou GESTION ?"
                ),
                "suggestion": "PRO (cas le plus fréquent en cours de conception).",
            }
        )
    if _State.catalog is None and not (
        _State.cch_pdf or _State.data_spec_xlsx or _State.naming_spec_xlsx
    ):
        missing.append("cch")
        questions.append(
            {
                "key": "cch",
                "question": (
                    "Quel cahier des charges BIM dois-je appliquer ? Le CCH I3F "
                    "V3.6 par défaut, ou un référentiel projet spécifique ?"
                ),
                "suggestion": (
                    "CCH I3F V3.6 (chemins par défaut dans .env) — sinon "
                    "appelle set_owner_documents avec les chemins du référentiel."
                ),
            }
        )
    if _State.classification_system == "UniFormat II":
        # Pas vraiment manquant mais on précise le défaut au cas où
        questions.append(
            {
                "key": "classification_system",
                "question": (
                    "Quel référentiel de classification utiliser ? UniFormat II "
                    "(défaut), Omniclass, CCS, ou table 3F interne ?"
                ),
                "suggestion": "UniFormat II convient pour la majorité des projets I3F.",
                "optional": True,
            }
        )
    if _State.phase in (BIMPhase.DOE, BIMPhase.GESTION) and _State.doe_available is None:
        missing.append("doe_available")
        questions.append(
            {
                "key": "doe_available",
                "question": (
                    "Phase DOE/GESTION : disposez-vous de données DOE (Excel, "
                    "PDF, ERP/GMAO) pour enrichir la maquette ?"
                ),
                "suggestion": "Si oui, l'agent DOE → IFC pourra compléter les Psets.",
            }
        )
    if _State.client is None:
        missing.append("bimdata_target")
        questions.append(
            {
                "key": "bimdata_target",
                "question": (
                    "Quelle maquette BIMData auditer ? (cloud_id, project_id, "
                    "model_id — ou utiliser les valeurs du .env)"
                ),
                "suggestion": "Appelle set_active_model avec les bons IDs.",
            }
        )

    return {
        "ready": len([q for q in questions if not q.get("optional")]) == 0,
        "missing": missing,
        "questions": questions,
        "current_context": {
            "phase": _State.phase.value if _State.phase else None,
            "classification_system": _State.classification_system,
            "cch_pdf": str(_State.cch_pdf) if _State.cch_pdf else None,
            "model_id": _State.model_id,
            "doe_available": _State.doe_available,
        },
    }


@mcp.tool()
def set_owner_documents(
    cch_pdf: str | None = None,
    data_spec_xlsx: str | None = None,
    naming_spec_xlsx: str | None = None,
) -> dict:
    """Cible les 3 documents MOA (CCH PDF + annexe Spécifications + annexe Nommage).

    Tous les paramètres sont optionnels : on ne réécrit que ce qui est fourni.
    Les chemins déjà chargés depuis ``.env`` restent en place sinon.
    """
    # Validation : si un chemin est fourni, il doit passer par la
    # sandbox d'inputs (extension stricte selon le type de document,
    # racine ``AUDIT_INPUT_DIR`` quand définie, taille / traversal /
    # existence).
    if cch_pdf is not None:
        _State.cch_pdf = safe_input_path(cch_pdf, allowed_extensions={".pdf"}) if cch_pdf else None
    if data_spec_xlsx is not None:
        _State.data_spec_xlsx = (
            safe_input_path(data_spec_xlsx, allowed_extensions={".xlsx", ".xlsm"})
            if data_spec_xlsx
            else None
        )
    if naming_spec_xlsx is not None:
        _State.naming_spec_xlsx = (
            safe_input_path(naming_spec_xlsx, allowed_extensions={".xlsx", ".xlsm"})
            if naming_spec_xlsx
            else None
        )

    def stat(p: Path | None):
        if not p:
            return None
        return {
            "path": str(p),
            "exists": p.exists(),
            "size_bytes": (p.stat().st_size if p.exists() else None),
        }

    return {
        "cch_pdf": stat(_State.cch_pdf),
        "data_spec_xlsx": stat(_State.data_spec_xlsx),
        "naming_spec_xlsx": stat(_State.naming_spec_xlsx),
    }


@mcp.tool()
def parse_owner_requirements() -> dict:
    """Lit les documents MOA chargés et produit le catalogue d'exigences.

    Returns:
        Résumé du catalogue (nb propriétés, règles, étages, zones, pièces…).
    """
    _State.catalog = build_catalog(
        cch_pdf=_State.cch_pdf,
        data_spec_xlsx=_State.data_spec_xlsx,
        naming_spec_xlsx=_State.naming_spec_xlsx,
    )
    return _State.catalog.summary()


@mcp.tool()
def get_catalog_properties(
    ifc_class: str | None = None,
    phase: str | None = None,
    theme: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Filtre les PropertySpec du catalogue (avant ou après audit)."""
    _State.ensure_catalog()
    cat = _State.catalog
    out = list(cat.properties)
    if ifc_class:
        out = [p for p in out if p.ifc_class.lower() == ifc_class.lower()]
    if theme:
        out = [p for p in out if p.theme.lower() == theme.lower()]
    if phase:
        ph = BIMPhase(phase)
        out = [p for p in out if p.required_at(ph)]
    return [p.model_dump(mode="json") for p in out[:limit]]


@mcp.tool()
def set_active_model(
    cloud_id: str | None = None,
    project_id: str | None = None,
    model_id: str | None = None,
    phase: str = "PRO",
    classification_system: str | None = None,
    access_token: str | None = None,
) -> dict:
    """Cible la maquette BIMData et la phase BIM à auditer.

    Args:
        cloud_id, project_id, model_id: IDs BIMData (fallback ``.env``).
        phase: APS | AVP | PRO | DCE | EXE | DOE | GESTION (défaut PRO).
        classification_system: référentiel à utiliser pour les
            classifications. Valeurs admises : ``UniFormat II`` (défaut) |
            ``Omniclass`` | ``CCS`` | ``3F``.
        access_token: Bearer token déjà acquis (optionnel).
    """
    from ..classifier import get_system

    _State.cloud_id = cloud_id or config.CLOUD_ID
    _State.project_id = project_id or config.PROJECT_ID
    _State.model_id = model_id or config.MODEL_ID
    _State.phase = BIMPhase(phase.upper())
    if classification_system:
        # Valide le système (raise si inconnu)
        _State.classification_system = get_system(classification_system).label
    _State.client = BIMDataClient(
        cloud_id=_State.cloud_id,
        project_id=_State.project_id,
        model_id=_State.model_id,
        access_token=access_token,
    )
    # Invalide les caches downstream
    _State.snapshot = None
    _State.result = None
    return {
        "cloud_id": _State.cloud_id,
        "project_id": _State.project_id,
        "model_id": _State.model_id,
        "phase": _State.phase.value,
        "classification_system": _State.classification_system,
        "auth": "ok",
    }


@mcp.tool()
def list_classification_systems() -> list[dict]:
    """Liste les référentiels de classification disponibles côté MCP."""
    from ..classifier import SYSTEMS

    return [
        {
            "key": k,
            "name_for_bimdata_api": v.name,
            "label": v.label,
            "description": v.description,
            "has_mapper_from_uniformat": v.map_from_uniformat is not None,
        }
        for k, v in SYSTEMS.items()
    ]


@mcp.tool()
def extract_model_snapshot(use_cache: bool = True, cache_dir: str = ".audit_cache") -> dict:
    """Récupère le snapshot du modèle (espaces, zones, éléments…) depuis BIMData.

    Args:
        use_cache: Si ``True`` (défaut), utilise le cache local : un
            ``get_model()`` léger sert à comparer ``modified_date`` ;
            si le cache matche, lecture instantanée du fichier. Sinon
            extraction complète (5-10s) + écriture du cache.
        cache_dir: Dossier du cache local. Défaut ``.audit_cache``
            (relatif au cwd).

    Returns:
        Résumé du snapshot enrichi de ``from_cache: bool``.
    """
    _State.ensure_client()
    # Le dossier de cache est sandboxé : créé sous AUDIT_OUTPUT_DIR si
    # relatif, refusé s'il s'évade.
    safe_dir = safe_export_dir(cache_dir)
    if use_cache:
        _State.snapshot, hit = cached_extract_snapshot(
            _State.client, cache_dir=str(safe_dir), use_cache=True
        )
    else:
        _State.snapshot = extract_snapshot(_State.client)
        hit = False
    summary = _State.snapshot.summary()
    summary["from_cache"] = hit
    return summary


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
def run_audit_tool() -> dict:
    """Joue toutes les règles d'audit et renvoie un résumé des findings."""
    _State.ensure_catalog()
    _State.ensure_snapshot()
    if _State.phase is None:
        _State.phase = BIMPhase.PRO
    _State.result = run_audit(_State.snapshot, _State.catalog, _State.phase)
    return _State.result.summary()


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


def _default_output_paths() -> tuple[Path, Path]:
    """Renvoie deux chemins relatifs (docx, xlsx) — passés ensuite à
    :func:`safe_export_path` qui les résoudra sous ``AUDIT_OUTPUT_DIR``.
    """
    project_name = (_State.snapshot.project or {}).get("name") if _State.snapshot else None
    project_name = project_name or _State.project_id or "projet"
    safe = "".join(c for c in str(project_name) if c not in r'\/:*?"<>|').strip()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    phase = _State.phase.value if _State.phase else "PRO"
    base = f"audit_{safe}_{phase}_{ts}"
    return Path(f"{base}.docx"), Path(f"{base}_annexes.xlsx")


@mcp.tool()
def generate_xlsx_annex(output_path: str | None = None, overwrite: bool = False) -> dict:
    """Génère l'annexe Excel détaillée de l'audit courant.

    Le chemin de sortie est filtré par la sandbox d'export
    (:func:`audit_bim.safe_paths.safe_export_path`) : doit rester sous
    ``AUDIT_OUTPUT_DIR`` (défaut ``./out``), sans ``..``, pas
    d'écrasement silencieux sauf ``overwrite=True``.
    """
    _State.ensure_result()
    raw = Path(output_path) if output_path else _default_output_paths()[1]
    target = safe_export_path(raw, overwrite=overwrite)
    written = write_xlsx_annex(_State.result, target)
    return {"path": str(written), "size_bytes": written.stat().st_size}


@mcp.tool()
def generate_word_report(
    output_path: str | None = None,
    xlsx_annex_path: str | None = None,
    auditor: str = "AMO BIM (audit automatisé)",
    overwrite: bool = False,
) -> dict:
    """Génère le rapport Word d'audit.

    Le chemin de sortie est filtré par la sandbox d'export — cf.
    :func:`generate_xlsx_annex`.
    """
    _State.ensure_result()
    raw = Path(output_path) if output_path else _default_output_paths()[0]
    target = safe_export_path(raw, overwrite=overwrite)
    written = write_word_report(
        _State.result,
        target,
        auditor=auditor,
        xlsx_annex_path=xlsx_annex_path,
    )
    return {"path": str(written), "size_bytes": written.stat().st_size}


@mcp.tool()
def suggest_classifications(
    min_confidence: float = 0.4,
    top_n: int = 3,
    limit: int = 200,
) -> list[dict]:
    """Pour chaque élément avec ``classification_missing``, propose 1-3 codes
    UniFormat II déduits de la classe IFC, des layers, des attributs, des
    Pset_*Common (IsExternal…) et des BaseQuantities.

    Args:
        min_confidence: seuil de confiance (0..1) sous lequel on n'expose pas
            de suggestion.
        top_n: nombre maximum de suggestions par élément.
        limit: cap du nombre d'éléments retournés (pour préserver le canal MCP).
    """
    _State.ensure_result()
    out = suggest_for_findings(
        _State.result.findings,
        _State.result.snapshot,
        min_confidence=min_confidence,
        top_n=top_n,
    )
    return out[:limit]


@mcp.tool()
def apply_suggested_classifications(
    min_confidence: float = 0.5,
    dry_run: bool = True,
) -> dict:
    """Applique automatiquement (mode **sans contrôle**) les classifications
    proposées par le suggester aux éléments en ``classification_missing``.

    Workflow :
    1. Récupère la suggestion top de chaque élément non classifié dont la
       confiance ≥ ``min_confidence``.
    2. Crée les classifications nécessaires au niveau projet BIMData
       (dédupliquées par code+système).
    3. Lie en bulk les classifications aux éléments via
       ``POST /classification-element``.

    Args:
        min_confidence: seuil de confiance minimum (0..1) pour appliquer une
            suggestion. Plus le seuil est haut, moins on prend de risques.
        dry_run: si ``True`` (défaut), simule sans appel POST — renvoie un
            aperçu détaillé. Mettre ``False`` pour pousser réellement.

    Returns:
        Résumé : nombre d'éléments traités, classifications créées vs
        réutilisées, liens créés, erreurs éventuelles.
    """
    _State.ensure_result()
    _State.ensure_client()
    if not dry_run:
        ensure_writes_allowed("apply_suggested_classifications")
    suggestions = suggest_for_findings(
        _State.result.findings,
        _State.result.snapshot,
        min_confidence=min_confidence,
        top_n=1,
    )
    items = items_from_suggestions(suggestions, min_confidence=min_confidence)
    return apply_classifications(_State.client, items, dry_run=dry_run)


@mcp.tool()
def apply_classifications_from_xlsx(
    xlsx_path: str,
    dry_run: bool = True,
) -> dict:
    """Applique les classifications **validées par l'auditeur** dans un XLSX
    d'audit potentiellement modifié.

    L'auditeur télécharge l'annexe ``audit_*_annexes.xlsx`` (générée par
    ``generate_xlsx_annex`` / ``full_audit``), édite l'onglet
    *Classifications suggérées* en colonne « Suggestion 1 — code » :

    - laisser la valeur suggérée → la classification sera appliquée ;
    - modifier le code → on applique le code corrigé (ex: ``B2010`` → ``C1010``) ;
    - effacer la cellule → ligne ignorée (refus de la suggestion).

    Args:
        xlsx_path: chemin absolu vers l'annexe XLSX éventuellement modifiée.
        dry_run: si ``True`` (défaut), simule sans appel POST.

    Returns:
        Résumé identique à ``apply_suggested_classifications``, avec en plus
        ``n_items_read_from_xlsx`` pour traçabilité.
    """
    _State.ensure_client()
    if not dry_run:
        ensure_writes_allowed("apply_classifications_from_xlsx")
    safe_xlsx = safe_input_path(xlsx_path, allowed_extensions={".xlsx", ".xlsm"})
    items = read_classifications_from_xlsx(str(safe_xlsx))
    result = apply_classifications(_State.client, items, dry_run=dry_run)
    result["n_items_read_from_xlsx"] = len(items)
    result["xlsx_path"] = str(safe_xlsx)
    return result


@mcp.tool()
def doe_enrich_model(
    doe_path: str,
    dry_run: bool = True,
    name_min_score: int = 75,
    on_conflict: str = "report",
    ocr_fallback: bool = True,
    ocr_lang: str = "fra",
) -> dict:
    """Agent DOE → IFC : lit un fichier DOE (Excel, PDF natif ou scanné),
    rapproche les équipements aux éléments IFC du modèle, et enrichit la
    maquette BIMData avec gestion des conflits.

    Workflow :

    1. **Extraction** — auto-détection du format (xlsx / pdf), avec
       fallback OCR Tesseract pour les PDF scannés.
    2. **Matching** — 4 stratégies en cascade (GUID, Tag/Mark, Nom
       fuzzy via rapidfuzz, Localisation).
    3. **Détection des conflits** — pour chaque propriété DOE,
       classification ``MATCH`` (= valeur déjà présente, skip),
       ``NEW`` (absente, à écrire), ``UPGRADE`` (présente mais vide,
       à écrire), ``CONFLICT`` (différente — voir ``on_conflict``).
    4. **Enrichissement** — écrit les Psets sur les éléments matchés.

    Conventions de colonnes (mêmes pour Excel et PDF) :

    - **Identifiants** : ``UUID`` / ``Tag`` / ``Mark`` / ``Nom`` /
      ``Type`` / ``Étage`` / ``Zone`` (insensible casse + accents).
    - **Propriétés** : ``Pset_3F.Fabricant`` ou ``Pset_3F/Fabricant``
      pour cibler un Pset précis, sinon ``Pset_DOE`` par défaut.

    Args:
        doe_path: Chemin du fichier DOE (.xlsx / .xlsm / .pdf).
        dry_run: ``True`` (défaut) → simule sans POST. Renvoie payloads
            et résumé. ``False`` pour pousser réellement les Psets.
        name_min_score: Seuil fuzzy 0–100 pour le matching par nom
            (défaut 75). Monter à 85+ pour réduire les faux positifs.
        on_conflict: Stratégie quand la maquette a déjà une valeur
            différente du DOE :

            - ``"report"`` (défaut) : **n'écrase pas**. Signale les
              conflits dans la réponse. Mode prudent recommandé.
            - ``"skip"`` : comme report mais sans détail nominal.
            - ``"overwrite"`` : écrase. À réserver au DOE autoritaire
              (post-réception, validé MOA).
        ocr_fallback: PDF scanné détecté → OCR Tesseract (défaut
            ``True``). Nécessite ``pip install audit-bim-i3f[ocr]`` +
            binaire Tesseract installé.
        ocr_lang: Langue Tesseract (défaut ``"fra"``).
    """
    _State.ensure_client()
    _State.ensure_snapshot()
    if not dry_run:
        ensure_writes_allowed("doe_enrich_model")
    safe_doe = safe_input_path(doe_path)
    records = parse_doe(str(safe_doe), ocr_fallback=ocr_fallback, ocr_lang=ocr_lang)
    matches = match_doe_records(records, _State.snapshot, name_min_score=name_min_score)
    summary = summarize_matches(matches)
    application = apply_matches_to_model(
        _State.client,
        matches,
        dry_run=dry_run,
        snapshot=_State.snapshot,
        on_conflict=on_conflict,
    )
    return {
        "source": str(safe_doe),
        "summary": summary,
        "application": application,
    }


@mcp.tool()
def doe_match_only(
    doe_path: str,
    name_min_score: int = 75,
    limit: int = 50,
    ocr_fallback: bool = True,
    ocr_lang: str = "fra",
) -> dict:
    """Variante read-only de ``doe_enrich_model``.

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


@mcp.tool()
def create_bcf_topics(
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
) -> dict:
    """Crée des BCF Topics (panneau *BCF Issues* du viewer) pour chaque thème
    d'anomalie. Workflow d'issue : ``topic_type``, ``topic_status``,
    ``priority``, ``description`` riche, ``labels``, sélection + coloration
    des éléments concernés.

    À utiliser pour le **suivi de résolution** d'anomalies (assignation,
    commentaires, changement de statut Open → In Progress → Closed).

    En ``dry_run`` (défaut), renvoie les payloads sans POST. Format
    buildingSMART standard, portable hors BIMData.
    """
    _State.ensure_result()
    _State.ensure_client()
    if not dry_run:
        ensure_writes_allowed("create_bcf_topics")
    out = push_bcf_topics(_State.result, _State.client, prefix=prefix, dry_run=dry_run)
    return {"n_topics": len(out), "dry_run": dry_run, "topics": out}


@mcp.tool()
def create_smart_views(
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
) -> dict:
    """Crée des Smart Views (panneau *Smart Views* du viewer BIMData) pour
    chaque thème d'anomalie. Payload minimal : juste un coloring d'éléments
    par thème, sans workflow d'issue.

    À utiliser pour la **navigation 3D rapide** vers un sous-ensemble
    d'éléments. Pas d'assignation, pas de statut, pas de commentaires —
    c'est juste une vue colorée.

    En ``dry_run`` (défaut), renvoie les payloads JSON prêts à pousser, sans
    appel API. Mettre ``dry_run=False`` pour pousser réellement.
    """
    _State.ensure_result()
    _State.ensure_client()
    if not dry_run:
        ensure_writes_allowed("create_smart_views")
    out = push_smart_views(_State.result, _State.client, prefix=prefix, dry_run=dry_run)
    return {
        "n_views": len(out),
        "dry_run": dry_run,
        "views": out,
    }


@mcp.tool()
def full_audit(
    cloud_id: str | None = None,
    project_id: str | None = None,
    model_id: str | None = None,
    phase: str = "PRO",
    output_dir: str | None = None,
    push_mode: str = "ask",
    access_token: str | None = None,
) -> dict:
    """Orchestrateur : parse documents → extract modèle → audit → reports.

    Pour la *publication des résultats* dans le viewer BIMData, deux régimes
    distincts sont disponibles via ``push_mode`` :

    - ``"bcf"`` : crée des **BCF Topics** (panneau *BCF Issues*) — workflow
      d'issue à résoudre avec assignation, statut, commentaires, description
      riche, sélection + coloration.
    - ``"smartview"`` : crée des **Smart Views** (panneau dédié) — vues 3D
      minimales (coloring uniquement) pour navigation rapide.
    - ``"both"`` : pousse les deux régimes.
    - ``"none"`` : ne pousse rien (dry-run, payloads conservés en JSON).
    - ``"ask"`` (défaut) : aucune publication ; renvoie une question à
      l'utilisateur pour qu'il choisisse — Claude doit demander avant de
      ré-appeler ``full_audit`` avec une valeur explicite.

    Args:
        cloud_id, project_id, model_id: cible BIMData (fallback ``.env``).
        phase: phase BIM auditée.
        output_dir: dossier de sortie (fallback ``AUDIT_OUTPUT_DIR`` env).
        push_mode: ``"ask"`` | ``"bcf"`` | ``"smartview"`` | ``"both"`` | ``"none"``.
        access_token: bearer optionnel.
    """
    mode = (push_mode or "ask").lower()
    if mode == "ask":
        return {
            "status": "needs_user_choice",
            "question": (
                "Comment veux-tu publier les résultats de l'audit dans le viewer BIMData ?"
            ),
            "options": {
                "bcf": "BCF Topics — workflow d'issues à résoudre (assignation, "
                "statut, commentaires) dans le panneau BCF Issues.",
                "smartview": "Smart Views — vues 3D colorées dans le panneau "
                "Smart Views (navigation seulement, pas de workflow).",
                "both": "Les deux — pratique pour avoir à la fois la navigation "
                "rapide (Smart Views) et le suivi de correction (BCF).",
                "none": "Ne rien publier — les payloads sont sauvegardés en JSON.",
            },
            "next_step": ("Re-appeler full_audit avec push_mode=<bcf|smartview|both|none>."),
        }
    if mode not in ("bcf", "smartview", "both", "none"):
        raise ValueError(
            f"push_mode invalide : {push_mode!r}. Attendu : "
            "'ask' | 'bcf' | 'smartview' | 'both' | 'none'."
        )

    # 1. Catalogue
    _State.catalog = build_catalog(
        cch_pdf=_State.cch_pdf,
        data_spec_xlsx=_State.data_spec_xlsx,
        naming_spec_xlsx=_State.naming_spec_xlsx,
    )

    # 2. Cible
    set_active_model(
        cloud_id=cloud_id,
        project_id=project_id,
        model_id=model_id,
        phase=phase,
        access_token=access_token,
    )

    # 3. Snapshot
    _State.snapshot = extract_snapshot(_State.client)

    # 4. Audit
    _State.result = run_audit(_State.snapshot, _State.catalog, _State.phase)

    # 5. Livrables — tous les chemins passent par la sandbox d'export.
    # ``output_dir`` (relatif ou absolu) doit rester sous AUDIT_OUTPUT_DIR.
    do_push_bcf = mode in ("bcf", "both")
    do_push_sv = mode in ("smartview", "both")
    if do_push_bcf or do_push_sv:
        ensure_writes_allowed(f"full_audit(push_mode={mode})")

    raw_word, raw_xlsx = _default_output_paths()
    if output_dir:
        # output_dir est une sous-arborescence (sandbox-validée) où
        # écrire les livrables — on préfixe les noms par défaut.
        raw_word = Path(output_dir) / raw_word
        raw_xlsx = Path(output_dir) / raw_xlsx

    word_path = safe_export_path(raw_word)
    xlsx_path = safe_export_path(raw_xlsx)
    xlsx_written = write_xlsx_annex(_State.result, xlsx_path)
    word_written = write_word_report(_State.result, word_path, xlsx_annex_path=xlsx_written)

    # 6. Publication selon le mode
    bcf_result = push_bcf_topics(_State.result, _State.client, dry_run=not do_push_bcf)
    sv_result = push_smart_views(_State.result, _State.client, dry_run=not do_push_sv)

    # 7. JSON machine (chacun resandboxé pour être explicite)
    findings_json = safe_export_path(word_path.with_name(word_path.stem + "_findings.json"))
    findings_json.write_text(
        json.dumps(
            [f.model_dump(mode="json") for f in _State.result.findings],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    bcf_json = safe_export_path(word_path.with_name(word_path.stem + "_bcf_topics.json"))
    bcf_json.write_text(
        json.dumps(bcf_result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    sv_json = safe_export_path(word_path.with_name(word_path.stem + "_smart_views.json"))
    sv_json.write_text(
        json.dumps(sv_result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    return {
        "summary": _State.result.summary(),
        "deliverables": {
            "word": str(word_written),
            "xlsx": str(xlsx_written),
            "findings_json": str(findings_json),
            "bcf_topics_json": str(bcf_json),
            "smart_views_json": str(sv_json),
        },
        "push_mode": mode,
        "bcf_topics": {"n": len(bcf_result), "pushed": do_push_bcf},
        "smart_views": {"n": len(sv_result), "pushed": do_push_sv},
    }


# ── Prompt MCP ─────────────────────────────────────────────────────────────


@mcp.prompt()
def amo_bim_i3f() -> str:
    """Persona AMO BIM I3F — chargée par Claude au démarrage du serveur."""
    return AMO_BIM_I3F_PROMPT


def main() -> None:
    """Point d'entrée du serveur MCP (lance la boucle stdio)."""
    mcp.run()


if __name__ == "__main__":
    main()
