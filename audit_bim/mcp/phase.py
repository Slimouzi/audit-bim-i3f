"""Helpers de **phase** et de **contexte d'audit** — pas de tools.

Extrait de ``server.py`` (PR2 §2b). Détection/mapping de la phase d'audit BIM,
composition de la question de phase unique, suggestions de contexte issues du
snapshot actif, et validation du contexte obligatoire avant audit. Consommé par
``tools_session`` / ``tools_audit``.
"""

from __future__ import annotations

from ..requirements.models import BIMPhase
from .session import _State

_VALID_PHASES = {p.value for p in BIMPhase}

# Aide de lecture « loi MOP / mission MOE » affichée avec la question de
# phase (une seule question, pas de second champ). Éclaire l'équivalence
# entre le vocabulaire loi MOP et la phase d'audit BIM.
_PHASE_READING_AID = {
    "APS": "avant-projet sommaire",
    "AVP": "avant-projet, ou APD si le projet est en avant-projet définitif",
    "PRO": "études de projet",
    "DCE": "consultation des entreprises / dossier marché",
    "EXE": "études d'exécution, VISA, DET, ACT ou suivi chantier",
    "DOE": "dossier des ouvrages exécutés / réception",
    "GESTION": "exploitation patrimoniale",
}

# Rapprochement des jalons loi MOP / mission MOE non reconnus comme phase
# d'audit BIM vers la phase BIM la plus proche. La phase d'audit reste
# l'unique source de vérité : ce mapping ne fait que **proposer** une
# correspondance à confirmer par l'utilisateur.
_PHASE_ALIASES = {
    "ESQ": "APS",  # esquisse
    "DIA": "APS",  # diagnostic
    "APD": "AVP",  # avant-projet définitif
    "ACT": "EXE",  # assistance passation des contrats de travaux
    "VISA": "EXE",
    "DET": "EXE",  # direction de l'exécution des travaux
    "AOR": "DOE",  # assistance aux opérations de réception
}


def _map_phase(raw: str | None) -> str | None:
    """Mappe une valeur de phase brute vers une phase d'audit BIM valide.

    Renvoie la phase BIM (``APS``…``GESTION``) si ``raw`` est déjà une
    phase valide ou possède un alias loi MOP connu ; ``None`` sinon.
    """
    if not raw or not str(raw).strip():
        return None
    up = str(raw).strip().upper()
    if up in _VALID_PHASES:
        return up
    return _PHASE_ALIASES.get(up)


def _detect_snapshot_phase() -> tuple[str | None, str | None]:
    """Détecte la phase déclarée dans l'IFC / les métadonnées BIMData.

    Cherche une valeur de phase (``IfcProject.Phase`` et équivalents) dans
    les dicts ``project`` puis ``model`` du snapshot actif.

    Returns:
        ``(raw, mapped)`` où ``raw`` est la valeur brute trouvée (ex.
        ``"APD"``) et ``mapped`` la phase d'audit BIM correspondante (ex.
        ``"AVP"``) ou ``None`` si non rapprochable. ``(None, None)`` si
        aucune phase n'est déclarée.
    """
    snap = _State.snapshot
    if snap is None:
        return (None, None)
    _keys = {"phase", "bim_phase", "projectphase", "project_phase", "phase_bim"}
    for container in ((snap.project or {}), (snap.model or {})):
        for key, val in container.items():
            if str(key).strip().lower() in _keys and isinstance(val, str) and val.strip():
                raw = val.strip()
                return (raw, _map_phase(raw))
    return (None, None)


def _phase_question(detected_raw: str | None, suggested: str | None) -> str:
    """Compose l'unique question de phase (avec proposition/mapping).

    Trois cas :

    - phase détectée **reconnue** → demander confirmation explicite ;
    - phase détectée **non reconnue** mais rapprochable → proposer le
      rapprochement à confirmer/corriger ;
    - rien de détecté (ou non rapprochable) → question ouverte.
    """
    base = (
        "Quelle est la phase du projet à auditer ? "
        "Phases proposées : APS, AVP, PRO, DCE, EXE, DOE, GESTION."
    )
    if detected_raw and suggested and detected_raw.strip().upper() in _VALID_PHASES:
        return (
            f"Phase détectée dans l'IFC : « {detected_raw} ». Confirmez-vous que "
            f"l'audit doit être lancé en phase {suggested} ? (sinon, indiquez la "
            f"phase correcte parmi : APS, AVP, PRO, DCE, EXE, DOE, GESTION)"
        )
    if detected_raw and suggested:
        return (
            f"Phase détectée : « {detected_raw} ». Proposition d'audit : "
            f"{suggested}. Confirmer ou corriger (APS, AVP, PRO, DCE, EXE, "
            f"DOE, GESTION)."
        )
    if detected_raw:
        return (
            f"Phase détectée : « {detected_raw} » (non reconnue). Choisir la "
            f"phase d'audit correspondante. " + base
        )
    return base


def _phase_question_dict(detected_raw: str | None, suggested: str | None) -> dict:
    """Question de phase **unique** normalisée (clé ``project_phase``).

    Embarque l'aide de lecture loi MOP / mission MOE dans la même question
    (pas de second champ) et la proposition (``suggested_value``) issue de
    la détection IFC. Partagée par ``_validate_audit_context`` et
    ``project_context_questions`` pour éviter tout flux de phase divergent.
    """
    q: dict = {
        "key": "project_phase",
        "question": _phase_question(detected_raw, suggested),
        "aide_lecture_loi_mop": dict(_PHASE_READING_AID),
    }
    if suggested:
        q["suggested_value"] = suggested
    return q


def _snapshot_address_suggestion() -> str | None:
    """Adresse suggérée depuis le snapshot actif (``IfcBuilding.BuildingAddress``
    / ``IfcSite.SiteAddress``), ou ``None``. Best-effort, ne lève pas."""
    snap = _State.snapshot
    if snap is None:
        return None
    try:
        from ..enrichment.address import resolve_project_address

        return resolve_project_address(snap).to_query() or None
    except Exception:
        return None


def _snapshot_description() -> str | None:
    """Description projet suggérée depuis le snapshot (``project.description``
    / ``longname``), ou ``None``."""
    snap = _State.snapshot
    if snap is None:
        return None
    proj = snap.project or {}
    for key in ("description", "longname", "long_name"):
        v = proj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _snapshot_project_name() -> str | None:
    """Nom de projet exploitable pour le nommage des livrables.

    Cascade : ``IfcProject.Name`` (``project.name``) → ``project.long_name``
    → ``IfcSite.Name`` du premier site. ``None`` si rien d'exploitable.
    """
    snap = _State.snapshot
    if snap is None:
        return None
    proj = snap.project or {}
    for key in ("name", "Name", "long_name", "LongName", "longname"):
        v = proj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for site in getattr(snap, "sites", None) or []:
        v = (site or {}).get("name") or (site or {}).get("Name")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _validate_audit_context(
    *,
    project_address: str | None,
    project_phase: str | None,
    auditor_name: str | None,
    confirm_context: bool,
    project_description: str | None = None,
    require_description: bool = False,
    suggested_address: str | None = None,
    suggested_description: str | None = None,
    suggested_phase: str | None = None,
    detected_phase_raw: str | None = None,
    require_phase_confirmation: bool = False,
) -> dict | None:
    """Valide les informations de contexte obligatoires avant audit.

    Renvoie ``None`` si tout est OK ; renvoie un dict de refus
    structuré (avec ``status='needs_context'``, ``missing`` et
    ``questions``) si une info manque et que ``confirm_context``
    n'est pas mis à ``True``.

    Ne **jamais** inventer une valeur — l'utilisateur DOIT fournir (ou
    valider explicitement une **suggestion** issue de la maquette,
    fournie via ``suggested_value`` dans la question).

    ``require_description`` n'active la validation de la description que
    lorsqu'un snapshot est disponible (donc qu'on peut proposer une
    suggestion) — un ``full_audit`` « à froid » n'est pas impacté.

    Phase — question **unique** (pas de doublon loi MOP / phase BIM) :
    ``require_phase_confirmation`` force la demande de validation quand
    l'utilisateur n'a pas passé de phase explicite (on propose alors la
    phase détectée dans l'IFC via ``suggested_phase`` / ``detected_phase_raw``
    et l'aide de lecture loi MOP). La phase confirmée est l'unique source
    de vérité (audit + rapport Word + pack AVP).
    """
    missing: list[str] = []
    questions: list[dict] = []
    if not project_address or not project_address.strip():
        missing.append("project_address")
        q: dict[str, str] = {
            "key": "project_address",
            "question": (
                "Quelle est l'adresse du projet ? "
                "(ex: « 12 rue de la Paix, 35340 LIFFRÉ »). "
                "Le rapport Word affichera cette adresse comme "
                "donnée fiable, fournie par l'utilisateur."
            ),
        }
        if suggested_address:
            q["suggested_value"] = suggested_address
            q["question"] += (
                f" Suggestion extraite de la maquette (IfcPostalAddress) : "
                f"« {suggested_address} » — merci de la valider ou de la corriger."
            )
        questions.append(q)
    # Phase — question unique. On la pose si la phase est absente/invalide,
    # OU si une confirmation explicite est requise (l'utilisateur n'a pas
    # passé de phase explicite : on propose la phase détectée à valider).
    phase_valid = bool(project_phase) and project_phase.upper() in _VALID_PHASES
    if not phase_valid or require_phase_confirmation:
        missing.append("project_phase")
        questions.append(_phase_question_dict(detected_phase_raw, suggested_phase))
    if not auditor_name or not auditor_name.strip():
        missing.append("auditor_name")
        questions.append(
            {
                "key": "auditor_name",
                "question": (
                    "Sous quel nom afficher l'auditeur sur la page de garde "
                    "et dans la section « Contexte de la mission » du rapport "
                    "Word ?"
                ),
            }
        )

    # Description : validée uniquement quand un snapshot est disponible
    # (on peut alors proposer une suggestion). Un snapshot muet → question
    # sans suggestion ; pas de snapshot → on ne bloque pas.
    if require_description and (not project_description or not project_description.strip()):
        missing.append("project_description")
        q_desc: dict[str, str] = {
            "key": "project_description",
            "question": (
                "Quelle description du projet afficher dans la section "
                "« Description du projet » du rapport Word ?"
            ),
        }
        if suggested_description:
            q_desc["suggested_value"] = suggested_description
            q_desc["question"] += (
                f" Suggestion extraite de la maquette : « {suggested_description} » "
                "— à valider ou corriger."
            )
        questions.append(q_desc)

    if not missing:
        return None  # tout est OK

    if confirm_context:
        # L'utilisateur a explicitement confirmé qu'il accepte de lancer
        # malgré l'absence de certaines infos. On le laisse passer mais
        # le rapport affichera NOT_AVAILABLE pour les champs manquants.
        return None

    return {
        "status": "needs_context",
        "missing": missing,
        "questions": questions,
        "next_step": (
            "Renseigner les informations manquantes puis re-appeler le tool "
            "avec les paramètres ``project_address``, ``project_phase``, "
            "``auditor_name`` (et ``project_description`` si demandée). Les "
            "questions comportant ``suggested_value`` proposent une valeur "
            "extraite de la maquette : la faire valider ou corriger par "
            "l'utilisateur. Pour lancer malgré tout sans toutes les infos "
            "(déconseillé), passer ``confirm_context=True``."
        ),
    }
