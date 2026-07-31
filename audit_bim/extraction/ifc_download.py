"""Téléchargement du fichier ``.ifc`` source depuis BIMData (cache local).

Le pack AVP peut avoir besoin du **fichier IFC** lui-même (et non du seul
snapshot BIMData) — par exemple pour le passer au MCP ``ifc-geometry`` qui
calcule géométriquement les ``BaseQuantities`` manquantes.

Design :

- **Streaming disque** : le corps HTTP n'est jamais chargé en RAM ; on écrit par
  chunks dans un fichier ``.part`` puis on renomme (atomique).
- **Plafond de taille** : ``AUDIT_MAX_IFC_MB`` (défaut 500) — le téléchargement
  est interrompu et le fichier partiel supprimé si dépassé.
- **Cache** keyé ``cloud_id`` + ``project_id`` + ``model_id`` + ``modified_date``
  (aligné sur le cache snapshot) : pas de collision inter-projets, invalidation à
  la republication du modèle. ``overwrite`` force le re-téléchargement.

Aucune écriture BIMData : lecture seule (``get_model`` + GET de l'URL signée).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_CHUNK = 1024 * 1024  # 1 Mo
_SANITIZE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize(value: str) -> str:
    """Fragment de nom de fichier sûr (pas de séparateur ni caractère réservé)."""
    return _SANITIZE.sub("_", str(value)).strip("_") or "x"


def _ifc_file_url(model: dict[str, Any]) -> str | None:
    """URL signée du fichier IFC dans les métadonnées ``get_model`` (défensif :
    ``document.file`` en priorité, puis quelques alias plats connus)."""
    doc = model.get("document")
    if isinstance(doc, dict) and doc.get("file"):
        return str(doc["file"])
    for key in ("file", "source_file", "ifc_file"):
        val = model.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _stream_to_file(session, url: str, target: Path, *, max_bytes: int, timeout: int) -> int:
    """Écrit le corps de ``url`` dans ``target`` par chunks. Renvoie le nombre
    d'octets écrits.

    Robustesse : le fichier partiel ``.part`` est **toujours** nettoyé si le
    streaming n'aboutit pas — dépassement du plafond, erreur réseau au milieu
    (``iter_content`` qui lève), échec d'écriture disque, etc. ``target`` n'est
    matérialisé qu'en cas de succès (rename atomique)."""
    tmp = target.with_name(target.name + ".part")
    written = 0
    ok = False
    resp = session.get(url, stream=True, timeout=timeout)
    try:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_CHUNK):
                if not chunk:
                    continue
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError(
                        f"Fichier IFC trop volumineux (> {max_bytes // (1024 * 1024)} Mo, "
                        "AUDIT_MAX_IFC_MB) — téléchargement interrompu."
                    )
                fh.write(chunk)
        tmp.replace(target)  # atomique, seulement en cas de succès complet
        ok = True
        return written
    finally:
        close = getattr(resp, "close", None)
        if callable(close):
            close()
        if not ok:
            tmp.unlink(missing_ok=True)  # partiel nettoyé sur TOUTE sortie non-OK


def download_model_ifc(
    client,
    *,
    cache_dir: str | Path,
    max_mb: int,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Télécharge le ``.ifc`` du modèle actif dans ``<cache_dir>/ifc/`` (streaming).

    Le nom de fichier est keyé ``<cloud>_<project>_<model>_<modified_date>.ifc``
    (aligné sur le cache snapshot) : un cache hit évite un re-téléchargement tant
    que le modèle n'a pas été republié, sans collision inter-projets.

    Args:
        client: client BIMData actif (expose ``get_model`` + ``session``).
        cache_dir: racine du cache (sandboxée par l'appelant).
        max_mb: plafond de taille (Mo) — au-delà, échec propre.
        overwrite: force le re-téléchargement même si le cache est présent.

    Returns:
        ``{path, from_cache, size_bytes, model_id, modified_date}``.

    Raises:
        ValueError: URL IFC introuvable, ou taille au-delà du plafond.
    """
    model = client.get_model() or {}
    model_id = str(model.get("id") or getattr(client, "model_id", None) or "model")
    modified = str(model.get("modified_date") or "nodate")
    # Clé de cache alignée sur le cache snapshot : cloud + projet + modèle +
    # modified_date → pas de collision inter-projets même si deux modèles
    # partageaient un id, et invalidation à la republication.
    cloud_id = str(getattr(client, "cloud_id", None) or model.get("cloud") or "c")
    project_id = str(getattr(client, "project_id", None) or model.get("project") or "p")

    ifc_dir = Path(cache_dir) / "ifc"
    ifc_dir.mkdir(parents=True, exist_ok=True)
    fname = "_".join(_sanitize(p) for p in (cloud_id, project_id, model_id, modified))
    target = ifc_dir / f"{fname}.ifc"

    if target.exists() and not overwrite:
        return {
            "path": str(target),
            "from_cache": True,
            "size_bytes": target.stat().st_size,
            "model_id": model_id,
            "modified_date": modified,
        }

    url = _ifc_file_url(model)
    if not url:
        raise ValueError(
            "URL du fichier IFC introuvable dans get_model() (champ `document.file`) — "
            "le modèle n'expose peut-être pas encore son fichier source."
        )

    size = _stream_to_file(
        client.session,
        url,
        target,
        max_bytes=int(max_mb) * 1024 * 1024,
        timeout=getattr(client, "timeout", 60),
    )
    return {
        "path": str(target),
        "from_cache": False,
        "size_bytes": size,
        "model_id": model_id,
        "modified_date": modified,
    }
