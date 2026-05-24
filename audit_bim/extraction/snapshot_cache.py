"""Cache local du ``ModelSnapshot`` BIMData.

L'extraction d'un snapshot (``extract_snapshot``) effectue 7 à 9 appels
HTTP en cascade vers l'API BIMData pour récupérer la hiérarchie spatiale
et les éléments dénormalisés (``/element/raw``). Sur un modèle moyen
(~2 000 éléments), cela prend **5 à 10 secondes** et consomme du quota
réseau.

Ce module met en cache le snapshot dans un fichier JSON gzip local, clé
par un hash de ``(cloud_id, project_id, model_id, model.modified_date)``.
Tant que le modèle BIMData n'a pas été ré-uploadé, le cache reste valide
et l'extraction devient instantanée (lecture disque).

Workflow type :

>>> client = BIMDataClient(...)
>>> snap = cached_extract_snapshot(client, cache_dir=".audit_cache")
# Hit ou miss selon état du modèle, la fonction gère elle-même.

Le cache est sain à la coupure (écriture atomique via fichier temp +
rename) et porte sa propre version de schéma — toute mise à jour du
``ModelSnapshot`` côté code rend les anciens caches invalides
automatiquement.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path

from .client import BIMDataClient
from .model_data import ModelSnapshot, extract_snapshot

# Bump à chaque changement de schéma de ModelSnapshot pour invalider les
# caches existants automatiquement.
_CACHE_SCHEMA_VERSION = 1

# Champs sérialisés du ModelSnapshot (ordre = ordre de reconstruction).
_SNAPSHOT_FIELDS = (
    "project",
    "model",
    "sites",
    "buildings",
    "storeys",
    "spaces",
    "zones",
    "elements",
    "structure_tree",
)


def _cache_key(cloud_id, project_id, model_id, model_modified_date: str | None) -> str:
    """Calcule la clé de cache (SHA-256 tronqué sur 16 chars).

    Inclut la version de schéma pour invalider automatiquement les
    caches en cas d'évolution du modèle Pydantic.

    Args:
        cloud_id, project_id, model_id: IDs BIMData de la cible.
        model_modified_date: Timestamp de dernière modification du
            modèle côté serveur (issu de ``client.get_model()``).

    Returns:
        Clé hexadécimale 16 caractères utilisable en nom de fichier.
    """
    raw = (
        f"v{_CACHE_SCHEMA_VERSION}"
        f"|cloud={cloud_id}|project={project_id}|model={model_id}"
        f"|modified={model_modified_date or ''}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(cache_dir: Path, key: str) -> Path:
    """Renvoie le chemin du fichier cache pour une clé donnée."""
    return cache_dir / f"snapshot_{key}.json.gz"


def _serialize(snap: ModelSnapshot) -> dict:
    """Sérialise un snapshot en dict JSON-compatible."""
    return {
        "_schema_version": _CACHE_SCHEMA_VERSION,
        **{field: getattr(snap, field) for field in _SNAPSHOT_FIELDS},
    }


def _deserialize(data: dict) -> ModelSnapshot:
    """Reconstruit un snapshot indexé depuis un dict sérialisé."""
    kwargs = {field: data.get(field, [] if field != "model" else {}) for field in _SNAPSHOT_FIELDS}
    return ModelSnapshot(**kwargs).index()


def _atomic_write(path: Path, payload: bytes) -> None:
    """Écrit ``payload`` dans ``path`` de façon atomique (temp + rename).

    Évite la corruption en cas de coupure pendant l'écriture (le fichier
    final est soit absent, soit complet).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # tempfile dans le même dossier pour garantir un rename atomique
    fd, tmp_str = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def save_snapshot_to_cache(
    snap: ModelSnapshot,
    *,
    cloud_id,
    project_id,
    model_id,
    model_modified_date: str | None,
    cache_dir: str | Path,
) -> Path:
    """Sauve un snapshot dans le cache local.

    Args:
        snap: Snapshot à sauvegarder.
        cloud_id, project_id, model_id, model_modified_date: Composent
            la clé de cache.
        cache_dir: Dossier racine du cache (créé si absent).

    Returns:
        Chemin absolu du fichier écrit.
    """
    key = _cache_key(cloud_id, project_id, model_id, model_modified_date)
    path = _cache_path(Path(cache_dir), key)
    payload = gzip.compress(json.dumps(_serialize(snap), ensure_ascii=False).encode("utf-8"))
    _atomic_write(path, payload)
    return path


def load_snapshot_from_cache(
    *,
    cloud_id,
    project_id,
    model_id,
    model_modified_date: str | None,
    cache_dir: str | Path,
) -> ModelSnapshot | None:
    """Charge un snapshot depuis le cache si la clé matche.

    Returns:
        ``ModelSnapshot`` indexé en cas de hit, ``None`` si miss ou
        cache corrompu/invalide.
    """
    key = _cache_key(cloud_id, project_id, model_id, model_modified_date)
    path = _cache_path(Path(cache_dir), key)
    if not path.exists():
        return None
    try:
        raw = gzip.decompress(path.read_bytes()).decode("utf-8")
        data = json.loads(raw)
        if data.get("_schema_version") != _CACHE_SCHEMA_VERSION:
            return None
        return _deserialize(data)
    except Exception:
        # Cache corrompu : on l'ignore (la prochaine extraction le réécrira).
        return None


def cached_extract_snapshot(
    client: BIMDataClient,
    *,
    cache_dir: str | Path = ".audit_cache",
    use_cache: bool = True,
) -> tuple[ModelSnapshot, bool]:
    """Extrait le snapshot avec mise en cache transparente.

    Récupère d'abord ``client.get_model()`` (1 appel léger) pour
    connaître ``modified_date`` du modèle. Si un fichier cache
    correspondant existe et que ``use_cache=True``, le snapshot est
    chargé depuis le disque (instantané). Sinon, extraction complète +
    sauvegarde.

    Args:
        client: Client BIMData authentifié.
        cache_dir: Dossier racine du cache. Créé si absent.
            Défaut ``".audit_cache"`` (sous le cwd).
        use_cache: Si ``False``, force l'extraction complète et réécrit
            le cache (utile en debug ou pour rafraîchir).

    Returns:
        Tuple ``(snapshot, hit)`` où ``hit`` indique si le snapshot
        vient du cache (``True``) ou d'une extraction complète
        (``False``).

    Raises:
        Exception: Les exceptions de ``client.get_model`` ou
            ``extract_snapshot`` sont remontées (pas avalées).
    """
    model = client.get_model()
    modified_date = (model or {}).get("modified_date") or (model or {}).get("modified") or None

    if use_cache:
        cached = load_snapshot_from_cache(
            cloud_id=client.cloud_id,
            project_id=client.project_id,
            model_id=client.model_id,
            model_modified_date=modified_date,
            cache_dir=cache_dir,
        )
        if cached is not None:
            return cached, True

    snap = extract_snapshot(client)
    try:
        save_snapshot_to_cache(
            snap,
            cloud_id=client.cloud_id,
            project_id=client.project_id,
            model_id=client.model_id,
            model_modified_date=modified_date,
            cache_dir=cache_dir,
        )
    except Exception:
        # Échec d'écriture cache (permissions, disque plein) : non bloquant.
        pass
    return snap, False
