"""Auto-résolution des contrats géométriques nécessaires au pack AVP.

Le pack a besoin de deux contrats produits par le calcul IfcOpenShell :
``computed_base_quantities/v1`` (surfaces d'espaces, dimensions de menuiseries,
aires de dalles) et ``envelope_quantities/v1``. Historiquement, il fallait les
produire à la main dans un autre MCP puis penser à passer les chemins — une
consigne oubliée produisait un pack aux colonnes vides.

Ce module rend l'enchaînement **automatique et déterministe** :

1. le snapshot porte déjà les quantités → rien à faire ;
2. sinon, un contrat déjà calculé pour ce modèle est réutilisé ;
3. sinon, le calcul est lancé localement depuis le ``.ifc`` actif ;
4. sinon, on remonte une demande **ciblée** (quel fichier, quel backend).

Sandbox : un fichier **fourni par l'utilisateur** est validé en lecture
(``safe_input_path``) ; un fichier **produit ici** vit sous ``AUDIT_OUTPUT_DIR``
et est relu par le chemin d'export — ``AUDIT_INPUT_DIR`` ne couvre pas
nécessairement le dossier de sortie.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bim_core.contracts import (
    SCHEMA_COMPUTED_BASE_QUANTITIES_V1,
    SCHEMA_ENVELOPE_QUANTITIES_V1,
)

from ..extraction.geometry_backend import (
    GeometryBackendUnavailable,
    compute_envelope_payload,
    compute_quantities_payload,
)
from ..safe_paths import (
    UnsafePathError,
    safe_export_dir,
    safe_export_path,
    safe_export_read_path,
    safe_input_path,
)

#: Sous-dossier d'export où vivent les contrats calculés localement.
CONTRACTS_SUBDIR = "contracts_v1"


class GeometryInputMissing(RuntimeError):
    """Aucun ``.ifc`` exploitable pour lancer le calcul.

    Porte de quoi poser une question **ciblée** (``ifc_path``), au lieu d'un
    « il manque des quantités » qui n'indique pas quoi faire.
    """

    def __init__(self, message: str, *, missing: str = "ifc_path"):
        self.missing = missing
        super().__init__(message)


def contracts_dir() -> Path:
    """Dossier des contrats calculés, sous la sandbox d'export."""
    return safe_export_dir(CONTRACTS_SUBDIR)


def _stem(ifc_path: str | Path | None, snapshot) -> str:
    """Racine de nom de fichier : celle du .ifc, sinon celle du modèle actif."""
    if ifc_path:
        return Path(ifc_path).stem
    name = ((getattr(snapshot, "model", None) or {}).get("name") or "").strip()
    return Path(name).stem if name else "modele"


def _contract_matches_model(doc: dict[str, Any], snapshot, ifc_path: str | Path | None) -> bool:
    """Le contrat porte-t-il bien sur le **modèle actif** ?

    Un nom de fichier qui « tombe bien » ne suffit pas : réutiliser le contrat
    d'une autre maquette produirait des surfaces d'un autre bâtiment, sans
    aucun signal. On compare donc la provenance déclarée (``source.ifc_file``)
    au ``.ifc`` visé ou au modèle actif ; en cas de doute, on recalcule.
    """
    source = (doc.get("source") or {}).get("ifc_file")
    if not source:
        return False  # provenance inconnue -> on ne parie pas
    stem_contrat = Path(str(source)).stem
    attendus = {s for s in (_stem(ifc_path, snapshot), _stem(None, snapshot)) if s}
    attendus.discard("modele")
    return bool(attendus) and stem_contrat in attendus


def _read_contract(
    path: Path,
    expected_schema: str,
    *,
    snapshot=None,
    ifc_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Relit un contrat déjà produit **sous le dossier d'export**.

    Renvoie ``None`` si le fichier est absent, illisible, d'un autre schéma ou
    d'un **autre modèle** : un fichier douteux ne doit jamais être réutilisé en
    silence — le recalcul est toujours préférable à une valeur étrangère.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict) or doc.get("schema") != expected_schema:
        return None
    if snapshot is not None and not _contract_matches_model(doc, snapshot, ifc_path):
        return None
    return doc


def _validate_ifc_path(ifc_path: str | Path) -> Path:
    """Valide un ``.ifc`` **fourni par l'appelant**, jamais accepté tel quel.

    Deux sandbox légitimes : la lecture (``AUDIT_INPUT_DIR``) et l'export
    (``AUDIT_OUTPUT_DIR``), ce dernier parce que ``download_model_ifc`` y dépose
    le fichier du modèle actif. Hors de ces deux racines → refus.
    """
    try:
        return safe_input_path(ifc_path, allowed_extensions={".ifc"})
    except UnsafePathError:
        pass
    try:
        cible = safe_export_read_path(ifc_path)
    except (UnsafePathError, OSError) as exc:
        raise GeometryInputMissing(
            f"Chemin .ifc refusé par la sandbox : {ifc_path}. Le fichier doit "
            "être sous ``AUDIT_INPUT_DIR``, ou sous ``AUDIT_OUTPUT_DIR`` s'il "
            "vient de ``download_model_ifc``."
        ) from exc
    if cible.suffix.lower() != ".ifc" or not cible.is_file():
        raise GeometryInputMissing(f"Chemin .ifc invalide ou introuvable : {ifc_path}")
    return cible


def _candidats_ifc() -> list[Path]:
    """Tous les ``.ifc`` visibles depuis les sandbox d'entrée et de sortie."""
    candidats: list[Path] = []
    sortie = os.getenv("AUDIT_OUTPUT_DIR")
    if sortie:
        candidats.extend(sorted(Path(sortie).rglob("*.ifc")))
    entree = os.getenv("AUDIT_INPUT_DIR")
    racines = [Path(entree)] if entree else [Path.cwd() / "audit_in", Path.cwd()]
    for racine in racines:
        if racine.is_dir():
            candidats.extend(sorted(racine.glob("*.ifc")))
    return candidats


def _cache_bimdata_prefix(model_ids: tuple[str | None, ...] | None) -> str | None:
    """Préfixe du cache ``download_model_ifc`` : ``<cloud>_<projet>_<modele>_``."""
    if not model_ids or not all(model_ids[:3]):
        return None
    return "_".join(str(x) for x in model_ids[:3]) + "_"


def resolve_active_ifc(
    ifc_path: str | Path | None,
    snapshot,
    *,
    session_ifc_path: str | Path | None = None,
    model_ids: tuple[str | None, ...] | None = None,
) -> Path | None:
    """Localise le ``.ifc`` **du modèle actif**, sans réseau.

    Le fichier doit être **corrélé** au modèle actif, jamais simplement
    disponible : calculer sur une autre maquette produirait un livrable faux et
    silencieux — des surfaces d'un autre bâtiment, sans aucun signal.

    Sources acceptées, dans l'ordre :

    1. ``ifc_path`` explicite (validé sandbox) ;
    2. chemin retourné par ``download_model_ifc`` et mémorisé en session ;
    3. cache BIMData, dont le nom porte ``cloud_id``/``project_id``/``model_id`` ;
    4. ``.ifc`` dont le *stem* est **exactement** celui du modèle actif.

    Un unique ``.ifc`` non corrélé n'est **pas** un repli : si le modèle actif
    est nommé et qu'aucune source ne correspond, on préfère demander.
    """
    if ifc_path:
        return _validate_ifc_path(ifc_path)

    if session_ifc_path:
        p = Path(session_ifc_path)
        if p.is_file():
            return p

    candidats = _candidats_ifc()

    prefixe = _cache_bimdata_prefix(model_ids)
    if prefixe:
        caches = sorted({c.resolve() for c in candidats if c.stem.startswith(prefixe)})
        if caches:
            return caches[-1]  # le plus récent (modified_date en suffixe)

    stem = _stem(None, snapshot)
    if stem and stem != "modele":
        exacts = sorted({c.resolve() for c in candidats if c.stem == stem})
        if len(exacts) > 1:
            raise GeometryInputMissing(
                f"Plusieurs fichiers .ifc portent le nom du modèle actif "
                f"« {stem} » : " + ", ".join(str(c) for c in exacts) + ". Préciser "
                "``ifc_path`` — choisir à votre place risquerait de calculer sur "
                "la mauvaise maquette."
            )
        if exacts:
            return exacts[0]
        # Modèle actif NOMMÉ mais aucun fichier corrélé : on ne se rabat pas sur
        # « le seul .ifc du dossier ». Un fichier disponible n'est pas un
        # fichier pertinent.
        return None

    # Modèle actif sans nom exploitable : un candidat UNIQUE reste acceptable,
    # faute de quoi aucun calcul ne serait jamais possible dans ce cas.
    uniques = {c.resolve() for c in candidats}
    return next(iter(uniques)) if len(uniques) == 1 else None


def ensure_computed_quantities_json(
    snapshot,
    *,
    ifc_path: str | Path | None = None,
    force: bool = False,
    session_ifc_path: str | Path | None = None,
    model_ids: tuple[str | None, ...] | None = None,
) -> dict[str, Any]:
    """Garantit la disponibilité du contrat ``computed_base_quantities/v1``.

    Returns:
        ``{json_path, reused, computed, coverage}``. ``json_path`` est
        exploitable tel quel : il vit sous la sandbox d'export.

    Raises:
        GeometryInputMissing: aucun ``.ifc`` exploitable.
        GeometryBackendUnavailable: calcul géométrique non installé.
    """
    cible = safe_export_path(
        Path(CONTRACTS_SUBDIR) / f"{_stem(ifc_path, snapshot)}_computed_quantities.json",
        overwrite=True,
    )
    if not force:
        existant = _read_contract(
            cible,
            SCHEMA_COMPUTED_BASE_QUANTITIES_V1,
            snapshot=snapshot,
            ifc_path=ifc_path,
        )
        if existant is not None:
            return {
                "json_path": str(cible),
                "reused": True,
                "computed": False,
                "coverage": existant.get("coverage"),
            }

    source = resolve_active_ifc(
        ifc_path, snapshot, session_ifc_path=session_ifc_path, model_ids=model_ids
    )
    if source is None:
        raise GeometryInputMissing(
            "Aucun fichier .ifc du modèle actif n'a été trouvé pour calculer les "
            "quantités manquantes. Fournir ``ifc_path``, ou appeler "
            "``download_model_ifc`` pour récupérer le .ifc du modèle BIMData actif."
        )

    payload = compute_quantities_payload(source)
    contracts_dir()  # garantit l'existence du dossier
    cible.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "json_path": str(cible),
        "reused": False,
        "computed": True,
        "coverage": payload.get("coverage"),
        "ifc_path": str(source),
    }


def ensure_envelope_json(
    snapshot,
    *,
    ifc_path: str | Path | None = None,
    seuil_3f: float | None = None,
    layer_pattern: str | None = None,
    type_pattern: str | None = None,
    force: bool = False,
    session_ifc_path: str | Path | None = None,
    model_ids: tuple[str | None, ...] | None = None,
) -> dict[str, Any]:
    """Garantit la disponibilité du contrat ``envelope_quantities/v1``.

    Un calcul qui ne retient **aucun** type de façade est une erreur explicite,
    pas une annexe « conforme » vide : sans calque ni motif de type fiable, la
    décomposition MOA n'a pas de sens.
    """
    cible = safe_export_path(
        Path(CONTRACTS_SUBDIR) / f"{_stem(ifc_path, snapshot)}_envelope.json",
        overwrite=True,
    )
    if not force:
        existant = _read_contract(
            cible, SCHEMA_ENVELOPE_QUANTITIES_V1, snapshot=snapshot, ifc_path=ifc_path
        )
        if existant is not None:
            return {"json_path": str(cible), "reused": True, "computed": False}

    source = resolve_active_ifc(
        ifc_path, snapshot, session_ifc_path=session_ifc_path, model_ids=model_ids
    )
    if source is None:
        raise GeometryInputMissing(
            "Aucun fichier .ifc du modèle actif n'a été trouvé pour calculer "
            "l'enveloppe. Fournir ``ifc_path``, ou appeler ``download_model_ifc``."
        )

    payload = compute_envelope_payload(
        source,
        seuil_3f=seuil_3f,
        layer_pattern=layer_pattern,
        type_pattern=type_pattern,
    )
    if not payload.get("par_type"):
        raise GeometryInputMissing(
            "Le calcul d'enveloppe n'a retenu aucun type de façade sur cette "
            "maquette. Préciser ``envelope_layer_pattern`` (calque des murs "
            "d'enveloppe, ex. « 221|extérieurs périphériques ») et "
            "``envelope_type_pattern`` (ex. « ^ME[ _] »), ou fournir un "
            "``envelope_json`` calculé. Aucune annexe n'est produite : une "
            "décomposition vide ne serait pas un livrable conforme.",
            missing="envelope_layer_pattern",
        )
    contracts_dir()
    cible.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"json_path": str(cible), "reused": False, "computed": True, "ifc_path": str(source)}


__all__ = [
    "CONTRACTS_SUBDIR",
    "GeometryBackendUnavailable",
    "GeometryInputMissing",
    "contracts_dir",
    "ensure_computed_quantities_json",
    "ensure_envelope_json",
    "resolve_active_ifc",
]
