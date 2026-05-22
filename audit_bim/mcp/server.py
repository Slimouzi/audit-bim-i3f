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
from typing import Any, Optional

from fastmcp import FastMCP

from .. import config
from ..audit.engine import AuditResult, run_audit
from ..classifier import suggest_for_findings
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

    cch_pdf: Optional[Path] = None
    data_spec_xlsx: Optional[Path] = None
    naming_spec_xlsx: Optional[Path] = None
    catalog: Optional[RequirementsCatalog] = None

    client: Optional[BIMDataClient] = None
    cloud_id: Optional[str] = None
    project_id: Optional[str] = None
    model_id: Optional[str] = None
    phase: Optional[BIMPhase] = None

    snapshot: Optional[ModelSnapshot] = None
    result: Optional[AuditResult] = None

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
            raise RuntimeError(
                "Aucune cible BIMData configurée — appelez `set_active_model`."
            )

    @classmethod
    def ensure_snapshot(cls):
        if cls.snapshot is None:
            raise RuntimeError(
                "Aucun snapshot — appelez `extract_model_snapshot`."
            )

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
def set_owner_documents(
    cch_pdf: Optional[str] = None,
    data_spec_xlsx: Optional[str] = None,
    naming_spec_xlsx: Optional[str] = None,
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

    def stat(p: Optional[Path]):
        if not p:
            return None
        return {"path": str(p), "exists": p.exists(), "size_bytes": (p.stat().st_size if p.exists() else None)}

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
    ifc_class: Optional[str] = None,
    phase: Optional[str] = None,
    theme: Optional[str] = None,
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
    cloud_id: Optional[str] = None,
    project_id: Optional[str] = None,
    model_id: Optional[str] = None,
    phase: str = "PRO",
    access_token: Optional[str] = None,
) -> dict:
    """Cible la maquette BIMData et la phase BIM à auditer.

    Args:
        cloud_id, project_id, model_id: IDs BIMData (fallback ``.env``).
        phase: APS | AVP | PRO | DCE | EXE | DOE | GESTION (défaut PRO).
        access_token: Bearer token déjà acquis (optionnel).
    """
    _State.cloud_id = cloud_id or config.CLOUD_ID
    _State.project_id = project_id or config.PROJECT_ID
    _State.model_id = model_id or config.MODEL_ID
    _State.phase = BIMPhase(phase.upper())
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
        "auth": "ok",
    }


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
    theme: Optional[str] = None,
    severity: Optional[str] = None,
    error_type: Optional[str] = None,
    ifc_type: Optional[str] = None,
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
    phase = (_State.phase.value if _State.phase else "PRO")
    base = config.AUDIT_OUTPUT_DIR / f"audit_{safe}_{phase}_{ts}"
    return Path(f"{base}.docx"), Path(f"{base}_annexes.xlsx")


@mcp.tool()
def generate_xlsx_annex(output_path: Optional[str] = None) -> dict:
    """Génère l'annexe Excel détaillée de l'audit courant."""
    _State.ensure_result()
    target = Path(output_path) if output_path else _default_output_paths()[1]
    written = write_xlsx_annex(_State.result, target)
    return {"path": str(written), "size_bytes": written.stat().st_size}


@mcp.tool()
def generate_word_report(
    output_path: Optional[str] = None,
    xlsx_annex_path: Optional[str] = None,
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
def create_smart_views(
    prefix: str = "I3F Audit — ",
    dry_run: bool = True,
) -> dict:
    """Crée (ou simule) 1 Smart View BIMData par thème en erreur.

    En mode ``dry_run`` (par défaut), renvoie les payloads JSON prêts à
    pousser, sans appel API. Mettre ``dry_run=False`` pour pousser réellement.
    """
    _State.ensure_result()
    _State.ensure_client()
    out = push_smart_views(
        _State.result, _State.client, prefix=prefix, dry_run=dry_run
    )
    return {
        "n_views": len(out),
        "dry_run": dry_run,
        "views": out,
    }


@mcp.tool()
def full_audit(
    cloud_id: Optional[str] = None,
    project_id: Optional[str] = None,
    model_id: Optional[str] = None,
    phase: str = "PRO",
    output_dir: Optional[str] = None,
    push_smart_views_now: bool = False,
    access_token: Optional[str] = None,
) -> dict:
    """Orchestrateur : parse documents → extract modèle → audit → reports → smart views.

    Args:
        cloud_id, project_id, model_id: cible BIMData (fallback ``.env``).
        phase: phase BIM auditée.
        output_dir: dossier de sortie (fallback ``AUDIT_OUTPUT_DIR`` env).
        push_smart_views_now: si ``True``, pousse les smart views réellement,
            sinon dry-run.
        access_token: bearer optionnel.
    """
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

    # 6. Smart views
    sv = push_smart_views(
        _State.result, _State.client, dry_run=not push_smart_views_now
    )

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
    sv_json = word_path.with_name(word_path.stem + "_smart_views.json")
    sv_json.write_text(
        json.dumps(sv, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    return {
        "summary": _State.result.summary(),
        "deliverables": {
            "word": str(word_written),
            "xlsx": str(xlsx_written),
            "findings_json": str(findings_json),
            "smart_views_json": str(sv_json),
        },
        "smart_views": {"n": len(sv), "pushed": push_smart_views_now},
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
