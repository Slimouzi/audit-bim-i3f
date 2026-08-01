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
from ..safe_paths import safe_export_dir, safe_export_path

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


def _read_contract(path: Path, expected_schema: str) -> dict[str, Any] | None:
    """Relit un contrat déjà produit **sous le dossier d'export**.

    Renvoie ``None`` si le fichier est absent, illisible ou d'un autre schéma :
    un fichier douteux ne doit jamais être réutilisé en silence.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) and doc.get("schema") == expected_schema else None


def resolve_active_ifc(ifc_path: str | Path | None, snapshot) -> Path | None:
    """Localise le ``.ifc`` du modèle actif, sans réseau.

    Ordre : chemin explicite → cache de ``download_model_ifc`` (sous
    ``AUDIT_OUTPUT_DIR``) → dossier d'entrée, si un seul ``.ifc`` y correspond.
    """
    if ifc_path:
        p = Path(ifc_path).expanduser()
        return p if p.is_file() else None

    stem = _stem(None, snapshot)
    candidats: list[Path] = []

    sortie = os.getenv("AUDIT_OUTPUT_DIR")
    if sortie:
        candidats.extend(sorted(Path(sortie).rglob("*.ifc")))
    entree = os.getenv("AUDIT_INPUT_DIR")
    racines = [Path(entree)] if entree else [Path.cwd() / "audit_in", Path.cwd()]
    for racine in racines:
        if racine.is_dir():
            candidats.extend(sorted(racine.glob("*.ifc")))

    if stem and stem != "modele":
        exacts = [c for c in candidats if c.stem == stem]
        if exacts:
            return exacts[0]
    # Sans nom de modèle exploitable, on n'accepte qu'un candidat UNIQUE :
    # choisir arbitrairement entre plusieurs maquettes serait un pari.
    uniques = {c.resolve() for c in candidats}
    return next(iter(uniques)) if len(uniques) == 1 else None


def ensure_computed_quantities_json(
    snapshot,
    *,
    ifc_path: str | Path | None = None,
    force: bool = False,
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
        existant = _read_contract(cible, SCHEMA_COMPUTED_BASE_QUANTITIES_V1)
        if existant is not None:
            return {
                "json_path": str(cible),
                "reused": True,
                "computed": False,
                "coverage": existant.get("coverage"),
            }

    source = resolve_active_ifc(ifc_path, snapshot)
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
        existant = _read_contract(cible, SCHEMA_ENVELOPE_QUANTITIES_V1)
        if existant is not None:
            return {"json_path": str(cible), "reused": True, "computed": False}

    source = resolve_active_ifc(ifc_path, snapshot)
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
