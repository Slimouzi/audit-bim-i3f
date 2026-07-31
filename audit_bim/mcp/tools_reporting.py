"""Tools MCP — génération des livrables (Word / xlsx / pack AVP) (PR2 §2b)."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from ..reporting.context import build_report_context, merge_user_context
from ..reporting.word_report import write_word_report
from ..reporting.xlsx_annex import write_xlsx_annex
from ..safe_paths import safe_export_dir, safe_export_path, safe_input_path
from .app import mcp
from .phase import (
    _VALID_PHASES,
    _detect_snapshot_phase,
    _map_phase,
    _phase_question_dict,
    _snapshot_address_suggestion,
    _snapshot_description,
    _snapshot_project_name,
    _validate_audit_context,
)
from .session import _State

_server_logger = logging.getLogger("audit_bim.mcp.tools_reporting")


def _default_output_paths() -> tuple[Path, Path]:
    """Renvoie deux chemins relatifs (docx, xlsx) — passés ensuite à
    :func:`safe_export_path` qui les résoudra sous ``AUDIT_OUTPUT_DIR``.
    """
    project_name = (_State.snapshot.project or {}).get("name") if _State.snapshot else None
    project_name = project_name or _State.project_id or "projet"
    safe = "".join(c for c in str(project_name) if c not in r'\/:*?"<>|').strip()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    phase = _State.phase.value if _State.phase else "PRO"
    base = f"audit_{safe}_{phase}_{ts}"
    return Path(f"{base}.docx"), Path(f"{base}_annexes.xlsx")


@mcp.tool()
def generate_xlsx_annex(output_path: str | None = None, overwrite: bool = False) -> dict:
    """Génère l'annexe Excel détaillée de l'audit courant.

    Le chemin de sortie est filtré par la sandbox d'export
    (:func:`audit_bim.safe_paths.safe_export_path`) : doit rester sous
    ``AUDIT_OUTPUT_DIR`` (défaut ``./out``), sans ``..``, pas
    d'écrasement silencieux sauf ``overwrite=True``.
    """
    _State.ensure_result()
    raw = Path(output_path) if output_path else _default_output_paths()[1]
    target = safe_export_path(raw, overwrite=overwrite)
    written = write_xlsx_annex(_State.result, target)
    return {"path": str(written), "size_bytes": written.stat().st_size}


@mcp.tool()
def list_avp_i3f_xls_reports(
    include_templates: bool = True,
    require_identical: bool = False,
) -> dict:
    """Liste les rapports XLS AVP I3F **préparables** et leur disponibilité.

    Tool **sans effet de bord** : il sonde le snapshot BIMData de la session
    courante (entités IFC, BaseQuantities, relations zone/espace, calque
    d'enveloppe) et rend, pour chacun des 6 rapports MOA, un verdict :

    - ``can_generate`` : un rapport **métier** (charte BIMData) est produisible ;
    - ``can_generate_identical`` : une reproduction MOA **stricte** (formules /
      pivots / styles préservés) est produisible. **Actuellement toujours
      ``False``** : la génération réécrit des tables brandées (valeurs figées),
      le mode template MOA (copie du workbook) n'est pas encore livré — on ne
      promet donc **jamais** « à l'identique », même avec les classeurs MOA ;
    - ``status`` : ``ready`` (jamais atteint sans mode template) / ``partial``
      (générable en brandé) / ``blocked`` + ``next_action``.

    C'est l'étape à appeler **avant** ``generate_avp_i3f_pack`` : elle explique
    pourquoi un rapport est générable (partiel) ou bloqué.

    Args:
        include_templates: inclure le chemin du classeur MOA de référence
            (``template_path``) quand il existe sur le poste.
        require_identical: si ``True``, un rapport n'est ``ready`` que si la
            reproduction stricte est possible — donc **aucun** tant que le mode
            template MOA n'existe pas (tout passe ``blocked``).

    Returns:
        ``{status, project, reports: [...]}`` — ``reports`` dans l'ordre CTO.
    """
    from ..reporting.avp_availability import inspect_avp_report_availability

    snap = _State.snapshot
    availabilities = inspect_avp_report_availability(
        snap,
        sources=None,
        require_identical=require_identical,
        has_audit_result=_State.result is not None,
    )
    reports: list[dict] = []
    for av in availabilities:
        d = av.to_dict()
        if not include_templates:
            d.pop("template_path", None)
        reports.append(d)

    phase = _State.phase.value if _State.phase else None
    return {
        "status": "ok",
        "project": {
            "name": (snap.project or {}).get("name") if snap else None,
            "model": (snap.model or {}).get("name") if snap else None,
            "phase": phase,
        },
        "require_identical": require_identical,
        "reports": reports,
    }


@mcp.tool()
def generate_avp_i3f_pack(
    output_dir: str | None = None,
    controle_xlsx: str | None = None,
    shab_xlsx: str | None = None,
    zones_espaces_xlsx: str | None = None,
    enveloppe_xlsx: str | None = None,
    envelope_json: str | None = None,
    menuiseries_xlsx: str | None = None,
    plancher_xlsx: str | None = None,
    project_name: str | None = None,
    project_code: str | None = None,
    phase: str | None = None,
    auditor: str | None = None,
    usages_bim: list[str] | None = None,
    nombre_logements: str | None = None,
    temoin_virtuel: str | None = None,
    date_controle: str | None = None,
    auteur_controle: str | None = None,
    export_pdf: bool = True,
    confirm_context: bool = False,
) -> dict:
    """Génère le pack de livrables AVP I3F (charte BIMData).

    Produit les 6 Excel (Contrôle Maquettes, SHAB, Zones/Espaces, Enveloppe,
    Menuiseries, Plancher) + le rapport consolidé « Analyse BIM AVP » (.docx,
    + .pdf best-effort). Les données métier sont **maquette-first** : elles
    viennent du snapshot/audit courant et des quantités IFC extraites ou
    calculées via la chaîne IFC OpenShell. Les .xlsx MOA éventuellement fournis
    servent au contexte documentaire (identité projet, seuils, templates
    futurs), pas à remplir des colonnes issues d'outils externes.

    Nommage des livrables — convention documentaire I3F **générée à partir
    de données projet confirmées** :
    ``YYMMDD <NomProjet> <CodeProjet> <Phase> - <TypeLivrable>.<ext>``
    (``YYMMDD`` = date de génération). Le **nom du projet** est cherché dans
    les métadonnées BIMData/IFC (``project.name`` / ``IfcSite.Name``), le
    **code (ESI)** dans le contrôle maquettes I3F, la **phase** est la phase
    confirmée de l'audit (``_State.phase``). Si le nom ou le code restent
    introuvables et ne sont pas fournis, le tool renvoie
    ``{status: needs_context}`` avec les questions à poser (sauf
    ``confirm_context=True``).

    Args:
        output_dir: sous-dossier d'export (sandbox ``AUDIT_OUTPUT_DIR``).
        controle_xlsx … plancher_xlsx: chemins des .xlsx MOA/I3F de référence
            (optionnels, sandbox lecture ``safe_input_path``). Ils peuvent
            aider à résoudre l'identité projet ou des paramètres de contrôle,
            mais les surfaces/dimensions exportées viennent de la maquette IFC.
        project_name, project_code, phase: identité projet pour le nommage.
            ``None`` → résolus depuis la maquette / les sources / la phase
            d'audit confirmée ; nom ou code introuvable → ``needs_context``.
        auditor, auteur_controle: nom de l'auteur du contrôle affiché sur le
            pack. **Demandé explicitement** (``needs_context``) si aucun des
            deux n'est fourni — pas de « AMO BIM » générique par défaut, sauf
            ``confirm_context=True``. ``auteur_controle`` prime sur ``auditor``.
        usages_bim, nombre_logements, temoin_virtuel, date_controle:
            métadonnées opérationnelles du contrôle (issues du rapport I3F de
            référence) pour « Données d'entrée » / « Usages BIM 3F ». Absentes
            → « Information non disponible… ».
        export_pdf: tente la conversion .docx → .pdf (LibreOffice si présent).
        confirm_context: ``True`` pour générer malgré un nom/code/phase/auteur
            manquant.

    Returns:
        ``{output_dir, paths, analyse_docx, analyse_pdf, pdf_available}`` ou
        ``{status: needs_context, missing, questions}``.
    """
    from ..reporting.avp_i3f import write_avp_i3f_report_pack
    from ..reporting.avp_sources import AvpSourcePaths, load_sources, read_envelope_json

    if _State.snapshot is None and _State.result is None:
        return {
            "status": "needs_context",
            "missing": ["snapshot"],
            "questions": [
                {
                    "key": "snapshot",
                    "question": (
                        "Extraire la maquette active avant de générer le pack "
                        "AVP I3F (set_active_model puis extract_model_snapshot, "
                        "ou full_audit)."
                    ),
                }
            ],
            "next_step": (
                "Appeler set_active_model(...), puis extract_model_snapshot "
                "ou full_audit. Relancer ensuite generate_avp_i3f_pack : les "
                "Excel utiliseront les données IFC/OpenShell plutôt que les "
                "colonnes d'outils externes des sources."
            ),
        }

    def _src(p: str | None) -> str | None:
        return str(safe_input_path(p, allowed_extensions={".xlsx", ".xlsm"})) if p else None

    source_paths = AvpSourcePaths(
        controle=_src(controle_xlsx),
        shab=_src(shab_xlsx),
        zones_espaces=_src(zones_espaces_xlsx),
        enveloppe=_src(enveloppe_xlsx),
        menuiseries=_src(menuiseries_xlsx),
        plancher=_src(plancher_xlsx),
    )
    # Chargement unique des sources (lues aussi pour résoudre le code ESI).
    sources = load_sources(source_paths)
    # Enveloppe « logique MOA » : source structurée envelope.json (MCP ifc-geometry)
    # → onglet par_type (8 lignes métier), prioritaire sur le repli snapshot (484
    # murs) et sur le .xlsx source.
    if envelope_json:
        safe_env = safe_input_path(envelope_json, allowed_extensions={".json"})
        sources.enveloppe = read_envelope_json(safe_env)
    ctrl_header = (sources.controle.header if sources.controle else {}) or {}

    def _hdr(key: str) -> str | None:
        v = ctrl_header.get(key)
        return str(v).strip() if v not in (None, "") and str(v).strip() else None

    # ── Résolution de l'identité projet (nom / code / phase) ────────────
    # Nom : param explicite > **entête « Projet » du contrôle I3F** (source
    # livrable, autoritaire pour l'identité I3F) > métadonnées maquette.
    # ``project.name`` BIMData peut être générique (ex. « I3F ») : la source
    # de contrôle prime pour ne pas nommer les livrables de travers.
    eff_name = (project_name or "").strip() or _hdr("projet") or _snapshot_project_name()
    # Code (ESI) : param > entête « ESI » du contrôle maquettes I3F.
    eff_code = (project_code or "").strip() or _hdr("esi")
    # Phase : param explicite > phase d'audit confirmée > entête contrôle I3F.
    eff_phase = (phase or "").strip() or None
    if not eff_phase and _State.phase is not None:
        eff_phase = _State.phase.value
    if not eff_phase:
        eff_phase = _map_phase(_hdr("phase"))

    # Auteur du contrôle : I3F attend un auteur nommé (CdP BIM / auditeur
    # AMO). On **demande** explicitement plutôt que de retomber sur un
    # « AMO BIM » générique — sauf si ``auteur_controle`` ou ``auditor``
    # sont fournis, ou ``confirm_context``.
    eff_auditor = (auditor or "").strip() or None
    eff_auteur = (auteur_controle or "").strip() or None

    # Nom / code / phase obligatoires pour un livrable I3F fiable → sinon on
    # demande (jamais de valeur inventée ni de défaut silencieux).
    missing: list[str] = []
    questions: list[dict] = []
    if not eff_name:
        missing.append("project_name")
        questions.append(
            {
                "key": "project_name",
                "question": "Quel nom de projet doit apparaître dans les livrables ?",
            }
        )
    if not eff_code:
        missing.append("project_code")
        questions.append(
            {
                "key": "project_code",
                "question": (
                    "Quel code projet / ESI doit apparaître dans les livrables ? "
                    "(ex. « 0546L », visible sur le contrôle maquettes I3F)"
                ),
            }
        )
    if not eff_phase:
        # Phase unique : proposée si détectée (IFC puis entête contrôle),
        # sinon demandée — jamais défautée silencieusement sur « AVP ».
        missing.append("project_phase")
        det_raw, det_mapped = _detect_snapshot_phase()
        if not det_raw:
            hdr_phase = _hdr("phase")
            if hdr_phase:
                det_raw, det_mapped = hdr_phase, _map_phase(hdr_phase)
        questions.append(_phase_question_dict(det_raw, det_mapped))
    if not eff_auteur and not eff_auditor:
        missing.append("auteur_controle")
        questions.append(
            {
                "key": "auteur_controle",
                "question": (
                    "Quel nom afficher comme « Auteur du contrôle » sur le pack "
                    "AVP I3F ? (ex. le CdP BIM 3F, ou l'auditeur AMO — passer "
                    "``auteur_controle`` ou ``auditor``)"
                ),
            }
        )
    if missing and not confirm_context:
        return {
            "status": "needs_context",
            "missing": missing,
            "questions": questions,
            "next_step": (
                "Renseigner ``project_name`` / ``project_code`` / "
                "``project_phase`` (=``phase``) / ``auteur_controle`` (ou "
                "``auditor``) puis re-appeler ``generate_avp_i3f_pack``. Pour "
                "générer malgré tout, passer ``confirm_context=True``."
            ),
        }

    from ..reporting.avp_i3f import AvpQaError

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = safe_export_dir(output_dir or f"avp_pack_{ts}")
    try:
        pack = write_avp_i3f_report_pack(
            _State.result,  # peut être None : le pack se limite alors aux sources
            out_dir,
            sources=sources,
            # Snapshot explicite : le repli maquette s'active même sans audit
            # (ex. après verify_active_model seul, _State.result est None).
            snapshot=_State.snapshot,
            project_name=eff_name or "Projet",
            project_code=eff_code or "",
            phase=eff_phase or "AVP",
            # Auteur validé/fourni (ou repli « AMO BIM » uniquement sous
            # confirm_context — voluntary confirmation).
            auditor=eff_auditor or "AMO BIM",
            usages_bim=usages_bim,
            nombre_logements=nombre_logements,
            temoin_virtuel=temoin_virtuel,
            date_controle=date_controle,
            auteur_controle=auteur_controle,
            export_pdf=export_pdf,
        )
    except AvpQaError as exc:
        # QA gate : au moins une annexe est sortie vide alors que la
        # maquette contient des données exploitables. Statut d'erreur
        # explicite — surtout pas un livrable client vide.
        return {
            "status": "error",
            "error": "empty_deliverable",
            "empty_deliverables": exc.empty,
            "message": str(exc),
        }
    return {
        "output_dir": str(out_dir),
        "paths": [str(p) for p in pack.paths()],
        "analyse_docx": str(pack.analyse_docx),
        "analyse_pdf": str(pack.analyse_pdf) if pack.analyse_pdf else None,
        "pdf_available": pack.analyse_pdf is not None,
        "project_name": eff_name,
        "project_code": eff_code,
        "phase": eff_phase,
    }


@mcp.tool()
def generate_word_report(
    output_path: str | None = None,
    xlsx_annex_path: str | None = None,
    auditor: str = "AMO BIM (audit automatisé)",
    overwrite: bool = False,
    project_address: str | None = None,
    project_phase: str | None = None,
    auditor_name: str | None = None,
    project_description: str | None = None,
    confirm_context: bool = False,
) -> dict:
    """Génère le rapport Word d'audit (enrichi avec contexte projet).

    Le rapport Word produit inclut désormais les sections :
    *Contexte de la mission*, *Description du projet*, *Référentiels*,
    *Attendus du projet*, *Objectifs BIM*, *Liste des contrôles
    réalisés*, *Informations non disponibles*. Voir
    :mod:`audit_bim.reporting.context`.

    Trois informations contextuelles sont **recommandées** pour un
    livrable AMO BIM professionnel :

    - ``project_address`` : adresse du projet (affichée dans
      *Description du projet*).
    - ``project_phase`` : APS / APD / PRO / DCE / EXE / DOE / GESTION.
      Si fourni, écrase la phase déduite du ``AuditResult`` pour
      l'affichage. **Ne change PAS** la phase utilisée pour exécuter
      l'audit (qui a déjà tourné).
    - ``auditor_name`` : nom de l'auditeur (page de garde + section
      *Contexte de la mission*).

    Si l'une de ces 3 infos est manquante **et** ``confirm_context``
    est ``False``, le tool retourne ``{"status": "needs_context", ...}``
    avec la liste des questions à poser à l'utilisateur, sans
    régénérer le rapport.

    Args:
        output_path: Chemin de sortie (sandbox ``AUDIT_OUTPUT_DIR``).
        xlsx_annex_path: Référence à l'annexe XLSX (mise en annexe).
        auditor: Nom de l'auditeur (legacy param ; déprécié au profit
            de ``auditor_name`` qui propage dans le contexte enrichi).
        overwrite: Écraser le fichier existant.
        project_address: Adresse projet (data fiable utilisateur).
        project_phase: Phase BIM à afficher.
        auditor_name: Nom de l'auditeur enrichi.
        confirm_context: ``True`` pour passer outre la validation des
            3 champs obligatoires (rapport généré avec
            ``Information non disponible`` pour les manquants).

    Returns:
        - ``{"path": "...", "size_bytes": N}`` en cas de succès.
        - ``{"status": "needs_context", "missing": [...], "questions":
          [...]}`` si validation refusée.
    """
    _State.ensure_result()

    # Suggestions issues de la maquette pour le dialogue de contexte
    # (adresse IfcPostalAddress, description projet). Le snapshot est
    # présent (``ensure_result`` implique un audit sur snapshot).
    sugg_address = _snapshot_address_suggestion()
    sugg_description = _snapshot_description()

    # Phase — unique source de vérité. L'audit a déjà tourné : ``_State.phase``
    # est la phase confirmée. On ne re-demande une confirmation que si aucune
    # phase n'est établie (ni fournie, ni posée en session).
    explicit_phase = (
        project_phase.strip() if isinstance(project_phase, str) and project_phase.strip() else None
    )
    detected_raw, detected_mapped = _detect_snapshot_phase()
    if explicit_phase:
        eff_phase = explicit_phase
    elif _State.phase is not None:
        eff_phase = _State.phase.value
    else:
        eff_phase = detected_mapped
    require_phase_confirmation = explicit_phase is None and _State.phase is None
    suggested_phase = (
        eff_phase if eff_phase and eff_phase.upper() in _VALID_PHASES else detected_mapped
    )

    # Validation contexte
    refusal = _validate_audit_context(
        project_address=project_address,
        project_phase=eff_phase,
        auditor_name=auditor_name,
        # On passe la valeur **utilisateur brute** (pas la description du
        # snapshot) : la description est demandée puis validée/corrigée par
        # l'utilisateur, avec la description maquette proposée en suggestion.
        project_description=project_description,
        require_description=True,
        suggested_address=sugg_address,
        suggested_description=sugg_description,
        suggested_phase=suggested_phase,
        detected_phase_raw=detected_raw,
        require_phase_confirmation=require_phase_confirmation,
        confirm_context=confirm_context,
    )
    if refusal is not None:
        return refusal

    raw = Path(output_path) if output_path else _default_output_paths()[0]
    target = safe_export_path(raw, overwrite=overwrite)

    # Construire le contexte enrichi avec les inputs utilisateur. La
    # description utilisateur (si fournie) écrase la description déduite ;
    # sinon ``base_ctx`` conserve la description extraite du snapshot.
    base_ctx = build_report_context(_State.result)
    ctx = merge_user_context(
        base_ctx,
        project_address=project_address,
        project_phase=eff_phase,
        auditor_name=auditor_name,
        project_description=project_description,
    )

    # Si auditor_name fourni, on l'utilise comme display ; sinon legacy
    # param ``auditor`` reste fonctionnel (write_word_report gère la
    # priorité contexte → kwargs).
    display_auditor = auditor_name or auditor

    written = write_word_report(
        _State.result,
        target,
        auditor=display_auditor,
        xlsx_annex_path=xlsx_annex_path,
        context=ctx,
    )
    return {"path": str(written), "size_bytes": written.stat().st_size}
