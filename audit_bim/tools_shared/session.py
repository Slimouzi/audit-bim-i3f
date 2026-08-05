"""Outils MCP de **cible, identité et lecture** — socle partagé entre profils.

Cinq outils qu'un AMO doit pouvoir appeler avant toute spécialisation : résoudre
une URL en identifiants, vérifier l'accès, confirmer qu'on travaille sur la
bonne maquette, la lire, la rapatrier.

Ils vivaient dans le profil I3F, faute d'un second appelant. Ils en ont un
depuis E5, et `docs/scope-shared-tools.md` a établi par analyse des dépendances
qu'ils ne touchent que des briques et des champs de session neutres — seul
cercle de l'inventaire dont l'extraction ne repose sur aucune hypothèse.

Le code est déplacé **verbatim**. La surface MCP d'I3F ne change pas d'un nom ni
d'un paramètre : c'est la condition de ce lot, et le golden la vérifie.

Ce module ne nomme **aucun outil d'un profil**, ni dans son code, ni dans les
docstrings — qui sont servies au modèle comme descriptions MCP. Le ciblage se
désigne par sa fonction, et quand un message doit citer l'outil, il le lit dans
le profil actif (`_target_tool_name`). Une description qui nomme un outil absent
du serveur est une instruction plausible et inapplicable : elle coûte plus cher
qu'une absence de conseil.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from .. import config
from ..extraction.client import BIMDataAuthError
from ..extraction.computed_quantities import (
    json_digest,
    load_computed_quantities,
    merge_into_snapshot,
)
from ..extraction.ifc_download import download_model_ifc as download_ifc
from ..extraction.model_data import extract_snapshot
from ..extraction.snapshot_cache import cached_extract_snapshot
from ..extraction.snapshot_health import snapshot_diagnostics
from ..mcp.app import mcp
from ..mcp.model_identity import model_matches_expected, parse_bimdata_viewer_url
from ..mcp.session import _State, _target_tool_name
from ..safe_paths import safe_export_dir, safe_input_path
from ..security.redaction import redact_secrets

logger = logging.getLogger("audit_bim.tools_shared.session")

__all__ = [
    "parse_bimdata_target",
    "check_bimdata_access",
    "verify_active_model",
    "extract_model_snapshot",
    "download_model_ifc",
]


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
def parse_bimdata_target(url: str) -> dict:
    """Extrait ``cloud_id`` / ``project_id`` / ``model_id`` d'une **URL viewer** BIMData.

    À appeler **avant** l'outil de ciblage du profil actif, quand l'utilisateur
    fournit une URL
    (``https://platform.bimdata.io/spaces/<cloud>/projects/<project>/viewer/<model>``) :
    le runtime cible toujours BIMData par IDs explicites, jamais par URL. Ne touche
    à aucun état de session — c'est un simple parseur.
    """
    cloud_id, project_id, model_id = parse_bimdata_viewer_url(url)
    return {"cloud_id": cloud_id, "project_id": project_id, "model_id": model_id}


@mcp.tool()
def check_bimdata_access() -> dict:
    """Smoke test **cible + auth** : prouve l'accès BIMData réel (sans cache).

    L'outil de ciblage du profil actif ne fait que *configurer* l'auth ; ce tool
    la **prouve** en lisant ``get_project`` puis ``get_model`` en direct. À
    lancer juste après le ciblage, avant l'extraction. Rapporte aussi le **mode d'auth
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
def verify_active_model(
    expected_model_name: str,
    refresh_snapshot: bool = True,
    use_cache: bool = False,
) -> dict:
    """Garde-fou d'identité : confirme que la maquette BIMData active est
    bien celle attendue **avant** de lancer l'audit ou la génération des
    livrables.

    Pourquoi : le ciblage invalide bien ``_State.snapshot`` et
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
                logger.warning(
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
            "N'enchaînez PAS l'audit avant correction : reciblez avec "
            f"`{_target_tool_name()}` puis relancez ce contrôle."
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
        **snapshot_diagnostics(_State.snapshot),
    }


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
            logger.warning(
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
    summary.update(snapshot_diagnostics(_State.snapshot))
    summary["from_cache"] = hit
    if computed_block is not None:
        summary["computed_quantities"] = computed_block
    return summary


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
