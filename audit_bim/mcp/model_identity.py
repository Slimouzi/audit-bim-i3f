"""Résolution et garde-fou d'identité du modèle BIMData actif.

Avant de générer un audit, on veut s'assurer que la maquette
effectivement chargée côté serveur correspond bien à celle attendue par
l'auditeur. Un risque concret : ``_State.snapshot`` est servi depuis le
cache local (clé = ``modified_date``), mais ``set_active_model`` peut
avoir pointé vers un *autre* ``model_id`` entre-temps — on génèrerait
alors un rapport sur la mauvaise maquette sans s'en apercevoir.

Ce module expose des helpers purs :

- :func:`parse_bimdata_viewer_url` — extrait les IDs d'une URL viewer ;
- :func:`resolve_bimdata_target` — valide une cible par **IDs explicites**
  (refuse une URL : pas de résolveur d'URL caché dans le chemin d'audit) ;
- :func:`normalize_model_name` — normalise une chaîne (casse, accents,
  espaces multiples) pour comparaison robuste.
- :func:`model_matches_expected` — vérifie que la valeur attendue
  apparaît bien (par inclusion normalisée) dans le nom de la maquette.

Politique de matching : *expected* est traité comme un fragment
attendu. Cela couvre le cas usuel où l'utilisateur tape
``"LIFFRE"`` et où le modèle s'appelle ``"Maquette BIM - LIFFRÉ -
DOE.ifc"``. Un *expected* vide ou ``None`` désactive la vérification
(retour ``True``).
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

_WHITESPACE_RE = re.compile(r"\s+")
_BIMDATA_VIEWER_PATH_RE = re.compile(
    r"^/spaces/(?P<cloud_id>\d+)/projects/(?P<project_id>\d+)/viewer/"
    r"(?P<model_id>\d+)/?$"
)
_BIMDATA_PLATFORM_HOST = "platform.bimdata.io"


def parse_bimdata_viewer_url(value: str) -> tuple[str, str, str]:
    """Extrait ``(cloud_id, project_id, model_id)`` d'une URL BIMData.

    Format accepté :
    ``https://platform.bimdata.io/spaces/<cloud>/projects/<project>/viewer/<model>``
    avec query string ou fragment optionnels.

    Raises:
        ValueError: si l'URL n'est pas une URL HTTPS du viewer BIMData ou
            si les trois IDs numériques sont absents.
    """
    raw = (value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() != (
        _BIMDATA_PLATFORM_HOST
    ):
        raise ValueError(
            "URL BIMData invalide : attendu "
            "'https://platform.bimdata.io/spaces/<cloud_id>/projects/"
            "<project_id>/viewer/<model_id>'."
        )

    match = _BIMDATA_VIEWER_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ValueError(
            "URL BIMData invalide : impossible d'extraire cloud_id, "
            "project_id et model_id du chemin viewer."
        )
    return (
        match.group("cloud_id"),
        match.group("project_id"),
        match.group("model_id"),
    )


def resolve_bimdata_target(
    *,
    cloud_id: str | None,
    project_id: str | None,
    model_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Valide une cible BIMData par **IDs explicites** (le runtime cible TOUJOURS
    par IDs, jamais par URL).

    Une **URL viewer n'est PAS résolue ici** : pas de résolveur d'URL caché dans le
    chemin d'audit. Pour une URL, appeler :func:`parse_bimdata_viewer_url` (ou le
    tool ``parse_bimdata_target``) **en amont**, puis passer les IDs. Un ``model_id``
    ressemblant à une URL est refusé avec ce rappel. Les valeurs sont sinon
    retournées telles quelles (fallback ``.env`` géré par l'appelant).
    """
    if isinstance(model_id, str) and model_id.strip().lower().startswith(("http://", "https://")):
        raise ValueError(
            "model_id doit être un identifiant numérique, pas une URL. Pour une URL "
            "viewer BIMData, appelle d'abord parse_bimdata_target(url) puis passe "
            "cloud_id/project_id/model_id explicites."
        )
    return cloud_id, project_id, model_id


def normalize_model_name(value: str | None) -> str:
    """Normalise une chaîne pour comparaison insensible à casse/accents.

    - ``None`` ou non-``str`` → chaîne vide.
    - Supprime les diacritiques (NFKD).
    - Passe en minuscules.
    - Compacte les blancs successifs en un seul espace, trim.
    """
    if not isinstance(value, str) or not value:
        return ""
    # NFKD décompose les caractères accentués → on jette les combining marks
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WHITESPACE_RE.sub(" ", stripped).strip().lower()


def model_matches_expected(model_name: str | None, expected: str | None) -> bool:
    """Renvoie ``True`` si ``expected`` est contenu dans ``model_name``.

    Politique :

    - ``expected`` ``None`` ou vide (après normalisation) → la
      vérification est désactivée, on renvoie ``True``.
    - Sinon, comparaison par inclusion sur les versions normalisées.
    """
    expected_norm = normalize_model_name(expected)
    if not expected_norm:
        return True
    return expected_norm in normalize_model_name(model_name)
