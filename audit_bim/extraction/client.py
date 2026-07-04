"""Client BIMData — façade lecture + écriture.

Toute la **lecture** (`bimdata-read`) **et** l'**écriture** (`bimdata-write` :
classifications, property sets, BCF/Smart Views) vivent désormais dans les
packages extraits. ``BIMDataClient`` hérite de
:class:`bimdata_write.BIMDataWriteClient` (qui hérite lui-même de la lecture) et
ne fait plus que câbler le fallback ``config.*`` (``.env``) — aucun transport ni
``_post`` brut ici.

Les garde-fous d'intention (``WritePlan``, ``dry_run``, journal, sandbox,
``ensure_writes_allowed``) et la logique métier I3F restent dans ``audit-bim-i3f``.
"""

from __future__ import annotations

from bimdata_read.client import _build_retry_adapter, _denormalize_raw_elements
from bimdata_write import BIMDataAuthError, BIMDataWriteClient

from .. import config

__all__ = [
    "BIMDataClient",
    "BIMDataAuthError",
    "_build_retry_adapter",
    "_denormalize_raw_elements",
]


class BIMDataClient(BIMDataWriteClient):
    """Client BIMData **lecture + écriture** (façade historique).

    Hérite la lecture (`bimdata-read`) et l'écriture (`bimdata-write`). Signature
    de constructeur inchangée : IDs et auth retombent sur ``config.*`` (``.env``)
    quand ils ne sont pas passés — comportement historique préservé.

    Exemple:
        >>> client = BIMDataClient(cloud_id=..., project_id=..., model_id=...)
        >>> client.get_buildings()                       # lecture (héritée)
        >>> client.create_classification(name=..., notation=..., title=...)  # écriture
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
