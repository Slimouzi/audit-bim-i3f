"""Tools MCP — cible/contexte/configuration de session (PR2 §2b)."""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from .. import config
from ..extraction.client import BIMDataAuthError, BIMDataClient
from ..extraction.computed_quantities import (
    json_digest,
    load_computed_quantities,
    merge_into_snapshot,
)
from ..extraction.ifc_download import download_model_ifc as download_ifc
from ..extraction.model_data import extract_snapshot
from ..extraction.snapshot_cache import cached_extract_snapshot
from ..requirements.catalog import build_catalog, catalog_usable
from ..requirements.models import BIMPhase
from ..safe_paths import safe_export_dir, safe_input_path
from ..security.redaction import redact_secrets
from .app import mcp
from .model_identity import (
    model_matches_expected,
    parse_bimdata_viewer_url,
    resolve_bimdata_target,
)
from .phase import (
    _detect_snapshot_phase,
    _phase_question_dict,
)
from .security import ensure_access_token_param_allowed
from .security import scrub as _scrub
from .session import _State

_server_logger = logging.getLogger("audit_bim.mcp.tools_session")

_MODEL_STATUS_LABELS = {
    "C": "Completed",
    "D": "Deleted",
    "P": "Pending",
    "W": "Waiting",
    "I": "In Process",
    "E": "Error",
}


def _snapshot_diagnostics(snapshot) -> dict:
    """Expose les signaux de sante du snapshot sans bloquer la connexion."""
    model = snapshot.model or {}
    status = model.get("status")
    errors = list(getattr(snapshot, "extraction_errors", None) or [])
    label = _MODEL_STATUS_LABELS.get(status) if status else None

    health = "ok"
    warning = None
    if not model:
        health = "empty_model"
        warning = (
            "Snapshot sans metadonnees model : cible/auth potentiellement invalides "
            "ou extraction BIMData incomplete."
        )
    elif status and status != "C":
        health = "model_not_completed"
        warning = (
            f"Modele BIMData status={status!r}"
            + (f" ({label})" if label else "")
            + " : les donnees d'elements peuvent etre absentes ou instables."
        )
    elif errors:
        health = "partial"
        warning = "Snapshot partiel : une ou plusieurs routes BIMData ont echoue."
    elif not snapshot.elements:
        health = "empty_elements"
        warning = "Snapshot sans elements bruts : verifier que la maquette est bien exploitable."

    return {
        "snapshot_health": health,
        "snapshot_warning": warning,
        "model_status": status,
        "model_status_label": label,
        "n_extraction_errors": len(errors),
        "extraction_errors": errors,
    }


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
                    "Si URL : parse_bimdata_target(url) → IDs, puis "
                    "set_active_model(cloud_id=..., project_id=..., model_id=..., phase=...). "
                    "Les valeurs du .env servent de fallback."
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
    phase: str = "PRO",
    classification_system: str | None = None,
    access_token: str | None = None,
) -> dict:
    """Cible la maquette BIMData par **IDs explicites** + la phase BIM à auditer.

    Le runtime cible **toujours** BIMData par ``cloud_id`` / ``project_id`` /
    ``model_id``. Une **URL viewer n'est pas acceptée ici** : appelle d'abord
    ``parse_bimdata_target(url)`` pour extraire les IDs, puis passe-les.

    **Cette fonction ne prouve PAS l'accès BIMData** — elle ne fait que *configurer*
    la cible et l'auth (clé serveur). L'autorisation réelle n'est confirmée qu'en
    appelant ``check_bimdata_access`` (qui interroge ``get_project``).

    .. warning::
       ``access_token`` reste **déconseillé** : les paramètres MCP peuvent transiter
       dans des logs client / traces d'agent. Préférer la config **serveur**
       (``BIMDATA_API_KEY``, ou ``BIMDATA_CLIENT_ID``+``…_SECRET``). Le token en
       paramètre est refusé par défaut en transport réseau.

    Args:
        cloud_id, project_id, model_id: **IDs numériques** BIMData (fallback ``.env``).
        phase: APS | AVP | PRO | DCE | EXE | DOE | GESTION (défaut PRO).
        classification_system: ``UniFormat II`` (défaut) | ``Omniclass`` | ``CCS`` | ``3F``.
        access_token: Bearer token (déconseillé, local/dev uniquement).
    """
    from ..classifier import get_system

    cloud_id, project_id, model_id = resolve_bimdata_target(
        cloud_id=cloud_id,
        project_id=project_id,
        model_id=model_id,
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
        # Cible + auth **configurées**, PAS prouvées. L'accès BIMData réel n'est
        # confirmé que par `check_bimdata_access` (get_project réussit).
        "auth": "configured",
        "auth_status": "configured",
        "note": "Auth configurée mais non prouvée — valider l'accès via check_bimdata_access.",
    }


@mcp.tool()
def parse_bimdata_target(url: str) -> dict:
    """Extrait ``cloud_id`` / ``project_id`` / ``model_id`` d'une **URL viewer** BIMData.

    À appeler **avant** ``set_active_model`` quand l'utilisateur fournit une URL
    (``https://platform.bimdata.io/spaces/<cloud>/projects/<project>/viewer/<model>``) :
    le runtime cible toujours BIMData par IDs explicites, jamais par URL. Ne touche
    à aucun état de session — c'est un simple parseur.
    """
    cloud_id, project_id, model_id = parse_bimdata_viewer_url(url)
    return {"cloud_id": cloud_id, "project_id": project_id, "model_id": model_id}


def _active_auth() -> dict:
    """Mode d'auth **effectif** du processus MCP, dans l'ordre de précédence de
    ``bimdata_read`` (access_token → api_key → OAuth2 client_credentials).

    La provenance est lue depuis la **config serveur** (``config.*`` / ``.env``),
    *pas* depuis l'instance client : le flow OAuth2 écrit ``self.access_token``
    **dès la construction** du client (``BIMDataClient.__init__`` appelle
    ``_auth_headers`` qui, en mode client_credentials, acquiert et stocke un
    jeton). Lire l'attribut ferait donc passer OAuth2 pour un Bearer configuré.
    Les ``config.*`` sont immuables → distinguent proprement un jeton *configuré*
    d'un jeton *dérivé*. On ne renvoie jamais la valeur des secrets, seulement
    leur *provenance*.
    """
    if config.ACCESS_TOKEN:
        return {"auth_source": "BIMDATA_ACCESS_TOKEN", "auth_scheme": "Bearer"}
    if config.API_KEY:
        return {"auth_source": "BIMDATA_API_KEY", "auth_scheme": "ApiKey"}
    if config.CLIENT_ID and config.CLIENT_SECRET:
        return {
            "auth_source": "BIMDATA_CLIENT_ID+SECRET",
            "auth_scheme": "Bearer (OAuth2 client_credentials)",
        }
    return {"auth_source": None, "auth_scheme": None}


@mcp.tool()
def check_bimdata_access() -> dict:
    """Smoke test **cible + auth** : prouve l'accès BIMData réel (sans cache).

    ``set_active_model`` ne fait que *configurer* l'auth ; ce tool la **prouve** en
    lisant ``get_project`` puis ``get_model`` en direct. À lancer juste après
    ``set_active_model``, avant l'extraction. Rapporte aussi le **mode d'auth
    effectif** (``auth_source`` / ``auth_scheme``) — sans jamais divulguer la
    valeur des secrets — pour la sonde de vérification de déploiement (ex. attendu
    ``auth_source: BIMDATA_API_KEY``, ``auth_scheme: ApiKey``).

    Returns:
        Succès → ``{ok: True, cloud_id, project_id, model_id, project_name,
        model_name, auth_source, auth_scheme}``.
        Échec → ``{ok: False, …, auth_source, auth_scheme, error: <diagnostic>}``
        (401 = credential du processus MCP rejetée par BIMData pour cette cible ;
        403 = sans droits ; 404 = cible introuvable).
    """
    _State.ensure_client()
    ids = {
        "cloud_id": _State.cloud_id,
        "project_id": _State.project_id,
        "model_id": _State.model_id,
    }
    auth = _active_auth()
    try:
        project = _State.client.get_project()
        model = _State.client.get_model()
    except BIMDataAuthError as exc:
        # bimdata_read lève ``BIMDataAuthError`` (PermissionError) pour 401/403,
        # AVANT ``raise_for_status`` — ce n'est donc PAS une ``requests.HTTPError``.
        # Sans cette branche, un 401 remonterait brut (« BIMData 401 on … »), sans
        # ``auth_source``/``auth_scheme``, masquant le vrai diagnostic (clé morte).
        is_403 = "403" in str(exc)
        if is_403:
            diagnostic = "Authentifié mais sans droits sur ce cloud/projet (HTTP 403)."
        else:
            diagnostic = (
                f"BIMData a rejeté la credential du processus MCP (HTTP 401, schéma "
                f"{auth['auth_scheme']}, source {auth['auth_source']}) — causes "
                "typiques : clé API périmée/révoquée, ou valeur mal résolue "
                "(ex. ${BIMDATA_API_KEY} non substitué par le client). Vérifie / "
                "régénère BIMDATA_API_KEY."
            )
        return {"ok": False, **ids, **auth, "error": diagnostic}
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        diagnostic = {
            404: "Cible introuvable (HTTP 404) — vérifie cloud_id / project_id / model_id.",
        }.get(status, f"Accès BIMData refusé (HTTP {status}).")
        return {"ok": False, **ids, **auth, "error": diagnostic}
    except requests.RequestException as exc:
        return {
            "ok": False,
            **ids,
            **auth,
            "error": f"Erreur réseau BIMData : {redact_secrets(str(exc))}",
        }
    return {
        "ok": True,
        **ids,
        "project_name": (project or {}).get("name"),
        "model_name": (model or {}).get("name"),
        **auth,
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
def download_model_ifc(cache_dir: str = ".audit_cache", overwrite: bool = False) -> dict:
    """Télécharge le **fichier .ifc** du modèle actif dans un cache local.

    Lecture seule (aucune écriture BIMData). Récupère l'URL signée via
    ``get_model()`` (champ ``document.file``) et **streame** le corps sur disque
    (jamais chargé en RAM), sous un plafond ``AUDIT_MAX_IFC_MB`` (défaut 500 Mo).
    Le fichier est mis en cache keyé ``model_id`` + ``modified_date`` (comme le
    cache snapshot) dans ``<cache_dir>/ifc/``.

    Sert notamment à fournir le ``.ifc`` au MCP ``ifc-geometry``
    (``complete_ifc_base_quantities``) pour calculer géométriquement les
    ``BaseQuantities`` absentes de la maquette.

    Note déploiement : le chemin retourné est sous ``AUDIT_OUTPUT_DIR`` (sandbox
    d'écriture d'audit-bim). Pour qu'``ifc-geometry`` le lise, son
    ``AUDIT_INPUT_DIR`` doit couvrir cet emplacement (ou pointer le même volume).

    Args:
        cache_dir: dossier de cache (sandboxé sous ``AUDIT_OUTPUT_DIR``).
        overwrite: force le re-téléchargement même si le cache est présent.

    Returns:
        ``{path, from_cache, size_bytes, model_id, modified_date}``.
    """
    _State.ensure_client()
    safe_dir = safe_export_dir(cache_dir)
    res = download_ifc(
        _State.client,
        cache_dir=str(safe_dir),
        max_mb=config.AUDIT_MAX_IFC_MB,
        overwrite=overwrite,
    )
    # Mémorisé en session : c'est la corrélation la plus sûre entre le modèle
    # actif et un fichier .ifc pour le calcul géométrique.
    _State.ifc_path = res.get("path")
    return res


@mcp.tool()
def extract_model_snapshot(
    use_cache: bool = True,
    cache_dir: str = ".audit_cache",
    compute_missing_quantities: bool = False,
    computed_quantities_json: str | None = None,
) -> dict:
    """Récupère le snapshot du modèle (espaces, zones, éléments…) depuis BIMData.

    Args:
        use_cache: Si ``True`` (défaut), utilise le cache local : un
            ``get_model()`` léger sert à comparer ``modified_date`` ;
            si le cache matche, lecture instantanée du fichier. Sinon
            extraction complète (5-10s) + écriture du cache.
        cache_dir: Dossier du cache local. Défaut ``.audit_cache``
            (relatif au cwd).
        compute_missing_quantities: si ``True``, **fusionne** les BaseQuantities
            calculées géométriquement (JSON ``computed_base_quantities/v1`` du
            MCP ``ifc-geometry``) dans le snapshot, en **gap-only** (ne comble que
            les vides, ne remplace **jamais** une valeur BIMData native). La
            provenance est conservée par valeur (``computed_base_quantities`` sur
            l'élément, exposée par ``get_object_detail``). Exige
            ``computed_quantities_json``. ``False`` (défaut) → comportement
            historique **inchangé**.
        computed_quantities_json: chemin du JSON de quantités calculées (sandbox
            lecture ``safe_input_path``). Obligatoire si
            ``compute_missing_quantities=True``.

    Returns:
        Résumé du snapshot + ``from_cache: bool``. Si ``compute_missing_quantities``,
        un bloc ``computed_quantities`` (schéma, ``json_sha``, clé de cache dédiée,
        couverture : mergés / vides conservés / ignorés / uuid inconnus).
    """
    _State.ensure_client()
    # L'extraction est une **lecture** : elle ne doit pas dépendre d'un dossier de
    # sortie inscriptible. Le cache (optionnel) est sandboxé sous AUDIT_OUTPUT_DIR ;
    # si cette racine est en **lecture seule** (ex. volume /out non monté en
    # écriture), on dégrade en extraction sans cache au lieu de planter. On ne
    # touche même pas la racine quand ``use_cache=False``.
    hit = False
    if use_cache:
        try:
            safe_dir = safe_export_dir(cache_dir)
            _State.snapshot, hit = cached_extract_snapshot(
                _State.client, cache_dir=str(safe_dir), use_cache=True
            )
        except OSError:
            _server_logger.warning(
                "cache snapshot indisponible (racine d'export en lecture seule ?) "
                "— extraction sans cache."
            )
            _State.snapshot = extract_snapshot(_State.client)
    else:
        _State.snapshot = extract_snapshot(_State.client)

    # Fusion des quantités calculées (gap-only) — appliquée **après** le cache
    # snapshot (qui ne stocke QUE le brut BIMData) : un appel standard ne voit
    # donc jamais un snapshot enrichi, et inversement. La fusion est ré-appliquée
    # à chaque appel sur un snapshot brut frais → toujours cohérente avec le JSON
    # courant (invalidation naturelle quand le JSON change).
    computed_block = None
    if compute_missing_quantities:
        computed_block = _merge_computed_quantities(computed_quantities_json)

    summary = _State.snapshot.summary()
    summary.update(_snapshot_diagnostics(_State.snapshot))
    summary["from_cache"] = hit
    if computed_block is not None:
        summary["computed_quantities"] = computed_block
    return summary


def _merge_computed_quantities(computed_quantities_json: str | None) -> dict:
    """Valide + fusionne le JSON de quantités calculées dans ``_State.snapshot``.

    Renvoie le bloc ``computed_quantities`` (schéma, json_sha, cache_key dédiée,
    couverture). Lève ``ValueError`` clair si le JSON est absent / invalide.
    """
    if not computed_quantities_json:
        raise ValueError(
            "compute_missing_quantities=True exige `computed_quantities_json` "
            "(JSON `computed_base_quantities/v1` produit par le MCP ifc-geometry "
            "via export_computed_base_quantities)."
        )
    safe_json = safe_input_path(computed_quantities_json, allowed_extensions={".json"})
    doc = load_computed_quantities(safe_json)  # valide le schéma (sinon ValueError)
    coverage = merge_into_snapshot(_State.snapshot, doc)
    # Couverture stockée sur le snapshot → reprise par le rapport consolidé (.docx).
    _State.snapshot.computed_coverage = dict(coverage)
    sha = json_digest(safe_json)
    model = _State.snapshot.model or {}
    # Clé de cache dédiée : snapshot key + hash du JSON + flag compute. Garantit
    # qu'un résultat « compute » n'est pas confondu avec un résultat standard, et
    # change dès que le JSON change.
    cache_key = ":".join(
        str(x)
        for x in (
            _State.cloud_id,
            _State.project_id,
            _State.model_id,
            model.get("modified_date") or "",
            sha,
            "compute",
        )
    )
    return {
        "schema": doc.get("schema"),
        "json": Path(safe_json).name,
        "json_sha": sha,
        "cache_key": cache_key,
        **coverage,
    }


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
        model_id, modified_date, from_cache, message, snapshot_health, ...}``.
        Quand ``ok=False`` l'audit ne doit pas être lancé ; cet outil ne
        modifie jamais ``_State.result``. Les champs ``snapshot_health`` /
        ``model_status`` sont informatifs et ne bloquent pas la connexion.
    """
    _State.ensure_client()
    expected = (expected_model_name or "").strip()
    if not expected:
        raise ValueError("expected_model_name est requis et ne peut pas être vide.")

    from_cache: bool | None
    if refresh_snapshot:
        from_cache = False
        if use_cache:
            # Cache sandboxé sous AUDIT_OUTPUT_DIR ; dégradation en lecture seule
            # (racine non inscriptible) → extraction sans cache plutôt que crash.
            try:
                safe_dir = safe_export_dir(".audit_cache")
                _State.snapshot, from_cache = cached_extract_snapshot(
                    _State.client, cache_dir=str(safe_dir), use_cache=True
                )
            except OSError:
                _server_logger.warning(
                    "cache snapshot indisponible (racine d'export en lecture seule ?)"
                    " — extraction sans cache."
                )
                _State.snapshot = extract_snapshot(_State.client)
        else:
            _State.snapshot = extract_snapshot(_State.client)
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
        **_snapshot_diagnostics(_State.snapshot),
    }
