"""Outils MCP du profil BIM in Motion — cible, identité, instantané.

Trois outils, écrits contre les briques neutres du dépôt. Aucun n'est copié
depuis I3F : les équivalents I3F portent de la phase BIM, un système de
classification et un catalogue d'exigences, qui appartiennent au référentiel
d'I3F et non à un socle.

C'est aussi ce qui rend ce profil utile au-delà de lui-même : il donne un
second consommateur réel aux briques partagées, donc un moyen de mesurer ce qui
est vraiment générique — plutôt que de l'inférer d'un seul appelant.
"""

from __future__ import annotations

import logging

from ... import config
from ...extraction.client import BIMDataClient
from ...extraction.model_data import extract_snapshot
from ...extraction.snapshot_cache import cached_extract_snapshot
from ...mcp.app import mcp
from ...mcp.model_identity import model_matches_expected, resolve_bimdata_target
from ...mcp.security import ensure_access_token_param_allowed
from ...mcp.security import scrub as _scrub
from ...mcp.session import _State
from ...safe_paths import safe_export_dir

logger = logging.getLogger("audit_bim.profiles.bim_in_motion.tools_session")

__all__ = ["set_active_target", "verify_active_target", "extract_model_snapshot"]

#: Message d'absence de cible. Écrit ici plutôt que repris de
#: ``_State.ensure_client()``, dont le texte nomme ``set_active_model`` — un
#: outil d'I3F, absent de ce profil. Renvoyer un utilisateur vers un outil
#: inexistant est une impasse silencieuse.
_NO_TARGET = "Aucune maquette active — appelle d'abord `set_active_target`."


def _require_target() -> None:
    if _State.client is None:
        raise RuntimeError(_NO_TARGET)


@mcp.tool()
def set_active_target(
    cloud_id: str | None = None,
    project_id: str | None = None,
    model_id: str | None = None,
    access_token: str | None = None,
) -> dict:
    """Désigne la maquette BIMData à examiner.

    Configure la cible et l'authentification ; **ne prouve pas** l'accès. Une
    erreur d'identifiant ne se manifestera qu'à la première lecture.

    Args:
        cloud_id, project_id, model_id: identifiants numériques BIMData. À
            défaut, les valeurs de configuration du serveur sont utilisées.
        access_token: jeton porteur. **Déconseillé** : un paramètre MCP peut
            transiter dans les journaux d'un client ou les traces d'un agent.
            Préférer la configuration serveur. Refusé par défaut en transport
            réseau.

    Returns:
        La cible retenue, et ``auth`` à ``"configured"`` — jamais ``"proved"``.
    """
    cloud_id, project_id, model_id = resolve_bimdata_target(
        cloud_id=cloud_id,
        project_id=project_id,
        model_id=model_id,
    )
    _State.cloud_id = cloud_id or config.CLOUD_ID
    _State.project_id = project_id or config.PROJECT_ID
    _State.model_id = model_id or config.MODEL_ID

    if access_token:
        ensure_access_token_param_allowed()
        logger.info(
            "set_active_target cloud=%s project=%s model=%s token=%s",
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
    # Tout ce qui a été lu appartient à la cible précédente. Le garder
    # produirait une description cohérente d'un autre bâtiment.
    _State.snapshot = None
    _State.ifc_path = None

    return {
        "cloud_id": _State.cloud_id,
        "project_id": _State.project_id,
        "model_id": _State.model_id,
        "auth": "configured",
        "note": "Cible configurée, accès non prouvé — la première lecture le confirmera.",
    }


@mcp.tool()
def verify_active_target(expected_model_name: str, use_cache: bool = False) -> dict:
    """Confirme que la maquette active est bien celle attendue.

    Le risque visé est humain, pas technique : un identifiant copié depuis un
    projet voisin donne un résultat parfaitement cohérent, sur la mauvaise
    maquette. Rien dans les données ne le signale.

    Args:
        expected_model_name: fragment attendu dans le nom du modèle. La
            comparaison ignore la casse, les accents et les espaces multiples.
        use_cache: ``False`` par défaut — un contrôle d'identité qui lirait le
            cache pourrait confirmer une maquette d'après une lecture antérieure.

    Returns:
        ``{ok, expected_model_name, model_name, model_id, from_cache}``.
        ``ok=False`` doit interrompre le travail en cours.
    """
    _require_target()
    expected = (expected_model_name or "").strip()
    if not expected:
        raise ValueError("expected_model_name est requis et ne peut pas être vide.")

    snapshot, from_cache = _load_snapshot(use_cache=use_cache, cache_dir=".audit_cache")
    _State.snapshot = snapshot
    model = snapshot.model or {}
    name = model.get("name")

    return {
        "ok": model_matches_expected(name, expected),
        "expected_model_name": expected,
        "model_name": name,
        "model_id": _State.model_id,
        "from_cache": from_cache,
    }


@mcp.tool()
def extract_model_snapshot(use_cache: bool = True, cache_dir: str = ".audit_cache") -> dict:
    """Lit un instantané de la maquette active (espaces, étages, éléments).

    Args:
        use_cache: réutilise une lecture antérieure si le modèle n'a pas changé.
        cache_dir: dossier de cache, confiné sous la racine d'export du serveur.

    Returns:
        Un résumé du contenu et ``from_cache``.
    """
    _require_target()
    snapshot, from_cache = _load_snapshot(use_cache=use_cache, cache_dir=cache_dir)
    _State.snapshot = snapshot
    model = snapshot.model or {}

    return {
        "model_name": model.get("name"),
        "model_id": _State.model_id,
        "spaces": len(getattr(snapshot, "spaces", None) or []),
        "storeys": len(getattr(snapshot, "storeys", None) or []),
        "elements": len(getattr(snapshot, "elements", None) or []),
        "from_cache": from_cache,
    }


def _load_snapshot(*, use_cache: bool, cache_dir: str):
    """Lecture d'instantané, avec repli si la racine d'export n'est pas écrivable.

    Une lecture ne doit pas dépendre d'un dossier inscriptible : sur un volume
    monté en lecture seule, l'absence de cache dégrade la performance, elle ne
    doit pas empêcher de travailler.
    """
    if use_cache:
        try:
            safe_dir = safe_export_dir(cache_dir)
            return cached_extract_snapshot(_State.client, cache_dir=str(safe_dir), use_cache=True)
        except OSError:
            logger.warning("cache indisponible (racine d'export en lecture seule ?) — sans cache.")
    return extract_snapshot(_State.client), False
