"""Tools MCP — cible/contexte/configuration de session (PR2 §2b)."""

from __future__ import annotations

import logging
from pathlib import Path

from .. import config
from ..extraction.client import BIMDataClient
from ..extraction.model_data import assert_snapshot_usable, extract_snapshot
from ..extraction.snapshot_cache import cached_extract_snapshot
from ..requirements.catalog import build_catalog, catalog_usable
from ..requirements.models import BIMPhase
from ..safe_paths import safe_export_dir, safe_input_path
from .app import mcp
from .model_identity import model_matches_expected, resolve_bimdata_target
from .phase import (
    _detect_snapshot_phase,
    _phase_question_dict,
)
from .security import ensure_access_token_param_allowed
from .security import scrub as _scrub
from .session import _State

_server_logger = logging.getLogger("audit_bim.mcp.tools_session")


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

    # Lot 5 — un changement de documents invalide le catalogue déjà construit :
    # sinon un audit ultérieur (`get_catalog_properties`, règles) tournerait sur
    # l'ANCIEN référentiel. `full_audit` reconstruit déjà via `_fa_prepare_catalog` ;
    # on aligne le reste du chemin MCP.
    if any(v is not None for v in (cch_pdf, data_spec_xlsx, naming_spec_xlsx)):
        _State.catalog = None

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
    summary = _State.catalog.summary()
    # E6 — avertissement structuré si le catalogue est inexploitable : un audit
    # ultérieur rendrait un verdict faussement « conforme » (documents illisibles).
    ok, reason = catalog_usable(_State.catalog)
    if not ok:
        summary["warning"] = reason
    return summary


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
    # E8 — le store de suggestions est construit sur les UUIDs du modèle précédent :
    # sans invalidation, un plan de classifications scellé sur la NOUVELLE cible
    # porterait les UUIDs de l'ANCIENNE → écritures parasites sur le mauvais modèle
    # (validate_target ne voit que la cible, pas la provenance des items).
    _State.suggestion_store = None
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
    # C2 — refuse un snapshot vide (extraction échouée) ou partiel (route en
    # échec) : sinon les tools d'audit dérouleraient sur du vide/tronqué.
    assert_snapshot_usable(_State.snapshot)
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
            # Lot 5 — sandboxer le dossier de cache (comme extract_model_snapshot) :
            # sinon `.audit_cache` s'écrit sous le CWD, hors AUDIT_OUTPUT_DIR.
            safe_dir = safe_export_dir(".audit_cache")
            _State.snapshot, hit = cached_extract_snapshot(
                _State.client, cache_dir=str(safe_dir), use_cache=True
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
