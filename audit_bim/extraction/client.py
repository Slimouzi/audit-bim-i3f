"""Client HTTP BIMData authentifié, dérivé du projet COBie.

Authentification — ordre de précédence :
1. ``access_token`` passé au constructeur (cas d'usage : viewer BIMData qui
   injecte un token déjà acquis pour le compte de l'utilisateur),
2. ``BIMDATA_API_KEY`` (header ``Authorization: ApiKey …``),
3. flow OAuth2 ``client_credentials`` (``BIMDATA_CLIENT_ID`` + ``…SECRET``).
"""
from __future__ import annotations

from typing import Any, Optional

import requests

from .. import config


class BIMDataClient:
    """Client HTTP minimaliste pour l'audit (lecture du modèle + écriture smart views)."""

    def __init__(
        self,
        *,
        cloud_id: Optional[int | str] = None,
        project_id: Optional[int | str] = None,
        model_id: Optional[int | str] = None,
        access_token: Optional[str] = None,
        timeout: int = 60,
    ):
        self.base_url = config.BIMDATA_BASE_URL.rstrip("/")
        self.cloud_id = cloud_id if cloud_id is not None else config.CLOUD_ID
        self.project_id = project_id if project_id is not None else config.PROJECT_ID
        self.model_id = model_id if model_id is not None else config.MODEL_ID
        self.access_token = access_token or config.ACCESS_TOKEN
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self._auth_headers())

    # ── Auth ────────────────────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        if config.API_KEY:
            return {"Authorization": f"ApiKey {config.API_KEY}"}
        if config.CLIENT_ID and config.CLIENT_SECRET:
            token = self._fetch_oauth_token()
            self.access_token = token
            return {"Authorization": f"Bearer {token}"}
        raise ValueError(
            "Authentification BIMData manquante : passer access_token, ou "
            "définir BIMDATA_API_KEY, ou (BIMDATA_CLIENT_ID + …SECRET)."
        )

    def _fetch_oauth_token(self) -> str:
        resp = requests.post(
            config.BIMDATA_IAM_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": config.CLIENT_ID,
                "client_secret": config.CLIENT_SECRET,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    # ── HTTP helpers ────────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get(self, path: str, params: dict | None = None) -> Any:
        resp = self.session.get(self._url(path), params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: dict) -> Any:
        resp = self.session.post(self._url(path), json=json, timeout=self.timeout)
        resp.raise_for_status()
        if not resp.content:
            return None
        try:
            return resp.json()
        except Exception:
            return resp.text

    # ── Routes ──────────────────────────────────────────────────────────────

    def _project_path(self, suffix: str = "") -> str:
        return f"/cloud/{self.cloud_id}/project/{self.project_id}{suffix}"

    def _model_path(self, suffix: str = "") -> str:
        return f"{self._project_path()}/model/{self.model_id}{suffix}"

    # Métadonnées
    def get_project(self) -> dict:
        return self._get(self._project_path())

    def get_model(self) -> dict:
        return self._get(self._model_path())

    # Hiérarchie spatiale
    def get_buildings(self) -> list:
        return self._get(self._model_path("/building"))

    def get_building_detail(self, uuid: str) -> dict:
        return self._get(self._model_path(f"/building/{uuid}"))

    def get_storeys(self) -> list:
        return self._get(self._model_path("/storey"))

    def get_spaces(self) -> list:
        return self._get(self._model_path("/space"))

    def get_zones(self) -> list:
        return self._get(self._model_path("/zone"))

    def get_sites(self) -> list:
        return self._get(self._model_path("/element"), params={"type": "IfcSite"})

    # Éléments (route optimisée + dénormalisation)
    def get_raw_elements(self) -> list:
        raw = self._get(self._model_path("/element/raw"))
        return _denormalize_raw_elements(raw)

    def get_structure_tree(self) -> list:
        model = self.get_model()
        url = model.get("structure_file")
        if not url:
            return []
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # Smart Views
    def create_smart_view(self, payload: dict) -> dict:
        """Crée une smart view sur le projet.

        L'URL est composée à partir de :
            ``{cloud}/{project}{BIMDATA_SMARTVIEW_PATH}``
        ce qui permet d'ajuster ``BIMDATA_SMARTVIEW_PATH`` via l'env si la
        convention diffère sur ton tenant (cf. .env.example).
        """
        path = f"{self._project_path()}{config.BIMDATA_SMARTVIEW_PATH}"
        return self._post(path, payload)


def _denormalize_raw_elements(raw: dict) -> list[dict]:
    """Reproduit la dénormalisation de ``/element/raw`` du projet COBie.

    La forme normalisée référence par index les tables ``property_sets``,
    ``layers``, ``classifications``, ``materials`` et ``definitions``. Pour
    l'audit, on a besoin d'une vue inlinée par élément.
    """
    if not isinstance(raw, dict):
        return raw or []

    defs = raw.get("definitions") or []
    psets_table = raw.get("property_sets") or []
    layers_table = raw.get("layers") or []
    classifs_table = raw.get("classifications") or []
    materials_table = (raw.get("materials") or {}).get("materials_data") or []

    def expand_pset(idx):
        if not isinstance(idx, int) or not (0 <= idx < len(psets_table)):
            return None
        p = psets_table[idx]
        properties = []
        for prop in p.get("properties") or []:
            di = prop.get("def_id")
            df = defs[di] if isinstance(di, int) and 0 <= di < len(defs) else {}
            properties.append(
                {
                    "definition": {
                        "name": df.get("name"),
                        "value_type": df.get("value_type"),
                    },
                    "value": prop.get("value"),
                }
            )
        return {
            "name": p.get("name"),
            "type": p.get("type"),
            "description": p.get("description"),
            "properties": properties,
        }

    def by_index(table, indices):
        return [
            table[i] for i in (indices or []) if isinstance(i, int) and 0 <= i < len(table)
        ]

    out = []
    for el in raw.get("elements") or []:
        attr_pset = expand_pset(el.get("attributes"))
        attr_lookup = {}
        if attr_pset:
            for prop in attr_pset["properties"]:
                nm = (prop.get("definition") or {}).get("name")
                if nm:
                    attr_lookup[nm] = prop.get("value")

        psets_inlined = [
            p for p in (expand_pset(i) for i in (el.get("psets") or [])) if p
        ]
        material_list = [
            {"material": {"name": materials_table[i].get("name")}}
            for i in (el.get("material_list") or [])
            if isinstance(i, int) and 0 <= i < len(materials_table)
        ]

        out.append(
            {
                "uuid": el.get("uuid"),
                "type": el.get("type"),
                "name": attr_lookup.get("Name"),
                "description": attr_lookup.get("Description"),
                "longname": attr_lookup.get("LongName"),
                "object_type": attr_lookup.get("ObjectType"),
                "attributes": attr_pset,
                "property_sets": psets_inlined,
                "classifications": by_index(classifs_table, el.get("classifications")),
                "layers": by_index(layers_table, el.get("layers")),
                "material_list": material_list,
            }
        )
    return out
