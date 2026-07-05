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
import logging
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

from .. import config
from ..audit.comparator import compare_audits_from_files
from ..audit.engine import AuditResult, run_audit
from ..bcf.builder import push_bcf_topics
from ..classifier import (
    apply_classifications,
    read_classifications_from_xlsx,
    suggest_for_findings,  # noqa: F401  — re-export public (compat)
)
from ..doe import (
    match_doe_records,
    parse_doe,
    summarize_matches,
)
from ..enrichment import enrich_with_public_data as _enrich_with_public_data
from ..extraction.client import BIMDataClient
from ..extraction.model_data import ModelSnapshot, extract_snapshot
from ..extraction.snapshot_cache import cached_extract_snapshot
from ..reporting.context import build_report_context, merge_user_context
from ..reporting.word_report import write_word_report
from ..reporting.xlsx_annex import write_xlsx_annex
from ..requirements.catalog import build_catalog
from ..requirements.models import BIMPhase, RequirementsCatalog
from ..safe_paths import safe_export_dir, safe_export_path, safe_input_path
from ..smartview.builder import push_smart_views
from .middleware import ApiKeyMiddleware, SessionBindingMiddleware
from .model_identity import model_matches_expected, resolve_bimdata_target
from .prompts import AMO_BIM_I3F_PROMPT
from .security import ensure_access_token_param_allowed, ensure_writes_allowed
from .security import scrub as _scrub
from .session import _State

_server_logger = logging.getLogger("audit_bim.mcp.server")

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
        # Question de phase **unique**, alignée sur le contrat (clé
        # ``project_phase``, aide loi MOP, détection IFC + rapprochement).
        # Pas de suggestion « PRO » codée en dur ni de clé divergente.
        missing.append("project_phase")
        det_raw, det_mapped = _detect_snapshot_phase()
        questions.append(_phase_question_dict(det_raw, det_mapped))
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
                    "Quelle maquette BIMData auditer ? Collez l'URL du viewer "
                    "BIMData, ou fournissez cloud_id, project_id et model_id."
                ),
                "suggestion": (
                    "Appelle set_active_model(bimdata_url=...) ; les IDs restent "
                    "acceptés et les valeurs du .env servent de fallback."
                ),
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
    bimdata_url: str | None = None,
    phase: str = "PRO",
    classification_system: str | None = None,
    access_token: str | None = None,
) -> dict:
    """Cible la maquette BIMData et la phase BIM à auditer.

    .. warning::
       ``access_token`` reste **déconseillé en transport réseau** :
       les paramètres MCP peuvent transiter dans des logs client,
       des traces d'agent ou des historiques JSON-RPC. Préférer la
       configuration côté serveur via ``BIMDATA_API_KEY`` /
       ``BIMDATA_CLIENT_ID``+``…_SECRET``, ou l'injection d'identité
       par le reverse-proxy. Utiliser ce paramètre uniquement en
       contexte stdio local / dev. Côté audit-bim-i3f, le token est
       *scrubbé* (sha-256[:8]) dans les logs serveur, mais l'appelant
       est responsable de sa propre hygiène de logs.

    Args:
        cloud_id, project_id, model_id: IDs BIMData (fallback ``.env``).
            ``model_id`` accepte aussi une URL viewer complète pour tolérer
            un copier-coller direct.
        bimdata_url: URL viewer BIMData
            ``https://platform.bimdata.io/spaces/<cloud>/projects/<project>/viewer/<model>``.
            Les IDs sont extraits automatiquement. Si des IDs explicites sont
            également fournis, ils doivent correspondre à l'URL.
        phase: APS | AVP | PRO | DCE | EXE | DOE | GESTION (défaut PRO).
        classification_system: référentiel à utiliser pour les
            classifications. Valeurs admises : ``UniFormat II`` (défaut) |
            ``Omniclass`` | ``CCS`` | ``3F``.
        access_token: Bearer token déjà acquis (optionnel, local/dev).
    """
    from ..classifier import get_system

    cloud_id, project_id, model_id = resolve_bimdata_target(
        cloud_id=cloud_id,
        project_id=project_id,
        model_id=model_id,
        bimdata_url=bimdata_url,
    )
    _State.cloud_id = cloud_id or config.CLOUD_ID
    _State.project_id = project_id or config.PROJECT_ID
    _State.model_id = model_id or config.MODEL_ID
    _State.phase = BIMPhase(phase.upper())
    if classification_system:
        # Valide le système (raise si inconnu)
        _State.classification_system = get_system(classification_system).label
    if access_token:
        # Garde-fou : refus du mode "token en paramètre MCP" sur les
        # transports réseau, sauf opt-in explicite. Levée d'un
        # AccessTokenParamDisabledError (PermissionError) avant tout
        # log ou stockage.
        ensure_access_token_param_allowed()
        _server_logger.info(
            "set_active_model cloud=%s project=%s model=%s token=%s",
            _State.cloud_id,
            _State.project_id,
            _State.model_id,
            _scrub(access_token),
        )
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
def verify_active_model(
    expected_model_name: str,
    refresh_snapshot: bool = True,
    use_cache: bool = False,
) -> dict:
    """Garde-fou d'identité : confirme que la maquette BIMData active est
    bien celle attendue **avant** de lancer l'audit ou la génération des
    livrables.

    Pourquoi : ``set_active_model`` invalide bien ``_State.snapshot`` et
    le cache disque est keyé par ``model_id`` — il n'y a donc *pas* de
    risque de contamination entre maquettes côté infrastructure. Le
    risque résiduel est **humain** : l'auditeur copie-colle un mauvais
    ``model_id`` (vue BIMData voisine, ancien projet, mauvais build du
    DOE) et le pipeline génère alors un rapport parfaitement cohérent…
    sur la mauvaise maquette. Le contrôle d'identité ferme cette
    fenêtre : on rafraîchit (par défaut) le snapshot sans cache, puis
    on compare ``model.name`` à ``expected_model_name`` via une
    correspondance insensible à la casse, aux accents et aux espaces
    multiples (le pattern attendu doit être *inclus* dans le nom du
    modèle).

    Args:
        expected_model_name: Fragment attendu dans le nom du modèle.
            Exemple : ``"LIFFRE"`` matche ``"Maquette BIM - LIFFRÉ -
            DOE.ifc"``.
        refresh_snapshot: Si ``True`` (défaut), appelle
            ``extract_model_snapshot`` pour rafraîchir
            ``_State.snapshot``. Si ``False``, utilise le snapshot déjà
            en session et lève une erreur claire s'il n'en existe pas.
        use_cache: Si ``False`` (défaut), force une extraction
            complète sans cache — la valeur recommandée pour ce
            contrôle. À ne passer à ``True`` que si on accepte
            explicitement de lire depuis le cache local.

    Returns:
        Dict ``{ok, expected_model_name, project_name, model_name,
        model_id, modified_date, from_cache, message}``. Quand
        ``ok=False`` l'audit ne doit pas être lancé ; cet outil ne
        modifie jamais ``_State.result``.
    """
    _State.ensure_client()
    expected = (expected_model_name or "").strip()
    if not expected:
        raise ValueError("expected_model_name est requis et ne peut pas être vide.")

    from_cache: bool | None
    if refresh_snapshot:
        if use_cache:
            _State.snapshot, hit = cached_extract_snapshot(
                _State.client, cache_dir=".audit_cache", use_cache=True
            )
            from_cache = hit
        else:
            _State.snapshot = extract_snapshot(_State.client)
            from_cache = False
    else:
        if _State.snapshot is None:
            raise RuntimeError(
                "Aucun snapshot disponible pour verify_active_model — "
                "appelez extract_model_snapshot(use_cache=false) au préalable "
                "ou laissez refresh_snapshot=true."
            )
        from_cache = None

    model = _State.snapshot.model or {}
    project = _State.snapshot.project or {}
    model_name = model.get("name")
    model_id = model.get("id") or _State.model_id
    modified_date = model.get("modified_date") or model.get("modified")

    ok = model_matches_expected(model_name, expected)
    if ok:
        message = f"Modèle actif conforme : '{model_name}' contient bien '{expected}'."
    else:
        message = (
            f"Modèle actif inattendu : attendu '{expected}', "
            f"reçu '{model_name}' (model_id={model_id}). "
            "N'enchaînez PAS l'audit avant correction (set_active_model + verify_active_model)."
        )
    return {
        "ok": ok,
        "expected_model_name": expected,
        "project_name": project.get("name"),
        "model_name": model_name,
        "model_id": model_id,
        "modified_date": modified_date,
        "from_cache": from_cache,
        "message": message,
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
def generate_avp_i3f_pack(
    output_dir: str | None = None,
    controle_xlsx: str | None = None,
    shab_xlsx: str | None = None,
    zones_espaces_xlsx: str | None = None,
    enveloppe_xlsx: str | None = None,
    menuiseries_xlsx: str | None = None,
    project_name: str | None = None,
    project_code: str | None = None,
    phase: str | None = None,
    auditor: str | None = None,
    usages_bim: list[str] | None = None,
    nombre_logements: str | None = None,
    temoin_virtuel: str | None = None,
    date_controle: str | None = None,
    auteur_controle: str | None = None,
    export_pdf: bool = True,
    confirm_context: bool = False,
) -> dict:
    """Génère le pack de livrables AVP I3F (charte BIMData).

    Produit les 5 Excel (Contrôle Maquettes, SHAB, Zones/Espaces, Enveloppe,
    Menuiseries) + le rapport consolidé « Analyse BIM AVP » (.docx, + .pdf
    best-effort). **Hybride** : données natives de l'audit courant
    (``_State.result``, si disponible) + lecture des .xlsx sources I3F
    fournis pour les colonnes d'outils externes. Toute donnée absente →
    « Information non disponible dans les documents fournis. » (jamais
    inventée).

    Nommage des livrables — convention documentaire I3F **générée à partir
    de données projet confirmées** :
    ``YYMMDD <NomProjet> <CodeProjet> <Phase> - <TypeLivrable>.<ext>``
    (``YYMMDD`` = date de génération). Le **nom du projet** est cherché dans
    les métadonnées BIMData/IFC (``project.name`` / ``IfcSite.Name``), le
    **code (ESI)** dans le contrôle maquettes I3F, la **phase** est la phase
    confirmée de l'audit (``_State.phase``). Si le nom ou le code restent
    introuvables et ne sont pas fournis, le tool renvoie
    ``{status: needs_context}`` avec les questions à poser (sauf
    ``confirm_context=True``).

    Args:
        output_dir: sous-dossier d'export (sandbox ``AUDIT_OUTPUT_DIR``).
        controle_xlsx … menuiseries_xlsx: chemins des .xlsx sources I3F
            (optionnels, sandbox lecture ``safe_input_path``).
        project_name, project_code, phase: identité projet pour le nommage.
            ``None`` → résolus depuis la maquette / les sources / la phase
            d'audit confirmée ; nom ou code introuvable → ``needs_context``.
        auditor, auteur_controle: nom de l'auteur du contrôle affiché sur le
            pack. **Demandé explicitement** (``needs_context``) si aucun des
            deux n'est fourni — pas de « AMO BIM » générique par défaut, sauf
            ``confirm_context=True``. ``auteur_controle`` prime sur ``auditor``.
        usages_bim, nombre_logements, temoin_virtuel, date_controle:
            métadonnées opérationnelles du contrôle (issues du rapport I3F de
            référence) pour « Données d'entrée » / « Usages BIM 3F ». Absentes
            → « Information non disponible… ».
        export_pdf: tente la conversion .docx → .pdf (LibreOffice si présent).
        confirm_context: ``True`` pour générer malgré un nom/code/phase/auteur
            manquant.

    Returns:
        ``{output_dir, paths, analyse_docx, analyse_pdf, pdf_available}`` ou
        ``{status: needs_context, missing, questions}``.
    """
    from ..reporting.avp_i3f import write_avp_i3f_report_pack
    from ..reporting.avp_sources import AvpSourcePaths, load_sources

    def _src(p: str | None) -> str | None:
        return str(safe_input_path(p, allowed_extensions={".xlsx", ".xlsm"})) if p else None

    source_paths = AvpSourcePaths(
        controle=_src(controle_xlsx),
        shab=_src(shab_xlsx),
        zones_espaces=_src(zones_espaces_xlsx),
        enveloppe=_src(enveloppe_xlsx),
        menuiseries=_src(menuiseries_xlsx),
    )
    # Chargement unique des sources (lues aussi pour résoudre le code ESI).
    sources = load_sources(source_paths)
    ctrl_header = (sources.controle.header if sources.controle else {}) or {}

    def _hdr(key: str) -> str | None:
        v = ctrl_header.get(key)
        return str(v).strip() if v not in (None, "") and str(v).strip() else None

    # ── Résolution de l'identité projet (nom / code / phase) ────────────
    # Nom : param explicite > **entête « Projet » du contrôle I3F** (source
    # livrable, autoritaire pour l'identité I3F) > métadonnées maquette.
    # ``project.name`` BIMData peut être générique (ex. « I3F ») : la source
    # de contrôle prime pour ne pas nommer les livrables de travers.
    eff_name = (project_name or "").strip() or _hdr("projet") or _snapshot_project_name()
    # Code (ESI) : param > entête « ESI » du contrôle maquettes I3F.
    eff_code = (project_code or "").strip() or _hdr("esi")
    # Phase : param explicite > phase d'audit confirmée > entête contrôle I3F.
    eff_phase = (phase or "").strip() or None
    if not eff_phase and _State.phase is not None:
        eff_phase = _State.phase.value
    if not eff_phase:
        eff_phase = _map_phase(_hdr("phase"))

    # Auteur du contrôle : I3F attend un auteur nommé (CdP BIM / auditeur
    # AMO). On **demande** explicitement plutôt que de retomber sur un
    # « AMO BIM » générique — sauf si ``auteur_controle`` ou ``auditor``
    # sont fournis, ou ``confirm_context``.
    eff_auditor = (auditor or "").strip() or None
    eff_auteur = (auteur_controle or "").strip() or None

    # Nom / code / phase obligatoires pour un livrable I3F fiable → sinon on
    # demande (jamais de valeur inventée ni de défaut silencieux).
    missing: list[str] = []
    questions: list[dict] = []
    if not eff_name:
        missing.append("project_name")
        questions.append(
            {
                "key": "project_name",
                "question": "Quel nom de projet doit apparaître dans les livrables ?",
            }
        )
    if not eff_code:
        missing.append("project_code")
        questions.append(
            {
                "key": "project_code",
                "question": (
                    "Quel code projet / ESI doit apparaître dans les livrables ? "
                    "(ex. « 0546L », visible sur le contrôle maquettes I3F)"
                ),
            }
        )
    if not eff_phase:
        # Phase unique : proposée si détectée (IFC puis entête contrôle),
        # sinon demandée — jamais défautée silencieusement sur « AVP ».
        missing.append("project_phase")
        det_raw, det_mapped = _detect_snapshot_phase()
        if not det_raw:
            hdr_phase = _hdr("phase")
            if hdr_phase:
                det_raw, det_mapped = hdr_phase, _map_phase(hdr_phase)
        questions.append(_phase_question_dict(det_raw, det_mapped))
    if not eff_auteur and not eff_auditor:
        missing.append("auteur_controle")
        questions.append(
            {
                "key": "auteur_controle",
                "question": (
                    "Quel nom afficher comme « Auteur du contrôle » sur le pack "
                    "AVP I3F ? (ex. le CdP BIM 3F, ou l'auditeur AMO — passer "
                    "``auteur_controle`` ou ``auditor``)"
                ),
            }
        )
    if missing and not confirm_context:
        return {
            "status": "needs_context",
            "missing": missing,
            "questions": questions,
            "next_step": (
                "Renseigner ``project_name`` / ``project_code`` / "
                "``project_phase`` (=``phase``) / ``auteur_controle`` (ou "
                "``auditor``) puis re-appeler ``generate_avp_i3f_pack``. Pour "
                "générer malgré tout, passer ``confirm_context=True``."
            ),
        }

    from ..reporting.avp_i3f import AvpQaError

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = safe_export_dir(output_dir or f"avp_pack_{ts}")
    try:
        pack = write_avp_i3f_report_pack(
            _State.result,  # peut être None : le pack se limite alors aux sources
            out_dir,
            sources=sources,
            # Snapshot explicite : le repli maquette s'active même sans audit
            # (ex. après verify_active_model seul, _State.result est None).
            snapshot=_State.snapshot,
            project_name=eff_name or "Projet",
            project_code=eff_code or "",
            phase=eff_phase or "AVP",
            # Auteur validé/fourni (ou repli « AMO BIM » uniquement sous
            # confirm_context — voluntary confirmation).
            auditor=eff_auditor or "AMO BIM",
            usages_bim=usages_bim,
            nombre_logements=nombre_logements,
            temoin_virtuel=temoin_virtuel,
            date_controle=date_controle,
            auteur_controle=auteur_controle,
            export_pdf=export_pdf,
        )
    except AvpQaError as exc:
        # QA gate : au moins une annexe est sortie vide alors que la
        # maquette contient des données exploitables. Statut d'erreur
        # explicite — surtout pas un livrable client vide.
        return {
            "status": "error",
            "error": "empty_deliverable",
            "empty_deliverables": exc.empty,
            "message": str(exc),
        }
    return {
        "output_dir": str(out_dir),
        "paths": [str(p) for p in pack.paths()],
        "analyse_docx": str(pack.analyse_docx),
        "analyse_pdf": str(pack.analyse_pdf) if pack.analyse_pdf else None,
        "pdf_available": pack.analyse_pdf is not None,
        "project_name": eff_name,
        "project_code": eff_code,
        "phase": eff_phase,
    }


_VALID_PHASES = {p.value for p in BIMPhase}

# Aide de lecture « loi MOP / mission MOE » affichée avec la question de
# phase (une seule question, pas de second champ). Éclaire l'équivalence
# entre le vocabulaire loi MOP et la phase d'audit BIM.
_PHASE_READING_AID = {
    "APS": "avant-projet sommaire",
    "AVP": "avant-projet, ou APD si le projet est en avant-projet définitif",
    "PRO": "études de projet",
    "DCE": "consultation des entreprises / dossier marché",
    "EXE": "études d'exécution, VISA, DET, ACT ou suivi chantier",
    "DOE": "dossier des ouvrages exécutés / réception",
    "GESTION": "exploitation patrimoniale",
}

# Rapprochement des jalons loi MOP / mission MOE non reconnus comme phase
# d'audit BIM vers la phase BIM la plus proche. La phase d'audit reste
# l'unique source de vérité : ce mapping ne fait que **proposer** une
# correspondance à confirmer par l'utilisateur.
_PHASE_ALIASES = {
    "ESQ": "APS",  # esquisse
    "DIA": "APS",  # diagnostic
    "APD": "AVP",  # avant-projet définitif
    "ACT": "EXE",  # assistance passation des contrats de travaux
    "VISA": "EXE",
    "DET": "EXE",  # direction de l'exécution des travaux
    "AOR": "DOE",  # assistance aux opérations de réception
}


def _map_phase(raw: str | None) -> str | None:
    """Mappe une valeur de phase brute vers une phase d'audit BIM valide.

    Renvoie la phase BIM (``APS``…``GESTION``) si ``raw`` est déjà une
    phase valide ou possède un alias loi MOP connu ; ``None`` sinon.
    """
    if not raw or not str(raw).strip():
        return None
    up = str(raw).strip().upper()
    if up in _VALID_PHASES:
        return up
    return _PHASE_ALIASES.get(up)


def _detect_snapshot_phase() -> tuple[str | None, str | None]:
    """Détecte la phase déclarée dans l'IFC / les métadonnées BIMData.

    Cherche une valeur de phase (``IfcProject.Phase`` et équivalents) dans
    les dicts ``project`` puis ``model`` du snapshot actif.

    Returns:
        ``(raw, mapped)`` où ``raw`` est la valeur brute trouvée (ex.
        ``"APD"``) et ``mapped`` la phase d'audit BIM correspondante (ex.
        ``"AVP"``) ou ``None`` si non rapprochable. ``(None, None)`` si
        aucune phase n'est déclarée.
    """
    snap = _State.snapshot
    if snap is None:
        return (None, None)
    _keys = {"phase", "bim_phase", "projectphase", "project_phase", "phase_bim"}
    for container in ((snap.project or {}), (snap.model or {})):
        for key, val in container.items():
            if str(key).strip().lower() in _keys and isinstance(val, str) and val.strip():
                raw = val.strip()
                return (raw, _map_phase(raw))
    return (None, None)


def _phase_question(detected_raw: str | None, suggested: str | None) -> str:
    """Compose l'unique question de phase (avec proposition/mapping).

    Trois cas :

    - phase détectée **reconnue** → demander confirmation explicite ;
    - phase détectée **non reconnue** mais rapprochable → proposer le
      rapprochement à confirmer/corriger ;
    - rien de détecté (ou non rapprochable) → question ouverte.
    """
    base = (
        "Quelle est la phase du projet à auditer ? "
        "Phases proposées : APS, AVP, PRO, DCE, EXE, DOE, GESTION."
    )
    if detected_raw and suggested and detected_raw.strip().upper() in _VALID_PHASES:
        return (
            f"Phase détectée dans l'IFC : « {detected_raw} ». Confirmez-vous que "
            f"l'audit doit être lancé en phase {suggested} ? (sinon, indiquez la "
            f"phase correcte parmi : APS, AVP, PRO, DCE, EXE, DOE, GESTION)"
        )
    if detected_raw and suggested:
        return (
            f"Phase détectée : « {detected_raw} ». Proposition d'audit : "
            f"{suggested}. Confirmer ou corriger (APS, AVP, PRO, DCE, EXE, "
            f"DOE, GESTION)."
        )
    if detected_raw:
        return (
            f"Phase détectée : « {detected_raw} » (non reconnue). Choisir la "
            f"phase d'audit correspondante. " + base
        )
    return base


def _phase_question_dict(detected_raw: str | None, suggested: str | None) -> dict:
    """Question de phase **unique** normalisée (clé ``project_phase``).

    Embarque l'aide de lecture loi MOP / mission MOE dans la même question
    (pas de second champ) et la proposition (``suggested_value``) issue de
    la détection IFC. Partagée par ``_validate_audit_context`` et
    ``project_context_questions`` pour éviter tout flux de phase divergent.
    """
    q: dict = {
        "key": "project_phase",
        "question": _phase_question(detected_raw, suggested),
        "aide_lecture_loi_mop": dict(_PHASE_READING_AID),
    }
    if suggested:
        q["suggested_value"] = suggested
    return q


def _snapshot_address_suggestion() -> str | None:
    """Adresse suggérée depuis le snapshot actif (``IfcBuilding.BuildingAddress``
    / ``IfcSite.SiteAddress``), ou ``None``. Best-effort, ne lève pas."""
    snap = _State.snapshot
    if snap is None:
        return None
    try:
        from ..enrichment.address import resolve_project_address

        return resolve_project_address(snap).to_query() or None
    except Exception:
        return None


def _snapshot_description() -> str | None:
    """Description projet suggérée depuis le snapshot (``project.description``
    / ``longname``), ou ``None``."""
    snap = _State.snapshot
    if snap is None:
        return None
    proj = snap.project or {}
    for key in ("description", "longname", "long_name"):
        v = proj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _snapshot_project_name() -> str | None:
    """Nom de projet exploitable pour le nommage des livrables.

    Cascade : ``IfcProject.Name`` (``project.name``) → ``project.long_name``
    → ``IfcSite.Name`` du premier site. ``None`` si rien d'exploitable.
    """
    snap = _State.snapshot
    if snap is None:
        return None
    proj = snap.project or {}
    for key in ("name", "Name", "long_name", "LongName", "longname"):
        v = proj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for site in getattr(snap, "sites", None) or []:
        v = (site or {}).get("name") or (site or {}).get("Name")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _validate_audit_context(
    *,
    project_address: str | None,
    project_phase: str | None,
    auditor_name: str | None,
    confirm_context: bool,
    project_description: str | None = None,
    require_description: bool = False,
    suggested_address: str | None = None,
    suggested_description: str | None = None,
    suggested_phase: str | None = None,
    detected_phase_raw: str | None = None,
    require_phase_confirmation: bool = False,
) -> dict | None:
    """Valide les informations de contexte obligatoires avant audit.

    Renvoie ``None`` si tout est OK ; renvoie un dict de refus
    structuré (avec ``status='needs_context'``, ``missing`` et
    ``questions``) si une info manque et que ``confirm_context``
    n'est pas mis à ``True``.

    Ne **jamais** inventer une valeur — l'utilisateur DOIT fournir (ou
    valider explicitement une **suggestion** issue de la maquette,
    fournie via ``suggested_value`` dans la question).

    ``require_description`` n'active la validation de la description que
    lorsqu'un snapshot est disponible (donc qu'on peut proposer une
    suggestion) — un ``full_audit`` « à froid » n'est pas impacté.

    Phase — question **unique** (pas de doublon loi MOP / phase BIM) :
    ``require_phase_confirmation`` force la demande de validation quand
    l'utilisateur n'a pas passé de phase explicite (on propose alors la
    phase détectée dans l'IFC via ``suggested_phase`` / ``detected_phase_raw``
    et l'aide de lecture loi MOP). La phase confirmée est l'unique source
    de vérité (audit + rapport Word + pack AVP).
    """
    missing: list[str] = []
    questions: list[dict] = []
    if not project_address or not project_address.strip():
        missing.append("project_address")
        q: dict[str, str] = {
            "key": "project_address",
            "question": (
                "Quelle est l'adresse du projet ? "
                "(ex: « 12 rue de la Paix, 35340 LIFFRÉ »). "
                "Le rapport Word affichera cette adresse comme "
                "donnée fiable, fournie par l'utilisateur."
            ),
        }
        if suggested_address:
            q["suggested_value"] = suggested_address
            q["question"] += (
                f" Suggestion extraite de la maquette (IfcPostalAddress) : "
                f"« {suggested_address} » — merci de la valider ou de la corriger."
            )
        questions.append(q)
    # Phase — question unique. On la pose si la phase est absente/invalide,
    # OU si une confirmation explicite est requise (l'utilisateur n'a pas
    # passé de phase explicite : on propose la phase détectée à valider).
    phase_valid = bool(project_phase) and project_phase.upper() in _VALID_PHASES
    if not phase_valid or require_phase_confirmation:
        missing.append("project_phase")
        questions.append(_phase_question_dict(detected_phase_raw, suggested_phase))
    if not auditor_name or not auditor_name.strip():
        missing.append("auditor_name")
        questions.append(
            {
                "key": "auditor_name",
                "question": (
                    "Sous quel nom afficher l'auditeur sur la page de garde "
                    "et dans la section « Contexte de la mission » du rapport "
                    "Word ?"
                ),
            }
        )

    # Description : validée uniquement quand un snapshot est disponible
    # (on peut alors proposer une suggestion). Un snapshot muet → question
    # sans suggestion ; pas de snapshot → on ne bloque pas.
    if require_description and (not project_description or not project_description.strip()):
        missing.append("project_description")
        q_desc: dict[str, str] = {
            "key": "project_description",
            "question": (
                "Quelle description du projet afficher dans la section "
                "« Description du projet » du rapport Word ?"
            ),
        }
        if suggested_description:
            q_desc["suggested_value"] = suggested_description
            q_desc["question"] += (
                f" Suggestion extraite de la maquette : « {suggested_description} » "
                "— à valider ou corriger."
            )
        questions.append(q_desc)

    if not missing:
        return None  # tout est OK

    if confirm_context:
        # L'utilisateur a explicitement confirmé qu'il accepte de lancer
        # malgré l'absence de certaines infos. On le laisse passer mais
        # le rapport affichera NOT_AVAILABLE pour les champs manquants.
        return None

    return {
        "status": "needs_context",
        "missing": missing,
        "questions": questions,
        "next_step": (
            "Renseigner les informations manquantes puis re-appeler le tool "
            "avec les paramètres ``project_address``, ``project_phase``, "
            "``auditor_name`` (et ``project_description`` si demandée). Les "
            "questions comportant ``suggested_value`` proposent une valeur "
            "extraite de la maquette : la faire valider ou corriger par "
            "l'utilisateur. Pour lancer malgré tout sans toutes les infos "
            "(déconseillé), passer ``confirm_context=True``."
        ),
    }


@mcp.tool()
def generate_word_report(
    output_path: str | None = None,
    xlsx_annex_path: str | None = None,
    auditor: str = "AMO BIM (audit automatisé)",
    overwrite: bool = False,
    project_address: str | None = None,
    project_phase: str | None = None,
    auditor_name: str | None = None,
    project_description: str | None = None,
    confirm_context: bool = False,
) -> dict:
    """Génère le rapport Word d'audit (enrichi avec contexte projet).

    Le rapport Word produit inclut désormais les sections :
    *Contexte de la mission*, *Description du projet*, *Référentiels*,
    *Attendus du projet*, *Objectifs BIM*, *Liste des contrôles
    réalisés*, *Informations non disponibles*. Voir
    :mod:`audit_bim.reporting.context`.

    Trois informations contextuelles sont **recommandées** pour un
    livrable AMO BIM professionnel :

    - ``project_address`` : adresse du projet (affichée dans
      *Description du projet*).
    - ``project_phase`` : APS / APD / PRO / DCE / EXE / DOE / GESTION.
      Si fourni, écrase la phase déduite du ``AuditResult`` pour
      l'affichage. **Ne change PAS** la phase utilisée pour exécuter
      l'audit (qui a déjà tourné).
    - ``auditor_name`` : nom de l'auditeur (page de garde + section
      *Contexte de la mission*).

    Si l'une de ces 3 infos est manquante **et** ``confirm_context``
    est ``False``, le tool retourne ``{"status": "needs_context", ...}``
    avec la liste des questions à poser à l'utilisateur, sans
    régénérer le rapport.

    Args:
        output_path: Chemin de sortie (sandbox ``AUDIT_OUTPUT_DIR``).
        xlsx_annex_path: Référence à l'annexe XLSX (mise en annexe).
        auditor: Nom de l'auditeur (legacy param ; déprécié au profit
            de ``auditor_name`` qui propage dans le contexte enrichi).
        overwrite: Écraser le fichier existant.
        project_address: Adresse projet (data fiable utilisateur).
        project_phase: Phase BIM à afficher.
        auditor_name: Nom de l'auditeur enrichi.
        confirm_context: ``True`` pour passer outre la validation des
            3 champs obligatoires (rapport généré avec
            ``Information non disponible`` pour les manquants).

    Returns:
        - ``{"path": "...", "size_bytes": N}`` en cas de succès.
        - ``{"status": "needs_context", "missing": [...], "questions":
          [...]}`` si validation refusée.
    """
    _State.ensure_result()

    # Suggestions issues de la maquette pour le dialogue de contexte
    # (adresse IfcPostalAddress, description projet). Le snapshot est
    # présent (``ensure_result`` implique un audit sur snapshot).
    sugg_address = _snapshot_address_suggestion()
    sugg_description = _snapshot_description()

    # Phase — unique source de vérité. L'audit a déjà tourné : ``_State.phase``
    # est la phase confirmée. On ne re-demande une confirmation que si aucune
    # phase n'est établie (ni fournie, ni posée en session).
    explicit_phase = (
        project_phase.strip() if isinstance(project_phase, str) and project_phase.strip() else None
    )
    detected_raw, detected_mapped = _detect_snapshot_phase()
    if explicit_phase:
        eff_phase = explicit_phase
    elif _State.phase is not None:
        eff_phase = _State.phase.value
    else:
        eff_phase = detected_mapped
    require_phase_confirmation = explicit_phase is None and _State.phase is None
    suggested_phase = (
        eff_phase if eff_phase and eff_phase.upper() in _VALID_PHASES else detected_mapped
    )

    # Validation contexte
    refusal = _validate_audit_context(
        project_address=project_address,
        project_phase=eff_phase,
        auditor_name=auditor_name,
        # On passe la valeur **utilisateur brute** (pas la description du
        # snapshot) : la description est demandée puis validée/corrigée par
        # l'utilisateur, avec la description maquette proposée en suggestion.
        project_description=project_description,
        require_description=True,
        suggested_address=sugg_address,
        suggested_description=sugg_description,
        suggested_phase=suggested_phase,
        detected_phase_raw=detected_raw,
        require_phase_confirmation=require_phase_confirmation,
        confirm_context=confirm_context,
    )
    if refusal is not None:
        return refusal

    raw = Path(output_path) if output_path else _default_output_paths()[0]
    target = safe_export_path(raw, overwrite=overwrite)

    # Construire le contexte enrichi avec les inputs utilisateur. La
    # description utilisateur (si fournie) écrase la description déduite ;
    # sinon ``base_ctx`` conserve la description extraite du snapshot.
    base_ctx = build_report_context(_State.result)
    ctx = merge_user_context(
        base_ctx,
        project_address=project_address,
        project_phase=eff_phase,
        auditor_name=auditor_name,
        project_description=project_description,
    )

    # Si auditor_name fourni, on l'utilise comme display ; sinon legacy
    # param ``auditor`` reste fonctionnel (write_word_report gère la
    # priorité contexte → kwargs).
    display_auditor = auditor_name or auditor

    written = write_word_report(
        _State.result,
        target,
        auditor=display_auditor,
        xlsx_annex_path=xlsx_annex_path,
        context=ctx,
    )
    return {"path": str(written), "size_bytes": written.stat().st_size}


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


# Note : ``doe_enrich_model`` est désormais un wrapper de dépréciation
# défini dans ``tools_legacy.py`` (legacy_execute=False par défaut →
# prépare un plan, ne pousse rien sans confirm). Voir
# ``docs/migration_prepare_apply.md`` pour le workflow recommandé.


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
    # Refus en amont du token en paramètre sur transport réseau (même
    # garde que ``set_active_model``, dupliquée pour fail-fast clair
    # avant tout calcul). Sans cette ligne, le refus arriverait au
    # milieu du pipeline (étape 2), masquant l'origine de l'erreur.
    if access_token:
        ensure_access_token_param_allowed()

    # P1 — anti-contamination multi-modèle. Si l'appelant fournit une cible
    # explicite (URL viewer ou IDs), on l'active **et on charge SON snapshot**
    # (lecture seule) *avant* de calculer les suggestions de contexte (phase /
    # adresse / description). Sinon, dans une session multi-modèle, ces
    # suggestions seraient tirées du snapshot du modèle précédemment chargé :
    # un ``full_audit(bimdata_url=<B>)`` proposerait l'adresse/description/phase
    # du modèle A resté en session. On active donc la cible en tête de fonction.
    explicit_target = any(v is not None for v in (cloud_id, project_id, model_id, bimdata_url))
    target_loaded = False
    if explicit_target:
        set_active_model(
            cloud_id=cloud_id,
            project_id=project_id,
            model_id=model_id,
            bimdata_url=bimdata_url,
            # Phase provisoire : ``_State.phase`` est ré-aligné plus bas sur la
            # phase effective résolue depuis le **nouveau** snapshot.
            phase=(phase.strip() if isinstance(phase, str) and phase.strip() else "PRO"),
            access_token=access_token,
        )
        _State.snapshot = extract_snapshot(_State.client)
        target_loaded = True

    # Phase — question **unique**, phase confirmée = unique source de
    # vérité (audit + rapport Word + pack AVP). Règle :
    #
    #   - ``phase`` passé explicitement (non vide) → choix de l'appelant,
    #     source de vérité, pas de re-confirmation ;
    #   - cible explicite fraîchement chargée → phase **détectée dans son
    #     IFC** (pas ``_State.phase``, provisoire depuis l'activation ci-dessus) ;
    #   - sinon, candidat = ``_State.phase`` (posée par un
    #     ``set_active_model`` précédent) ou, à défaut, la phase détectée
    #     dans l'IFC (mappée depuis un jalon loi MOP si besoin) ;
    #   - la confirmation explicite est **exigée** dès que l'appelant n'a
    #     pas passé de phase (``require_phase_confirmation``) : on propose
    #     le candidat et on demande validation (``confirm_context=True``
    #     court-circuite).
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
    # Proposition affichée dans la question : candidat effectif, sinon la
    # phase détectée mappée.
    suggested_phase = (
        effective_phase
        if effective_phase and effective_phase.upper() in _VALID_PHASES
        else detected_mapped
    )

    # Suggestions pour le dialogue de contexte, best-effort depuis le
    # snapshot **actif**. Deux cas garantissent qu'il s'agit bien du modèle
    # ciblé, jamais d'un précédent :
    #   - cible explicite → snapshot chargé en tête de fonction (fix P1) ;
    #   - sinon → snapshot déjà en session (``set_active_model`` →
    #     ``verify_active_model`` → ``full_audit``).
    # On ne force pas d'extraction supplémentaire ici : à froid (aucun
    # snapshot), la validation reste bon marché et sans accès modèle.
    # Snapshot présent → on propose l'adresse (IfcPostalAddress) + la
    # description et on exige la description ; snapshot absent → question
    # sans suggestion et description non requise.
    sugg_address = _snapshot_address_suggestion()
    sugg_description = _snapshot_description()

    # Validation contexte projet AVANT toute exécution coûteuse :
    # adresse + phase + nom auditeur (+ description si un snapshot est
    # disponible) sont obligatoires pour un livrable AMO BIM exploitable.
    # Si une info manque et ``confirm_context`` n'est pas True, on refuse
    # en posant des questions structurées, avec ``suggested_value`` quand
    # la maquette permet de proposer une valeur. La description projet est
    # **demandée** (valeur utilisateur brute) puis validée/corrigée, la
    # description maquette n'étant qu'une suggestion.
    context_refusal = _validate_audit_context(
        project_address=project_address,
        project_phase=effective_phase,
        auditor_name=auditor_name,
        project_description=project_description,
        require_description=_State.snapshot is not None,
        suggested_address=sugg_address,
        suggested_description=sugg_description,
        suggested_phase=suggested_phase,
        detected_phase_raw=detected_raw,
        require_phase_confirmation=require_phase_confirmation,
        confirm_context=confirm_context,
    )
    if context_refusal is not None:
        return context_refusal

    # Après validation/confirmation : filet de sécurité pour l'énumération
    # (``confirm_context=True`` peut passer sans phase déterminée à froid).
    effective_phase = effective_phase or "PRO"

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

    # 2. Cible — politique de préservation :
    #   - cible explicite (URL/IDs) → déjà activée + snapshot chargé en tête
    #     de fonction (``target_loaded``, fix P1) : on aligne seulement la
    #     phase de session sur la phase effective résolue ;
    #   - sinon, si une cible est déjà active en session (``_State.client``),
    #     on la **garde** (et on aligne la phase) ;
    #   - sinon (pas de client en session, pas d'ID fourni) →
    #     fallback ``.env`` via ``set_active_model``.
    #
    # Sans ce garde, un appel ``full_audit()`` (ou avec
    # ``model_id=None``) **écrasait silencieusement** la cible posée par
    # un précédent ``set_active_model`` + ``verify_active_model`` avec
    # le ``BIMDATA_MODEL_ID`` du ``.env``. Risque concret : l'auditeur
    # vérifie la bonne maquette puis se fait re-router sur l'ancienne
    # cible de l'environnement.
    # ``effective_phase`` est résolu en BIMPhase ici pour pouvoir
    # l'aligner sur ``_State.phase`` ci-dessous. On passe en majuscules par
    # robustesse vs entrée utilisateur.
    effective_bim_phase = BIMPhase(effective_phase.upper())

    if target_loaded:
        # Cible explicite déjà activée + snapshot fraîchement chargé plus haut.
        # L'activation initiale a posé une phase provisoire : on la réaligne
        # sur la phase effective (détectée ou explicite) pour que l'audit et le
        # rapport partagent la même source de vérité.
        _State.phase = effective_bim_phase
    elif _State.client is None:
        # Pas de cible fournie ni de session active → fallback ``.env``.
        set_active_model(
            cloud_id=cloud_id,
            project_id=project_id,
            model_id=model_id,
            bimdata_url=bimdata_url,
            phase=effective_phase,
            access_token=access_token,
        )
    else:
        # Cible préservée. On ne réinitialise ni le client BIMData, ni
        # le ``_State.snapshot`` (déjà chargé par verify_active_model).
        # En revanche, on **aligne ``_State.phase`` sur
        # ``effective_bim_phase``** pour garder l'état session
        # cohérent. Sans ce réalignement, un appel
        # ``full_audit(phase="DCE", model_id=None)`` après
        # ``set_active_model(phase="AVP")`` ferait tourner
        # ``run_audit`` sur AVP (qui lit ``_State.phase``) tandis que
        # le rapport serait étiqueté DCE — divergence audit/rapport
        # silencieuse.
        _State.phase = effective_bim_phase

    # 3. Snapshot — refresh forcé par défaut pour éviter d'auditer une
    # version périmée en cache. Sauté pour une cible explicite déjà chargée
    # fraîchement en tête de fonction (``target_loaded``) — inutile de
    # re-extraire ce qu'on vient d'obtenir sans cache.
    if not target_loaded and (force_refresh_snapshot or _State.snapshot is None):
        _State.snapshot = extract_snapshot(_State.client)

    # 3 bis. Garde-fou d'identité : si l'auditeur a déclaré la maquette
    # attendue, on bloque AVANT toute génération de livrable.
    if expected_model_name:
        actual_name = (_State.snapshot.model or {}).get("name")
        if not model_matches_expected(actual_name, expected_model_name):
            actual_id = (_State.snapshot.model or {}).get("id") or _State.model_id
            raise ValueError(
                f"Modèle actif inattendu : attendu '{expected_model_name}', "
                f"reçu '{actual_name}' (model_id={actual_id}). Audit interrompu."
            )

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

    # Contexte enrichi : extraction auto + inputs utilisateur (adresse,
    # phase, auditeur). Garantit que les valeurs fournies par l'AMO
    # apparaissent comme données fiables (pas "déduit — à confirmer").
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


# ── Enregistrement des tools des modules dédiés ──────────────────────────
#
# L'import déclenche l'exécution des décorateurs ``@mcp.tool()`` sur les
# fonctions définies dans chaque module. Ordre : les query/actions
# d'abord, puis les wrappers legacy (qui dépendent des planners), puis
# les aliases (qui re-dispatchent vers tools_actions).
#
# Cette indirection permet de garder server.py < 1 000 lignes tout en
# préservant le registre FastMCP unique.

from . import aliases  # noqa: E402, F401, I001
from . import tools_actions  # noqa: E402, F401
from . import tools_legacy  # noqa: E402, F401
from . import tools_query  # noqa: E402, F401

# Re-export des tools déplacés pour préserver l'API publique :
# ``from audit_bim.mcp import server; server.prepare_bcf_topics(...)``
# reste valide (utilisé par les tests et certains scripts).
from .aliases import (  # noqa: E402, F401
    apply_bcf_plan,
    apply_classification_corrections,
    apply_doe_enrichment as apply_doe_enrichment_alias,
    apply_smartviews_plan,
    prepare_bcf_from_findings,
    prepare_classification_corrections,
    prepare_doe_enrichment_from_file,
    prepare_smartviews_from_findings,
)
from .tools_actions import (  # noqa: E402, F401
    apply_bcf_topics,
    apply_classification_update_plan,
    apply_doe_enrichment_plan,
    apply_smart_views_plan,
    audit_trail,
    extract_doe_records,
    list_write_plans,
    match_doe_to_ifc,
    prepare_bcf_topics,
    prepare_classification_update_plan,
    prepare_doe_enrichment_plan,
    prepare_smart_view_from_filter_plan,
    prepare_smart_views_plan,
    update_suggestion_status,
)
from .tools_legacy import (  # noqa: E402, F401
    apply_suggested_classifications,
    create_bcf_topics,
    create_smart_views,
    doe_enrich_model,
    suggest_classifications,
)
from .tools_query import (  # noqa: E402, F401
    filter_bim_objects,
    get_object_detail,
    list_audit_findings,
    list_classification_suggestions,
    list_query_presets,
    query_bim_data,
    query_bim_preset,
    show_filtered_objects_in_viewer,
)


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
