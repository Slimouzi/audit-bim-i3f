"""Tools MCP — cible/contexte/configuration de session (PR2 §2b)."""

from __future__ import annotations

import logging
from pathlib import Path

from ... import config
from ...extraction.client import BIMDataClient
from ...extraction.snapshot_health import snapshot_diagnostics
from ...mcp.app import mcp
from ...mcp.model_identity import (
    resolve_bimdata_target,
)
from ...mcp.phase import (
    _detect_snapshot_phase,
    _phase_question_dict,
)
from ...mcp.security import ensure_access_token_param_allowed
from ...mcp.security import scrub as _scrub
from ...mcp.session import _State
from ...requirements.catalog import build_catalog, catalog_usable
from ...requirements.models import BIMPhase
from ...safe_paths import safe_input_path

_server_logger = logging.getLogger("audit_bim.profiles.i3f.tools_session")


#: Repris du module partagé : la santé d'un snapshot ne dépend d'aucun
#: référentiel client. Nom privé conservé — les appelants d'I3F sont inchangés.
_snapshot_diagnostics = snapshot_diagnostics


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
    from ...classifier import get_system

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
    # Le .ifc rapatrié appartient au modèle PRÉCÉDENT : le garder ferait
    # calculer les quantités et l'enveloppe de l'ancienne maquette sur la
    # nouvelle cible — des surfaces d'un autre bâtiment, sans aucun signal.
    _State.ifc_path = None
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
def list_classification_systems() -> list[dict]:
    """Liste les référentiels de classification disponibles côté MCP."""
    from ...classifier import SYSTEMS

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
