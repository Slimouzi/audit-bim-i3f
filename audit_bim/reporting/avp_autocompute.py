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


class ContractModelMismatch(ValueError):
    """Le contrat **fourni explicitement** ne porte pas sur le modèle actif.

    Le cas réel : l'auditeur rejoue une recette et passe le chemin d'un contrat
    calculé pour une autre maquette. Les surfaces d'un autre bâtiment entreraient
    alors dans un livrable nommé d'après le projet courant — exactement la classe
    d'erreur que ``verify_active_model`` ferme côté cible. Un chemin explicite ne
    doit pas rouvrir cette fenêtre : la provenance déclarée dans ``source.ifc_file``
    prime sur l'intention de l'appelant.
    """

    def __init__(self, message: str, *, parametre: str, provenance: str | None):
        self.parametre = parametre
        self.provenance = provenance
        super().__init__(message)


def contract_source_ifc(doc: dict[str, Any] | None) -> str | None:
    """``source.ifc_file`` déclaré par un contrat, ou ``None``.

    Exposé pour la **traçabilité** du pack : le retour de la génération doit dire
    de quel ``.ifc`` chaque contrat provient, sans que l'appelant ait à rouvrir
    les JSON.
    """
    if not isinstance(doc, dict):
        return None
    source = (doc.get("source") or {}).get("ifc_file")
    return str(source) if source else None


def assert_contract_matches_model(
    doc: dict[str, Any],
    snapshot,
    *,
    parametre: str,
    ifc_path: str | Path | None = None,
    session_ifc_path: str | Path | None = None,
    model_ids: tuple[str | None, ...] | None = None,
) -> None:
    """Vérifie qu'un contrat **fourni** porte sur le modèle actif, sinon lève.

    Même règle que la réutilisation automatique (:func:`_contract_matches_model`) :
    les deux formes de nom légitimes — nom métier BIMData **et** préfixe du cache
    ``<cloud>_<projet>_<modele>_`` — sont acceptées, sans quoi tout contrat calculé
    depuis un ``.ifc`` téléchargé serait rejeté à tort.
    """
    if snapshot is None:
        return
    if _contract_matches_model(
        doc,
        snapshot,
        ifc_path,
        session_ifc_path=session_ifc_path,
        model_ids=model_ids,
    ):
        return
    provenance = contract_source_ifc(doc)
    attendu = _stem(None, snapshot) or "modèle actif"
    prefixe = _cache_bimdata_prefix(model_ids)
    raise ContractModelMismatch(
        f"Le contrat passé en ``{parametre}`` ne porte pas sur le modèle actif : "
        f"provenance déclarée « {provenance or 'inconnue'} », attendu « {attendu} »"
        + (f" ou un fichier préfixé « {prefixe} »" if prefixe else "")
        + ". Générer le pack avec ce contrat produirait les surfaces d'une autre "
        "maquette sous le nom du projet courant. Recalculer le contrat sur le "
        "modèle actif (``download_model_ifc`` puis le MCP ifc-geometry), ou "
        "laisser l'auto-calcul le faire.",
        parametre=parametre,
        provenance=provenance,
    )


def contracts_dir() -> Path:
    """Dossier des contrats calculés, sous la sandbox d'export."""
    return safe_export_dir(CONTRACTS_SUBDIR)


def _stem(ifc_path: str | Path | None, snapshot) -> str:
    """Racine de nom de fichier : celle du .ifc, sinon celle du modèle actif."""
    if ifc_path:
        return Path(ifc_path).stem
    name = ((getattr(snapshot, "model", None) or {}).get("name") or "").strip()
    return Path(name).stem if name else "modele"


def _contract_matches_model(
    doc: dict[str, Any],
    snapshot,
    ifc_path: str | Path | None,
    *,
    session_ifc_path: str | Path | None = None,
    model_ids: tuple[str | None, ...] | None = None,
) -> bool:
    """Le contrat porte-t-il bien sur le **modèle actif** ?

    Un nom de fichier qui « tombe bien » ne suffit pas : réutiliser le contrat
    d'une autre maquette produirait des surfaces d'un autre bâtiment, sans
    aucun signal. On compare la provenance déclarée (``source.ifc_file``) aux
    formes de nom légitimes de la cible — nom métier **et** nom de cache
    BIMData, sans quoi un contrat calculé depuis un ``.ifc`` téléchargé serait
    recalculé à chaque génération. En cas de doute, on recalcule.
    """
    source = (doc.get("source") or {}).get("ifc_file")
    if not source:
        return False  # provenance inconnue -> on ne parie pas
    stem_contrat = Path(str(source)).stem

    prefixe = _cache_bimdata_prefix(model_ids)
    if prefixe and stem_contrat.startswith(prefixe):
        return True
    if session_ifc_path and stem_contrat == Path(session_ifc_path).stem:
        return True

    attendus = {s for s in (_stem(ifc_path, snapshot), _stem(None, snapshot)) if s}
    attendus.discard("modele")
    return bool(attendus) and stem_contrat in attendus


def _read_contract(
    path: Path,
    expected_schema: str,
    *,
    snapshot=None,
    ifc_path: str | Path | None = None,
    session_ifc_path: str | Path | None = None,
    model_ids: tuple[str | None, ...] | None = None,
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
    if snapshot is not None and not _contract_matches_model(
        doc,
        snapshot,
        ifc_path,
        session_ifc_path=session_ifc_path,
        model_ids=model_ids,
    ):
        return None
    return doc


def _sandbox_roots() -> list[Path]:
    """Racines de lecture légitimes pour un ``.ifc``.

    L'entrée (``AUDIT_INPUT_DIR``) et l'export (``AUDIT_OUTPUT_DIR``) — ce
    dernier parce que ``download_model_ifc`` y dépose le fichier du modèle actif.
    """
    racines: list[Path] = []
    for var in ("AUDIT_INPUT_DIR", "AUDIT_OUTPUT_DIR"):
        valeur = os.getenv(var)
        if valeur:
            racines.append(Path(valeur).expanduser().resolve())
    return racines


def _validate_ifc_path(ifc_path: str | Path) -> Path:
    """Valide un ``.ifc`` **fourni par l'appelant**, jamais accepté tel quel.

    Deux étapes distinctes, pour que chaque contrôle s'applique toujours :

    1. **confinement** — le fichier doit être sous une racine autorisée. On
       réutilise les validations de la sandbox (lecture, puis export : c'est là
       que ``download_model_ifc`` dépose la maquette), avec un repli explicite
       pour le cas ci-dessous ;
    2. **contrôles propres à la maquette** — extension, fichier régulier, et
       plafond ``AUDIT_MAX_IFC_MB``.

    La séparation compte : ``safe_input_path`` refuse au-delà de
    ``AUDIT_MAX_INPUT_MB`` (50 Mo), plafond calibré pour des classeurs et des
    PDF. Une maquette réelle le dépasse largement — celle de référence pèse
    167 Mo — et ``download_model_ifc`` en accepte jusqu'à 500 Mo. Laisser le
    plafond des documents décider reviendrait à refuser tous les modèles de
    production.
    """
    cible: Path | None = None
    try:
        cible = safe_input_path(ifc_path, allowed_extensions={".ifc"})
    except UnsafePathError:
        try:
            cible = safe_export_read_path(ifc_path)
        except (UnsafePathError, OSError):
            cible = None

    if cible is None:
        # Repli : maquette trop volumineuse pour la sandbox documentaire, mais
        # légitime. Le confinement est revérifié ici, il n'est jamais relâché.
        brut = Path(ifc_path)
        if ".." in brut.parts:
            raise GeometryInputMissing(f"Chemin .ifc refusé (traversée) : {ifc_path}")
        resolu = brut.expanduser().resolve()
        racines = _sandbox_roots()
        if racines and not any(resolu.is_relative_to(r) for r in racines):
            raise GeometryInputMissing(
                f"Chemin .ifc refusé par la sandbox : {ifc_path}. Le fichier doit "
                "être sous ``AUDIT_INPUT_DIR``, ou sous ``AUDIT_OUTPUT_DIR`` s'il "
                "vient de ``download_model_ifc``."
            )
        cible = resolu

    if cible.suffix.lower() != ".ifc" or not cible.is_file():
        raise GeometryInputMissing(f"Chemin .ifc invalide ou introuvable : {ifc_path}")
    plafond_mo = int(os.getenv("AUDIT_MAX_IFC_MB", "500"))
    taille_mo = cible.stat().st_size / (1024 * 1024)
    if taille_mo > plafond_mo:
        raise GeometryInputMissing(
            f"Maquette trop volumineuse : {taille_mo:.0f} Mo > {plafond_mo} Mo "
            "(``AUDIT_MAX_IFC_MB``)."
        )
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


def _ifc_correspond(chemin: Path, prefixe: str | None, stem_modele: str | None) -> bool:
    """Ce ``.ifc`` appartient-il à la cible courante ?

    Deux formes de nom légitimes : celle du cache ``download_model_ifc``
    (identifiants BIMData en préfixe) et le nom métier du modèle actif. Sans
    l'une des deux, le fichier n'est pas rattachable à la cible — et un fichier
    non rattachable ne doit jamais servir de base de calcul.
    """
    if prefixe and chemin.stem.startswith(prefixe):
        return True
    return bool(stem_modele) and stem_modele != "modele" and chemin.stem == stem_modele


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

    prefixe = _cache_bimdata_prefix(model_ids)
    stem_modele = _stem(None, snapshot)

    if session_ifc_path:
        # Défense en profondeur : `set_active_model` remet ce champ à None,
        # mais on ne s'en remet pas à cette seule invalidation. Un chemin
        # mémorisé n'est accepté que s'il CORRESPOND à la cible courante —
        # sinon on l'ignore et la résolution continue.
        p = Path(session_ifc_path)
        if p.is_file() and _ifc_correspond(p, prefixe, stem_modele):
            return p

    candidats = _candidats_ifc()

    if prefixe:
        caches = sorted({c.resolve() for c in candidats if c.stem.startswith(prefixe)})
        if caches:
            return caches[-1]  # le plus récent (modified_date en suffixe)

    stem = stem_modele
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
            session_ifc_path=session_ifc_path,
            model_ids=model_ids,
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


def _envelope_contract_matches_request(
    doc: dict[str, Any],
    *,
    layer_pattern: str | None,
    type_pattern: str | None,
    filter_mode: str | None,
) -> bool:
    """Le contrat en cache a-t-il été produit **avec ces paramètres-là** ?

    La corrélation au modèle ne suffit pas. Un ``envelope.json`` déjà présent
    porte le résultat d'un calcul **passé**, dont les motifs, le mode et la
    version du backend peuvent différer de la demande courante — et rien, dans
    les chiffres, ne le signale : ce sont des surfaces plausibles dans les deux
    cas. Réutiliser aveuglément, c'est livrer le filtre d'hier sous les
    paramètres d'aujourd'hui.

    Trois vérifications, chacune fermant un cas observé :

    1. ``summary.methode_shab`` présent — un contrat produit avant
       ifc-geometry-mcp v0.5.0 ne déclare pas la nature de son dénominateur, et
       son ratio n'est donc pas celui que le livrable annonce ;
    2. ``diagnostics.filters`` (mode et motifs) identique à la demande ;
    3. ``source.version`` égale à la version **installée** du backend — deux
       versions peuvent rendre le même schéma sous des définitions différentes.
    """
    summary = doc.get("summary") or {}
    if not isinstance(summary, dict) or not summary.get("methode_shab"):
        return False

    diagnostics = doc.get("diagnostics") or {}
    filtres = diagnostics.get("filters") if isinstance(diagnostics, dict) else None
    if not isinstance(filtres, dict):
        return False
    if filter_mode and filtres.get("mode") != filter_mode:
        return False
    if filtres.get("layer_pattern") != layer_pattern:
        return False
    if filtres.get("type_pattern") != type_pattern:
        return False

    from ..extraction.geometry_backend import backend_version

    installee = backend_version()
    produite = (doc.get("source") or {}).get("version")
    return bool(installee) and produite == installee


def ensure_envelope_json(
    snapshot,
    *,
    ifc_path: str | Path | None = None,
    seuil_3f: float | None = None,
    layer_pattern: str | None = None,
    type_pattern: str | None = None,
    filter_mode: str | None = None,
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
            cible,
            SCHEMA_ENVELOPE_QUANTITIES_V1,
            snapshot=snapshot,
            ifc_path=ifc_path,
            session_ifc_path=session_ifc_path,
            model_ids=model_ids,
        )
        if existant is not None and _envelope_contract_matches_request(
            existant,
            layer_pattern=layer_pattern,
            type_pattern=type_pattern,
            filter_mode=filter_mode,
        ):
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
        filter_mode=filter_mode,
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
