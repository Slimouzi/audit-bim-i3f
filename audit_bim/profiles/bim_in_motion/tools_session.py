"""Outils MCP du profil BIM in Motion — cible, identité, instantané.

**Un seul outil reste ici.** ``verify_active_target`` et
``extract_model_snapshot`` avaient été écrits pour ce profil faute de socle qui
les porte ; E7 les a remplacés par ``audit_bim.tools_shared.session``, que les
deux profils déclarent. C'était la seule duplication dont on ait eu la preuve
qu'elle gênait un second AMO — et cette preuve, c'est ce profil qui l'a fournie.

``set_active_target`` demeure : son équivalent I3F, ``set_active_model``, porte
une phase BIM et un système de classification qui appartiennent au référentiel
d'I3F. Il n'appartient donc pas au socle, et ce profil garde le sien.
"""

from __future__ import annotations

import logging

from ... import config
from ...extraction.client import BIMDataClient
from ...mcp.app import mcp
from ...mcp.model_identity import parse_bimdata_viewer_url
from ...mcp.security import ensure_access_token_param_allowed
from ...mcp.security import scrub as _scrub
from ...mcp.session import _State

logger = logging.getLogger("audit_bim.profiles.bim_in_motion.tools_session")

__all__ = ["set_active_target"]


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
