"""Serveur MCP « Audit BIM I3F » — orchestrateur AMO BIM piloté par Claude.

Le serveur conserve un *état de session* léger en mémoire :
- catalogue d'exigences (chargé depuis les 3 documents MOA),
- client BIMData (auth),
- snapshot du modèle,
- résultat d'audit courant.

Chaque outil MCP travaille sur cet état et renvoie des structures
sérialisables (dict / list) compatibles avec FastMCP.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

from .. import config
from ..audit.engine import AuditResult, run_audit
from ..bcf.builder import push_bcf_topics
from ..classifier import (
    apply_classifications,
    items_from_suggestions,
    read_classifications_from_xlsx,
    suggest_for_findings,
)
from ..doe import (
    apply_matches_to_model,
    match_doe_records,
    parse_doe,
    summarize_matches,
)
from ..extraction.client import BIMDataClient
from ..extraction.model_data import ModelSnapshot, extract_snapshot
from ..reporting.word_report import write_word_report
from ..reporting.xlsx_annex import write_xlsx_annex
from ..requirements.catalog import build_catalog
from ..requirements.models import BIMPhase, RequirementsCatalog
from ..smartview.builder import push_smart_views
from .prompts import AMO_BIM_I3F_PROMPT

# ── État de session ────────────────────────────────────────────────────────


class _State:
    """Singleton léger qui porte l'état de l'audit en cours."""

    cch_pdf: Path | None = None
    data_spec_xlsx: Path | None = None
    naming_spec_xlsx: Path | None = None
    catalog: RequirementsCatalog | None = None

    client: BIMDataClient | None = None
    cloud_id: str | None = None
    project_id: str | None = None
    model_id: str | None = None
    phase: BIMPhase | None = None
    classification_system: str = "UniFormat II"
    doe_available: bool | None = None

    snapshot: ModelSnapshot | None = None
    result: AuditResult | None = None

    @classmethod
    def ensure_catalog(cls):
        if cls.catalog is None:
            raise RuntimeError(
                "Le catalogue d'exigences n'est pas chargé — appelez "
                "`parse_owner_requirements` (ou `full_audit`) au préalable."
            )

    @classmethod
    def ensure_client(cls):
        if cls.client is None:
            raise RuntimeError("Aucune cible BIMData configurée — appelez `set_active_model`.")

    @classmethod
    def ensure_snapshot(cls):
        if cls.snapshot is None:
            raise RuntimeError("Aucun snapshot — appelez `extract_model_snapshot`.")

    @classmethod
    def ensure_result(cls):
        if cls.result is None:
            raise RuntimeError("Aucun audit en cours — appelez `run_audit`.")


# ── Application MCP ────────────────────────────────────────────────────────


mcp = FastMCP("audit-bim-i3f")


# Charger un éventuel chemin par défaut depuis l'env
def _bootstrap_defaults():
    if config.I3F_CCH_PDF:
        _State.cch_pdf = Path(config.I3F_CCH_PDF)
    if config.I3F_DATA_SPEC_XLSX:
        _State.data_spec_xlsx = Path(config.I3F_DATA_SPEC_XLSX)
    if config.I3F_NAMING_SPEC_XLSX:
        _State.naming_spec_xlsx = Path(config.I3F_NAMING_SPEC_XLSX)


_bootstrap_defaults()


# ── Tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def project_context_questions() -> dict:
    """Inspecte l'état de la session et renvoie la **liste des questions** à
    poser à l'utilisateur si du contexte projet manque (phase, référentiel
    classification, CCH, disponibilité DOE).

    À appeler en début de session AVANT ``run_audit_tool`` pour s'assurer
    que l'audit est cadré. Renvoie une liste vide si tout est déjà connu.

    Returns:
        Dict ``{ready: bool, missing: [...], questions: [{key, question,
        suggestion}]}``.
    """
    questions: list[dict] = []
    missing: list[str] = []

    if _State.phase is None:
        missing.append("phase")
        questions.append(
            {
                "key": "phase",
                "question": (
                    "À quelle phase projet correspond cette maquette ? "
                    "APS, AVP, PRO, DCE, EXE, DOE ou GESTION ?"
                ),
                "suggestion": "PRO (cas le plus fréquent en cours de conception).",
            }
        )
    if _State.catalog is None and not (
        _State.cch_pdf or _State.data_spec_xlsx or _State.naming_spec_xlsx
    ):
        missing.append("cch")
        questions.append(
            {
                "key": "cch",
                "question": (
                    "Quel cahier des charges BIM dois-je appliquer ? Le CCH I3F "
                    "V3.6 par défaut, ou un référentiel projet spécifique ?"
                ),
                "suggestion": (
                    "CCH I3F V3.6 (chemins par défaut dans .env) — sinon "
                    "appelle set_owner_documents avec les chemins du référentiel."
                ),
            }
        )
    if _State.classification_system == "UniFormat II":
        # Pas vraiment manquant mais on précise le défaut au cas où
        questions.append(
            {
                "key": "classification_system",
                "question": (
                    "Quel référentiel de classification utiliser ? UniFormat II "
                    "(défaut), Omniclass, CCS, ou table 3F interne ?"
                ),
                "suggestion": "UniFormat II convient pour la majorité des projets I3F.",
                "optional": True,
            }
        )
    if _State.phase in (BIMPhase.DOE, BIMPhase.GESTION) and _State.doe_available is None:
        missing.append("doe_available")
        questions.append(
            {
                "key": "doe_available",
                "question": (
                    "Phase DOE/GESTION : disposez-vous de données DOE (Excel, "
                    "PDF, ERP/GMAO) pour enrichir la maquette ?"
                ),
                "suggestion": "Si oui, l'agent DOE → IFC pourra compléter les Psets.",
            }
        )
    if _State.client is None:
        missing.append("bimdata_target")
        questions.append(
            {
                "key": "bimdata_target",
                "question": (
                    "Quelle maquette BIMData auditer ? (cloud_id, project_id, "
                    "model_id — ou utiliser les valeurs du .env)"
                ),
                "suggestion": "Appelle set_active_model avec les bons IDs.",
            }
        )

    return {
        "ready": len([q for q in questions if not q.get("optional")]) == 0,
        "missing": missing,
        "questions": questions,
        "current_context": {
            "phase": _State.phase.value if _State.phase else None,
            "classification_system": _State.classification_system,
            "cch_pdf": str(_State.cch_pdf) if _State.cch_pdf else None,
            "model_id": _State.model_id,
            "doe_available": _State.doe_available,
        },
    }


@mcp.tool()
def set_owner_documents(
    cch_pdf: str | None = None,
    data_spec_xlsx: str | None = None,
    naming_spec_xlsx: str | None = None,
) -> dict:
    """Cible les 3 documents MOA (CCH PDF + annexe Spécifications + annexe Nommage).

    Tous les paramètres sont optionnels : on ne réécrit que ce qui est fourni.
    Les chemins déjà chargés depuis ``.env`` restent en place sinon.
    """
    if cch_pdf is not None:
        _State.cch_pdf = Path(cch_pdf) if cch_pdf else None
    if data_spec_xlsx is not None:
        _State.data_spec_xlsx = Path(data_spec_xlsx) if data_spec_xlsx else None
    if naming_spec_xlsx is not None:
        _State.naming_spec_xlsx = Path(naming_spec_xlsx) if naming_spec_xlsx else None

    def stat(p: Path | None):
        if not p:
            return None
        return {
            "path": str(p),
            "exists": p.exists(),
            "size_bytes": (p.stat().st_size if p.exists() else None),
        }

    return {
        "cch_pdf": stat(_State.cch_pdf),
        "data_spec_xlsx": stat(_State.data_spec_xlsx),
        "naming_spec_xlsx": stat(_State.naming_spec_xlsx),
    }


@mcp.tool()
def parse_owner_requirements() -> dict:
    """Lit les documents MOA chargés et produit le catalogue d'exigences.

    Returns:
        Résumé du catalogue (nb propriétés, règles, étages, zones, pièces…).
    """
    _State.catalog = build_catalog(
        cch_pdf=_State.cch_pdf,
        data_spec_xlsx=_State.data_spec_xlsx,
        naming_spec_xlsx=_State.naming_spec_xlsx,
    )
    return _State.catalog.summary()


@mcp.tool()
def get_catalog_properties(
    ifc_class: str | None = None,
    phase: str | None = None,
    theme: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Filtre les PropertySpec du catalogue (avant ou après audit)."""
    _State.ensure_catalog()
    cat = _State.catalog
    out = list(cat.properties)
    if ifc_class:
        out = [p for p in out if p.ifc_class.lower() == ifc_class.lower()]
    if theme:
        out = [p for p in out if p.theme.lower() == theme.lower()]
    if phase:
        ph = BIMPhase(phase)
        out = [p for p in out if p.required_at(ph)]
    return [p.model_dump(mode="json") for p in out[:limit]]


@mcp.tool()
def set_active_model(
    cloud_id: str | None = None,
    project_id: str | None = None,
    model_id: str | None = None,
    phase: str = "PRO",
    classification_system: str | None = None,
    access_token: str | None = None,
) -> dict:
    """Cible la maquette BIMData et la phase BIM à auditer.

    Args:
        cloud_id, project_id, model_id: IDs BIMData (fallback ``.env``).
        phase: APS | AVP | PRO | DCE | EXE | DOE | GESTION (défaut PRO).
        classification_system: référentiel à utiliser pour les
            classifications. Valeurs admises : ``UniFormat II`` (défaut) |
            ``Omniclass`` | ``CCS`` | ``3F``.
        access_token: Bearer token déjà acquis (optionnel).
    """
    from ..classifier import get_system

    _State.cloud_id = cloud_id or config.CLOUD_ID
    _State.project_id = project_id or config.PROJECT_ID
    _State.model_id = model_id or config.MODEL_ID
    _State.phase = BIMPhase(phase.upper())
    if classification_system:
        # Valide le système (raise si inconnu)
        _State.classification_system = get_system(classification_system).label
    _State.client = BIMDataClient(
        cloud_id=_State.cloud_id,
        project_id=_State.project_id,
        model_id=_State.model_id,
        access_token=access_token,
    )
    # Invalide les caches downstream
    _State.snapshot = None
    _State.result = None
    return {
        "cloud_id": _State.cloud_id,
        "project_id": _State.project_id,
        "model_id": _State.model_id,
        "phase": _State.phase.value,
        "classification_system": _State.classification_system,
        "auth": "ok",
    }


@mcp.tool()
def list_classification_systems() -> list[dict]:
    """Liste les référentiels de classification disponibles côté MCP."""
    from ..classifier import SYSTEMS

    return [
        {
            "key": k,
            "name_for_bimdata_api": v.name,
            "label": v.label,
            "description": v.description,
            "has_mapper_from_uniformat": v.map_from_uniformat is not None,
        }
        for k, v in SYSTEMS.items()
    ]


@mcp.tool()
def extract_model_snapshot() -> dict:
    """Récupère le snapshot du modèle (espaces, zones, éléments…) depuis BIMData."""
    _State.ensure_client()
    _State.snapshot = extract_snapshot(_State.client)
    return _State.snapshot.summary()


@mcp.tool()
def run_audit_tool() -> dict:
    """Joue toutes les règles d'audit et renvoie un résumé des findings."""
    _State.ensure_catalog()
    _State.ensure_snapshot()
    if _State.phase is None:
        _State.phase = BIMPhase.PRO
    _State.result = run_audit(_State.snapshot, _State.catalog, _State.phase)
    return _State.result.summary()


@mcp.tool()
def query_findings(
    theme: str | None = None,
    severity: str | None = None,
    error_type: str | None = None,
    ifc_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Filtre les findings de l'audit courant."""
    _State.ensure_result()
    items = _State.result.filter(
        theme=theme, severity=severity, error_type=error_type, ifc_type=ifc_type
    )
    return [f.model_dump(mode="json") for f in items[:limit]]


def _default_output_paths() -> tuple[Path, Path]:
    project_name = (_State.snapshot.project or {}).get("name") if _State.snapshot else None
    project_name = project_name or _State.project_id or "projet"
    safe = "".join(c for c in str(project_name) if c not in r'\/:*?"<>|').strip()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    phase = _State.phase.value if _State.phase else "PRO"
    base = config.AUDIT_OUTPUT_DIR / f"audit_{safe}_{phase}_{ts}"
    return Path(f"{base}.docx"), Path(f"{base}_annexes.xlsx")


@mcp.tool()
def generate_xlsx_annex(output_path: str | None = None) -> dict:
    """Génère l'annexe Excel détaillée de l'audit courant."""
    _State.ensure_result()
    target = Path(output_path) if output_path else _default_output_paths()[1]
    written = write_xlsx_annex(_State.result, target)
    return {"path": str(written), "size_bytes": written.stat().st_size}


@mcp.tool()
def generate_word_report(
    output_path: str | None = None,
    xlsx_annex_path: str | None = None,
    auditor: str = "AMO BIM (audit automatisé)",
) -> dict:
    """Génère le rapport Word d'audit."""
    _State.ensure_result()
    target = Path(output_path) if output_path else _default_output_paths()[0]
    written = write_word_report(
        _State.result,
        target,
        auditor=auditor,
        xlsx_annex_path=xlsx_annex_path,
    )
    return {"path": str(written), "size_bytes": written.stat().st_size}


@mcp.tool()
def suggest_classifications(
    min_confidence: float = 0.4,
    top_n: int = 3,
    limit: int = 200,
) -> list[dict]:
    """Pour chaque élément avec ``classification_missing``, propose 1-3 codes
    UniFormat II déduits de la classe IFC, des layers, des attributs, des
    Pset_*Common (IsExternal…) et des BaseQuantities.

    Args:
        min_confidence: seuil de confiance (0..1) sous lequel on n'expose pas
            de suggestion.
        top_n: nombre maximum de suggestions par élément.
        limit: cap du nombre d'éléments retournés (pour préserver le canal MCP).
    """
    _State.ensure_result()
    out = suggest_for_findings(
        _State.result.findings,
        _State.result.snapshot,
        min_confidence=min_confidence,
        top_n=top_n,
    )
    return out[:limit]


@mcp.tool()
def apply_suggested_classifications(
    min_confidence: float = 0.5,
    dry_run: bool = True,
) -> dict:
    """Applique automatiquement (mode **sans contrôle**) les classifications
    proposées par le suggester aux éléments en ``classification_missing``.

    Workflow :
    1. Récupère la suggestion top de chaque élément non classifié dont la
       confiance ≥ ``min_confidence``.
    2. Crée les classifications nécessaires au niveau projet BIMData
       (dédupliquées par code+système).
    3. Lie en bulk les classifications aux éléments via
       ``POST /classification-element``.

    Args:
        min_confidence: seuil de confiance minimum (0..1) pour appliquer une
            suggestion. Plus le seuil est haut, moins on prend de risques.
        dry_run: si ``True`` (défaut), simule sans appel POST — renvoie un
            aperçu détaillé. Mettre ``False`` pour pousser réellement.

    Returns:
        Résumé : nombre d'éléments traités, classifications créées vs
        réutilisées, liens créés, erreurs éventuelles.
    """
    _State.ensure_result()
    _State.ensure_client()
    suggestions = suggest_for_findings(
        _State.result.findings,
        _State.result.snapshot,
        min_confidence=min_confidence,
        top_n=1,
    )
    items = items_from_suggestions(suggestions, min_confidence=min_confidence)
    return apply_classifications(_State.client, items, dry_run=dry_run)


@mcp.tool()
def apply_classifications_from_xlsx(
    xlsx_path: str,
    dry_run: bool = True,
) -> dict:
    """Applique les classifications **validées par l'auditeur** dans un XLSX
    d'audit potentiellement modifié.

    L'auditeur télécharge l'annexe ``audit_*_annexes.xlsx`` (générée par
    ``generate_xlsx_annex`` / ``full_audit``), édite l'onglet
    *Classifications suggérées* en colonne « Suggestion 1 — code » :

    - laisser la valeur suggérée → la classification sera appliquée ;
    - modifier le code → on applique le code corrigé (ex: ``B2010`` → ``C1010``) ;
    - effacer la cellule → ligne ignorée (refus de la suggestion).

    Args:
        xlsx_path: chemin absolu vers l'annexe XLSX éventuellement modifiée.
        dry_run: si ``True`` (défaut), simule sans appel POST.

    Returns:
        Résumé identique à ``apply_suggested_classifications``, avec en plus
        ``n_items_read_from_xlsx`` pour traçabilité.
    """
    _State.ensure_client()
    items = read_classifications_from_xlsx(xlsx_path)
    result = apply_classifications(_State.client, items, dry_run=dry_run)
    result["n_items_read_from_xlsx"] = len(items)
    result["xlsx_path"] = xlsx_path
    return result


@mcp.tool()
def doe_enrich_model(
    doe_path: str,
    dry_run: bool = True,
    name_min_score: int = 75,
    on_conflict: str = "report",
    ocr_fallback: bool = True,
    ocr_lang: str = "fra",
) -> dict:
    """Agent DOE → IFC : lit un fichier DOE (Excel, PDF natif ou scanné),
    rapproche les équipements aux éléments IFC du modèle, et enrichit la
    maquette BIMData avec gestion des conflits.

    Workflow :

    1. **Extraction** — auto-détection du format (xlsx / pdf), avec
       fallback OCR Tesseract pour les PDF scannés.
    2. **Matching** — 4 stratégies en cascade (GUID, Tag/Mark, Nom
       fuzzy via rapidfuzz, Localisation).
    3. **Détection des conflits** — pour chaque propriété DOE,
       classification ``MATCH`` (= valeur déjà présente, skip),
       ``NEW`` (absente, à écrire), ``UPGRADE`` (présente mais vide,
       à écrire), ``CONFLICT`` (différente — voir ``on_conflict``).
    4. **Enrichissement** — écrit les Psets sur les éléments matchés.

    Conventions de colonnes (mêmes pour Excel et PDF) :

    - **Identifiants** : ``UUID`` / ``Tag`` / ``Mark`` / ``Nom`` /
      ``Type`` / ``Étage`` / ``Zone`` (insensible casse + accents).
    - **Propriétés** : ``Pset_3F.Fabricant`` ou ``Pset_3F/Fabricant``
      pour cibler un Pset précis, sinon ``Pset_DOE`` par défaut.

    Args:
        doe_path: Chemin du fichier DOE (.xlsx / .xlsm / .pdf).
        dry_run: ``True`` (défaut) → simule sans POST. Renvoie payloads
            et résumé. ``False`` pour pousser réellement les Psets.
        name_min_score: Seuil fuzzy 0–100 pour le matching par nom
            (défaut 75). Monter à 85+ pour réduire les faux positifs.
        on_conflict: Stratégie quand la maquette a déjà une valeur
            différente du DOE :

            - ``"report"`` (défaut) : **n'écrase pas**. Signale les
              conflits dans la réponse. Mode prudent recommandé.
            - ``"skip"`` : comme report mais sans détail nominal.
            - ``"overwrite"`` : écrase. À réserver au DOE autoritaire
              (post-réception, validé MOA).
        ocr_fallback: PDF scanné détecté → OCR Tesseract (défaut
            ``True``). Nécessite ``pip install audit-bim-i3f[ocr]`` +
            binaire Tesseract installé.
        ocr_lang: Langue Tesseract (défaut ``"fra"``).
    """
    _State.ensure_client()
    _State.ensure_snapshot()
    records = parse_doe(doe_path, ocr_fallback=ocr_fallback, ocr_lang=ocr_lang)
    matches = match_doe_records(records, _State.snapshot, name_min_score=name_min_score)
    summary = summarize_matches(matches)
    application = apply_matches_to_model(
        _State.client,
        matches,
        dry_run=dry_run,
        snapshot=_State.snapshot,
        on_conflict=on_conflict,
    )
    return {
        "source": doe_path,
        "summary": summary,
        "application": application,
    }


@mcp.tool()
def doe_match_only(
    doe_path: str,
    name_min_score: int = 75,
    limit: int = 50,
    ocr_fallback: bool = True,
    ocr_lang: str = "fra",
) -> dict:
    """Variante read-only de ``doe_enrich_model``.

    Parse + matche mais n'enrichit *jamais* la maquette. Utile pour
    valider la qualité des matches avant d'appliquer.

    Args:
        doe_path: Chemin du fichier DOE (.xlsx / .xlsm / .pdf).
        name_min_score: Seuil fuzzy 0–100 pour le matching par nom.
        limit: Nombre max de matches échantillonnés dans la réponse
            (les stats globales couvrent l'intégralité).
        ocr_fallback: OCR sur PDF scanné (défaut ``True``).
        ocr_lang: Langue Tesseract (défaut ``"fra"``).
    """
    _State.ensure_snapshot()
    records = parse_doe(doe_path, ocr_fallback=ocr_fallback, ocr_lang=ocr_lang)
    matches = match_doe_records(records, _State.snapshot, name_min_score=name_min_score)
    summary = summarize_matches(matches)
    sample = [m.model_dump(mode="json") for m in matches[:limit]]
    return {
        "source": doe_path,
        "n_records": len(records),
        "summary": summary,
        "sample_matches": sample,
    }


@mcp.tool()
def create_bcf_topics(
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
) -> dict:
    """Crée des BCF Topics (panneau *BCF Issues* du viewer) pour chaque thème
    d'anomalie. Workflow d'issue : ``topic_type``, ``topic_status``,
    ``priority``, ``description`` riche, ``labels``, sélection + coloration
    des éléments concernés.

    À utiliser pour le **suivi de résolution** d'anomalies (assignation,
    commentaires, changement de statut Open → In Progress → Closed).

    En ``dry_run`` (défaut), renvoie les payloads sans POST. Format
    buildingSMART standard, portable hors BIMData.
    """
    _State.ensure_result()
    _State.ensure_client()
    out = push_bcf_topics(_State.result, _State.client, prefix=prefix, dry_run=dry_run)
    return {"n_topics": len(out), "dry_run": dry_run, "topics": out}


@mcp.tool()
def create_smart_views(
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
) -> dict:
    """Crée des Smart Views (panneau *Smart Views* du viewer BIMData) pour
    chaque thème d'anomalie. Payload minimal : juste un coloring d'éléments
    par thème, sans workflow d'issue.

    À utiliser pour la **navigation 3D rapide** vers un sous-ensemble
    d'éléments. Pas d'assignation, pas de statut, pas de commentaires —
    c'est juste une vue colorée.

    En ``dry_run`` (défaut), renvoie les payloads JSON prêts à pousser, sans
    appel API. Mettre ``dry_run=False`` pour pousser réellement.
    """
    _State.ensure_result()
    _State.ensure_client()
    out = push_smart_views(_State.result, _State.client, prefix=prefix, dry_run=dry_run)
    return {
        "n_views": len(out),
        "dry_run": dry_run,
        "views": out,
    }


@mcp.tool()
def full_audit(
    cloud_id: str | None = None,
    project_id: str | None = None,
    model_id: str | None = None,
    phase: str = "PRO",
    output_dir: str | None = None,
    push_mode: str = "ask",
    access_token: str | None = None,
) -> dict:
    """Orchestrateur : parse documents → extract modèle → audit → reports.

    Pour la *publication des résultats* dans le viewer BIMData, deux régimes
    distincts sont disponibles via ``push_mode`` :

    - ``"bcf"`` : crée des **BCF Topics** (panneau *BCF Issues*) — workflow
      d'issue à résoudre avec assignation, statut, commentaires, description
      riche, sélection + coloration.
    - ``"smartview"`` : crée des **Smart Views** (panneau dédié) — vues 3D
      minimales (coloring uniquement) pour navigation rapide.
    - ``"both"`` : pousse les deux régimes.
    - ``"none"`` : ne pousse rien (dry-run, payloads conservés en JSON).
    - ``"ask"`` (défaut) : aucune publication ; renvoie une question à
      l'utilisateur pour qu'il choisisse — Claude doit demander avant de
      ré-appeler ``full_audit`` avec une valeur explicite.

    Args:
        cloud_id, project_id, model_id: cible BIMData (fallback ``.env``).
        phase: phase BIM auditée.
        output_dir: dossier de sortie (fallback ``AUDIT_OUTPUT_DIR`` env).
        push_mode: ``"ask"`` | ``"bcf"`` | ``"smartview"`` | ``"both"`` | ``"none"``.
        access_token: bearer optionnel.
    """
    mode = (push_mode or "ask").lower()
    if mode == "ask":
        return {
            "status": "needs_user_choice",
            "question": (
                "Comment veux-tu publier les résultats de l'audit dans le viewer BIMData ?"
            ),
            "options": {
                "bcf": "BCF Topics — workflow d'issues à résoudre (assignation, "
                "statut, commentaires) dans le panneau BCF Issues.",
                "smartview": "Smart Views — vues 3D colorées dans le panneau "
                "Smart Views (navigation seulement, pas de workflow).",
                "both": "Les deux — pratique pour avoir à la fois la navigation "
                "rapide (Smart Views) et le suivi de correction (BCF).",
                "none": "Ne rien publier — les payloads sont sauvegardés en JSON.",
            },
            "next_step": ("Re-appeler full_audit avec push_mode=<bcf|smartview|both|none>."),
        }
    if mode not in ("bcf", "smartview", "both", "none"):
        raise ValueError(
            f"push_mode invalide : {push_mode!r}. Attendu : "
            "'ask' | 'bcf' | 'smartview' | 'both' | 'none'."
        )

    # 1. Catalogue
    _State.catalog = build_catalog(
        cch_pdf=_State.cch_pdf,
        data_spec_xlsx=_State.data_spec_xlsx,
        naming_spec_xlsx=_State.naming_spec_xlsx,
    )

    # 2. Cible
    set_active_model(
        cloud_id=cloud_id,
        project_id=project_id,
        model_id=model_id,
        phase=phase,
        access_token=access_token,
    )

    # 3. Snapshot
    _State.snapshot = extract_snapshot(_State.client)

    # 4. Audit
    _State.result = run_audit(_State.snapshot, _State.catalog, _State.phase)

    # 5. Livrables
    if output_dir:
        config.AUDIT_OUTPUT_DIR = Path(output_dir).resolve()
    word_path, xlsx_path = _default_output_paths()
    xlsx_written = write_xlsx_annex(_State.result, xlsx_path)
    word_written = write_word_report(_State.result, word_path, xlsx_annex_path=xlsx_written)

    # 6. Publication selon le mode
    bcf_result, sv_result = [], []
    do_push_bcf = mode in ("bcf", "both")
    do_push_sv = mode in ("smartview", "both")
    bcf_result = push_bcf_topics(_State.result, _State.client, dry_run=not do_push_bcf)
    sv_result = push_smart_views(_State.result, _State.client, dry_run=not do_push_sv)

    # 7. JSON machine
    findings_json = word_path.with_name(word_path.stem + "_findings.json")
    findings_json.write_text(
        json.dumps(
            [f.model_dump(mode="json") for f in _State.result.findings],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    bcf_json = word_path.with_name(word_path.stem + "_bcf_topics.json")
    bcf_json.write_text(
        json.dumps(bcf_result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    sv_json = word_path.with_name(word_path.stem + "_smart_views.json")
    sv_json.write_text(
        json.dumps(sv_result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    return {
        "summary": _State.result.summary(),
        "deliverables": {
            "word": str(word_written),
            "xlsx": str(xlsx_written),
            "findings_json": str(findings_json),
            "bcf_topics_json": str(bcf_json),
            "smart_views_json": str(sv_json),
        },
        "push_mode": mode,
        "bcf_topics": {"n": len(bcf_result), "pushed": do_push_bcf},
        "smart_views": {"n": len(sv_result), "pushed": do_push_sv},
    }


# ── Prompt MCP ─────────────────────────────────────────────────────────────


@mcp.prompt()
def amo_bim_i3f() -> str:
    """Persona AMO BIM I3F — chargée par Claude au démarrage du serveur."""
    return AMO_BIM_I3F_PROMPT


def main() -> None:
    """Point d'entrée du serveur MCP (lance la boucle stdio)."""
    mcp.run()


if __name__ == "__main__":
    main()
