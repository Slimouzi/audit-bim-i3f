"""Client HTTP BIMData authentifié, dérivé du projet COBie.

Authentification — ordre de précédence :
1. ``access_token`` passé au constructeur (cas d'usage : viewer BIMData qui
   injecte un token déjà acquis pour le compte de l'utilisateur),
2. ``BIMDATA_API_KEY`` (header ``Authorization: ApiKey …``),
3. flow OAuth2 ``client_credentials`` (``BIMDATA_CLIENT_ID`` + ``…SECRET``).
"""

from __future__ import annotations

from typing import Any

import requests

from .. import config


class BIMDataClient:
    """Client HTTP minimaliste pour l'API BIMData.

    Couvre la lecture du modèle (snapshot spatial + dénormalisation
    ``/element/raw``) et l'écriture (BCF Topics, Smart Views,
    classifications, propertysets). L'instance porte la cible
    (cloud/project/model) et la session HTTP authentifiée.

    Exemple:
        >>> client = BIMDataClient(cloud_id=33617, project_id=2698917,
        ...                        model_id=1674450)
        >>> client.get_buildings()      # GET /cloud/.../building
        [...]
        >>> client.create_bcf_full_topic({"title": "..."})
        {'guid': '...', ...}

    Attributes:
        base_url: Racine de l'API (sans ``/v1`` — la spec OpenAPI BIMData
            est exposée à plat sous ``api.bimdata.io``).
        cloud_id, project_id, model_id: Cible IFC. ``None`` autorisé tant
            qu'on n'appelle pas les routes ``/model/...``.
        access_token: Bearer OAuth2 si disponible (sinon ``None`` → on
            retombe sur API Key ou flow client_credentials).
        timeout: Timeout HTTP par défaut, en secondes.
        session: ``requests.Session`` avec le header ``Authorization``
            injecté à la construction.
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
        """Initialise le client et la session HTTP.

        Args:
            cloud_id: ID cloud BIMData. Fallback sur ``config.CLOUD_ID``
                (``.env``).
            project_id: ID projet BIMData. Fallback sur
                ``config.PROJECT_ID``.
            model_id: ID modèle IFC. Fallback sur ``config.MODEL_ID``.
            access_token: Bearer OAuth2 déjà acquis (utile pour les
                plugins viewer qui injectent le token utilisateur).
            timeout: Timeout HTTP par défaut (secondes). Override possible
                par appel via ``_post(..., timeout=...)``.

        Raises:
            ValueError: Si aucun mode d'authentification n'est disponible
                (ni ``access_token``, ni ``BIMDATA_API_KEY``, ni
                ``BIMDATA_CLIENT_ID + …SECRET``).
        """
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
        """Construit le header ``Authorization`` selon l'ordre de précédence.

        Ordre :

        1. ``access_token`` passé au constructeur (Bearer).
        2. ``BIMDATA_API_KEY`` du ``.env`` (ApiKey).
        3. Flow OAuth2 ``client_credentials`` (acquiert un Bearer).

        Returns:
            Dict prêt à être injecté dans ``session.headers``.

        Raises:
            ValueError: Si aucun mode d'auth n'est dispo.
        """
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
        """Acquiert un Bearer token via OAuth2 ``client_credentials``.

        Returns:
            Le token d'accès (à mettre tel quel après ``Bearer ``).

        Raises:
            requests.HTTPError: Si l'IAM Keycloak rejette les credentials.
        """
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
        """Compose l'URL absolue depuis un chemin relatif à ``base_url``.

        Args:
            path: Chemin commençant par ``/`` (ex: ``/cloud/123/project``).

        Returns:
            URL absolue.
        """
        return f"{self.base_url}{path}"

    def _get(self, path: str, params: dict | None = None) -> Any:
        """GET authentifié + décode JSON.

        Args:
            path: Chemin relatif (ex: ``/cloud/{id}/project/{id}/model/{id}/storey``).
            params: Paramètres de query string optionnels.

        Returns:
            La réponse JSON décodée (dict ou liste).

        Raises:
            requests.HTTPError: Si le statut est 4xx/5xx.
        """
        resp = self.session.get(self._url(path), params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: dict, timeout: int | None = None) -> Any:
        """POST authentifié JSON → JSON décodé.

        Args:
            path: Chemin relatif.
            json: Body sérialisable en JSON.
            timeout: Override du timeout pour cet appel (utile pour les
                POST volumineux : Vue d'ensemble Smart View, bulk
                classification-element, etc.).

        Returns:
            Réponse JSON décodée, ou ``None`` si le serveur renvoie un
            204 No Content, ou la chaîne brute si la réponse n'est pas
            du JSON parseable.

        Raises:
            requests.HTTPError: Si le statut est 4xx/5xx (le body est
                disponible via ``e.response.text`` côté appelant).
        """
        resp = self.session.post(self._url(path), json=json, timeout=(timeout or self.timeout))
        resp.raise_for_status()
        if not resp.content:
            return None
        try:
            return resp.json()
        except Exception:
            return resp.text

    # ── Routes ──────────────────────────────────────────────────────────────

    def _project_path(self, suffix: str = "") -> str:
        """Compose le chemin ``/cloud/{cloud}/project/{project}{suffix}``."""
        return f"/cloud/{self.cloud_id}/project/{self.project_id}{suffix}"

    def _model_path(self, suffix: str = "") -> str:
        """Compose le chemin ``/cloud/{cloud}/project/{project}/model/{model}{suffix}``."""
        return f"{self._project_path()}/model/{self.model_id}{suffix}"

    # Métadonnées
    def get_project(self) -> dict:
        """Récupère les métadonnées du projet BIMData.

        Returns:
            Dict ``{id, name, description, cloud, status, ...}``.
        """
        return self._get(self._project_path())

    def get_model(self) -> dict:
        """Récupère les métadonnées du modèle IFC.

        Returns:
            Dict ``{id, name, type, creator, status, structure_file, ...}``.
        """
        return self._get(self._model_path())

    # Hiérarchie spatiale
    def get_buildings(self) -> list:
        """Liste les ``IfcBuilding`` du modèle.

        Returns:
            Liste de dicts (un par bâtiment) avec ``uuid`` et attributs IFC.
        """
        return self._get(self._model_path("/building"))

    def get_building_detail(self, uuid: str) -> dict:
        """Détail d'un bâtiment (avec ``IfcPostalAddress`` si présente).

        Args:
            uuid: GlobalId IFC du bâtiment.

        Returns:
            Dict complet du bâtiment.
        """
        return self._get(self._model_path(f"/building/{uuid}"))

    def get_storeys(self) -> list:
        """Liste les ``IfcBuildingStorey`` (étages) du modèle."""
        return self._get(self._model_path("/storey"))

    def get_spaces(self) -> list:
        """Liste les ``IfcSpace`` (pièces) du modèle."""
        return self._get(self._model_path("/space"))

    def get_zones(self) -> list:
        """Liste les ``IfcZone`` du modèle (logements, parties communes)."""
        return self._get(self._model_path("/zone"))

    def get_sites(self) -> list:
        """Liste les ``IfcSite`` du modèle.

        BIMData n'expose pas de route ``/site`` dédiée ; on passe par
        ``/element?type=IfcSite``. Les coordonnées géographiques
        (RefLatitude, RefLongitude) sont dans ``attributes.properties``.

        Returns:
            Liste de dicts IfcSite avec attributs IFC.
        """
        return self._get(self._model_path("/element"), params={"type": "IfcSite"})

    # Éléments (route optimisée + dénormalisation)
    def get_raw_elements(self) -> list:
        """Récupère tous les éléments du modèle via ``/element/raw`` dénormalisé.

        La route ``/element/raw`` retourne une forme *normalisée* (psets,
        layers, classifications, materials stockés dans des tables
        parallèles et référencés par index). Cette méthode applique la
        *dénormalisation* pour exposer chaque élément avec ses
        ``property_sets``, ``classifications``, ``layers``,
        ``material_list``, ``attributes`` inlinés — format attendu par
        les règles d'audit.

        Returns:
            Liste de dicts ``{uuid, type, name, description, longname,
            object_type, attributes, property_sets, classifications,
            layers, material_list}``.
        """
        raw = self._get(self._model_path("/element/raw"))
        return _denormalize_raw_elements(raw)

    def get_structure_tree(self) -> list:
        """Arborescence spatiale complète (Project → Site → Building → Storey → …).

        Récupère l'URL ``structure_file`` sur le modèle puis télécharge
        le JSON depuis le bucket S3. Chaque nœud porte ``uuid``, ``type``,
        ``name`` et ``children``.

        Returns:
            Liste de nœuds racine (généralement 1 IfcProject). Liste vide
            si le modèle n'a pas encore généré son ``structure_file``.
        """
        model = self.get_model()
        url = model.get("structure_file")
        if not url:
            return []
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ── BCF (équivalent BIMData des « Smart Views » côté viewer) ─────────────
    # Les vues thématiques d'audit sont matérialisées comme des *BCF Topics*
    # avec un viewpoint qui colore/sélectionne les UUIDs en erreur. C'est le
    # standard buildingSMART (donc portable hors BIMData) et c'est ce que le
    # viewer BIMData consomme nativement.

    def create_bcf_full_topic(self, payload: dict) -> dict:
        """Crée un BCF Topic + Viewpoints en une seule requête.

        Endpoint : ``POST /bcf/2.1/projects/{project_id}/full-topic``.

        Pour qu'un topic apparaisse dans le panneau *Smart Views* du viewer
        BIMData (plutôt que dans les issues BCF classiques), inclure
        ``"format": "bimdata-smartview"`` dans le body — c'est ce que fait
        l'appelant (cf. ``smartview/builder.py``). Sans ce champ, le topic
        est créé avec ``format: "standard"``.

        Args:
            payload: dict respectant ``FullTopicRequest`` (cf. OpenAPI BIMData) —
                ``title`` obligatoire, ``viewpoints`` recommandé avec
                ``components.coloring`` ou ``components.selection``,
                ``format: "bimdata-smartview"`` pour cibler le panneau Smart Views.
        """
        # Timeout généreux : un topic Vue d'ensemble peut compter quelques
        # milliers d'UUIDs en selection + plusieurs groupes de coloring.
        return self._post(
            f"/bcf/2.1/projects/{self.project_id}/full-topic",
            payload,
            timeout=240,
        )


def _denormalize_raw_elements(raw: dict) -> list[dict]:
    """Dénormalise la réponse ``/element/raw`` de BIMData.

    L'API BIMData renvoie une structure normalisée pour économiser la
    bande passante : les psets, layers, classifications, materials et
    definitions sont stockés dans des tables parallèles, et chaque
    élément ne contient que des **index** vers ces tables. Pour l'audit,
    on dénormalise en inlinant tout sur chaque élément.

    Mapping des index :

    - ``elements[i].attributes`` → index dans ``property_sets`` (Pset des
      attributs IFC natifs : Name, LongName, Description, …)
    - ``elements[i].psets``      → liste d'index dans ``property_sets``
    - ``elements[i].layers``     → liste d'index dans ``layers``
    - ``elements[i].classifications`` → liste d'index dans ``classifications``
    - ``elements[i].material_list``   → liste d'index dans ``materials.materials_data``
    - ``property_sets[i].properties[j].def_id`` → index dans ``definitions``

    Args:
        raw: Réponse brute de ``/element/raw`` (dict avec ``elements``,
            ``property_sets``, ``layers``, ``classifications``,
            ``materials``, ``definitions``).

    Returns:
        Liste de dicts dénormalisés, un par élément, prêts pour l'audit.
        Liste vide si ``raw`` est ``None`` ou malformé.
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
        return [table[i] for i in (indices or []) if isinstance(i, int) and 0 <= i < len(table)]

    out = []
    for el in raw.get("elements") or []:
        attr_pset = expand_pset(el.get("attributes"))
        attr_lookup = {}
        if attr_pset:
            for prop in attr_pset["properties"]:
                nm = (prop.get("definition") or {}).get("name")
                if nm:
                    attr_lookup[nm] = prop.get("value")

        psets_inlined = [p for p in (expand_pset(i) for i in (el.get("psets") or [])) if p]
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
