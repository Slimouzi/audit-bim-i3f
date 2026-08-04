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
from ...extraction.snapshot_health import snapshot_diagnostics
from ...mcp.app import mcp
from ...mcp.model_identity import model_matches_expected, parse_bimdata_viewer_url
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


def _clean_id(label: str, value: str | None) -> str | None:
    """Valide un identifiant BIMData, en ne citant que des actions disponibles ici.

    ``resolve_bimdata_target`` refuse déjà les URL, mais son message renvoie vers
    ``parse_bimdata_target`` — un outil d'I3F, absent de ce profil. Envoyer un
    utilisateur vers un outil que son serveur n'expose pas est une impasse
    d'autant plus coûteuse qu'elle a l'air d'une instruction valide. Et ce
    contrôle ne portait que sur ``model_id`` : une URL passée en ``cloud_id``
    était acceptée telle quelle, produisant une cible invalide annoncée comme
    configurée.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower().startswith(("http://", "https://")):
        raise ValueError(
            f"{label} est une URL. Passe-la plutôt dans `bimdata_url`, qui en "
            f"extrait cloud_id / project_id / model_id."
        )
    if not text.isdigit():
        raise ValueError(
            f"{label} doit être un identifiant numérique BIMData (reçu {text!r}). "
            f"Depuis une URL viewer, utilise `bimdata_url`."
        )
    return text


@mcp.tool()
def set_active_target(
    cloud_id: str | None = None,
    project_id: str | None = None,
    model_id: str | None = None,
    bimdata_url: str | None = None,
    access_token: str | None = None,
) -> dict:
    """Désigne la maquette BIMData à examiner.

    Configure la cible et l'authentification ; **ne prouve pas** l'accès. Une
    erreur d'identifiant ne se manifestera qu'à la première lecture.

    Args:
        cloud_id, project_id, model_id: identifiants **numériques** BIMData. À
            défaut, les valeurs de configuration du serveur sont utilisées.
        bimdata_url: URL viewer BIMData, dont les trois identifiants sont
            extraits ici. Alternative aux trois paramètres ci-dessus, pas un
            complément : fournir les deux serait ambigu et est refusé.
        access_token: jeton porteur. **Déconseillé** : un paramètre MCP peut
            transiter dans les journaux d'un client ou les traces d'un agent.
            Préférer la configuration serveur. Refusé par défaut en transport
            réseau.

    Returns:
        La cible retenue, et ``auth`` à ``"configured"`` — jamais ``"proved"``.
    """
    if bimdata_url:
        if any((cloud_id, project_id, model_id)):
            raise ValueError(
                "Fournis soit `bimdata_url`, soit cloud_id/project_id/model_id, "
                "mais pas les deux : la cible retenue serait ambiguë."
            )
        cloud_id, project_id, model_id = parse_bimdata_viewer_url(bimdata_url)

    cloud_id = _clean_id("cloud_id", cloud_id)
    project_id = _clean_id("project_id", project_id)
    model_id = _clean_id("model_id", model_id)
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
        ``{ok, expected_model_name, model_name, model_id, from_cache}`` plus les
        diagnostics de lecture (``snapshot_health``, ``snapshot_warning``,
        ``n_extraction_errors``, ``extraction_errors``). ``ok=False`` doit
        interrompre le travail en cours — et ``snapshot_health`` dit s'il s'agit
        d'un écart de nom ou d'une lecture qui n'a pas abouti.
    """
    _require_target()
    expected = (expected_model_name or "").strip()
    if not expected:
        raise ValueError("expected_model_name est requis et ne peut pas être vide.")

    snapshot, from_cache = _load_snapshot(use_cache=use_cache, cache_dir=".audit_cache")
    _State.snapshot = snapshot
    model = snapshot.model or {}
    name = model.get("name")

    # Sans les diagnostics, une lecture qui a échoué renverrait `ok: false` avec
    # `model_name: null` — indiscernable d'un simple écart de nom. L'auditeur
    # conclurait « mauvaise maquette » là où la maquette n'a pas pu être lue.
    return {
        "ok": model_matches_expected(name, expected),
        "expected_model_name": expected,
        "model_name": name,
        "model_id": _State.model_id,
        "from_cache": from_cache,
        **snapshot_diagnostics(snapshot),
    }


@mcp.tool()
def extract_model_snapshot(use_cache: bool = True, cache_dir: str = ".audit_cache") -> dict:
    """Lit un instantané de la maquette active (espaces, étages, éléments).

    Args:
        use_cache: réutilise une lecture antérieure si le modèle n'a pas changé.
        cache_dir: dossier de cache, confiné sous la racine d'export du serveur.

    Returns:
        Un résumé du contenu, ``from_cache``, et les diagnostics de lecture
        (``snapshot_health``, ``snapshot_warning``, ``n_extraction_errors``,
        ``extraction_errors``) — sans lesquels des compteurs à zéro ne
        distingueraient pas une maquette vide d'une extraction en échec.
    """
    _require_target()
    snapshot, from_cache = _load_snapshot(use_cache=use_cache, cache_dir=cache_dir)
    _State.snapshot = snapshot
    model = snapshot.model or {}

    # Des compteurs à zéro ne disent pas s'ils décrivent une maquette vide ou
    # une extraction qui a échoué. Les diagnostics rendent les deux cas
    # distinguables — sans eux, l'outil présente une lecture ratée comme un
    # résultat.
    return {
        "model_name": model.get("name"),
        "model_id": _State.model_id,
        "spaces": len(getattr(snapshot, "spaces", None) or []),
        "storeys": len(getattr(snapshot, "storeys", None) or []),
        "elements": len(getattr(snapshot, "elements", None) or []),
        "from_cache": from_cache,
        **snapshot_diagnostics(snapshot),
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
