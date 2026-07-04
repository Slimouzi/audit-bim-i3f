"""Client BIMData — façade lecture + écriture.

La **lecture** (auth, transport ``GET``, routes ``get_*``, dénormalisation
``/element/raw``) vit désormais dans ``bimdata-read`` (``BIMDataReadClient``).
``BIMDataClient`` en hérite et n'ajoute que les **écritures** — transport
``_post`` (utilisé aussi directement par ``classifier/applier``) et
``create_bcf_full_topic`` (BCF Topics / Smart Views) — réservées à ce MCP jusqu'à
l'extraction d'un MCP « BIMData Write » dédié.

Le constructeur préserve le fallback ``config.*`` (``.env`` : base_url, IDs,
API_KEY, OAuth) : le comportement historique côté audit-bim est inchangé.
"""

from __future__ import annotations

from typing import Any

from bimdata_read.client import (
    BIMDataAuthError,
    BIMDataReadClient,
    _build_retry_adapter,
    _denormalize_raw_elements,
)

from .. import config

__all__ = [
    "BIMDataClient",
    "BIMDataAuthError",
    "_build_retry_adapter",
    "_denormalize_raw_elements",
]


class BIMDataClient(BIMDataReadClient):
    """Client BIMData **lecture + écriture** (façade historique).

    Hérite toute la lecture de :class:`bimdata_read.BIMDataReadClient` et ajoute
    les écritures. Signature de constructeur inchangée : les IDs et l'auth
    retombent sur ``config.*`` (``.env``) quand ils ne sont pas passés.

    Exemple:
        >>> client = BIMDataClient(cloud_id=..., project_id=..., model_id=...)
        >>> client.get_buildings()                  # lecture (héritée)
        [...]
        >>> client.create_bcf_full_topic({"title": "..."})   # écriture (locale)
        {'guid': '...', ...}
    """

    def __init__(
        self,
        *,
        cloud_id: int | str | None = None,
        project_id: int | str | None = None,
        model_id: int | str | None = None,
        access_token: str | None = None,
        timeout: int = 60,
    ):
        super().__init__(
            base_url=config.BIMDATA_BASE_URL,
            cloud_id=cloud_id if cloud_id is not None else config.CLOUD_ID,
            project_id=project_id if project_id is not None else config.PROJECT_ID,
            model_id=model_id if model_id is not None else config.MODEL_ID,
            api_key=config.API_KEY,
            access_token=access_token or config.ACCESS_TOKEN,
            client_id=config.CLIENT_ID,
            client_secret=config.CLIENT_SECRET,
            iam_url=config.BIMDATA_IAM_URL,
            timeout=timeout,
        )

    # ── Écriture (hors périmètre lecture — futur MCP « BIMData Write ») ───────

    def _post(self, path: str, json: dict, timeout: int | None = None) -> Any:
        """POST authentifié JSON → JSON décodé.

        Returns:
            Réponse JSON décodée, ``None`` si 204 No Content, ou la chaîne brute
            si la réponse n'est pas du JSON parseable.

        Raises:
            BIMDataAuthError: Statut 401/403.
            requests.HTTPError: Autres statuts 4xx/5xx.
        """
        resp = self.session.post(self._url(path), json=json, timeout=(timeout or self.timeout))
        if resp.status_code in (401, 403):
            raise BIMDataAuthError(f"BIMData {resp.status_code} on {path}")
        resp.raise_for_status()
        if not resp.content:
            return None
        try:
            return resp.json()
        except Exception:
            return resp.text

    def create_bcf_full_topic(self, payload: dict) -> dict:
        """Crée un BCF Topic + Viewpoints en une requête.

        Endpoint : ``POST /bcf/2.1/projects/{project_id}/full-topic``. Inclure
        ``"format": "bimdata-smartview"`` dans le body cible le panneau Smart
        Views du viewer (cf. ``smartview/builder.py``).
        """
        # Timeout généreux : un topic Vue d'ensemble peut compter quelques
        # milliers d'UUIDs en selection + plusieurs groupes de coloring.
        return self._post(
            f"/bcf/2.1/projects/{self.project_id}/full-topic",
            payload,
            timeout=240,
        )
