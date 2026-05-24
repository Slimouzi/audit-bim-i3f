"""Annexe Excel de l'audit BIM I3F.

Structure :
- 1 onglet *Synthèse* (KPIs et graphes)
- 1 onglet *Findings (tous)* — vue exhaustive plate
- 1 onglet par *type d'erreur* (classification manquante, nommage non
  conforme, propriété manquante, etc.)
- 1 onglet *Référentiel I3F* (rappel : liste des étages, zones, pièces)

Chaque ligne d'erreur a la même structure de colonnes :
``UUID | Classe IFC | Nom | Étage | Zone | Thème | Type erreur | Sévérité |
Attendu | Réel | Référence CCH | Action recommandée``
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import xlsxwriter

from ..audit.engine import AuditResult
from ..audit.findings import ErrorType, Severity
from ..classifier import suggest_for_findings
from .theming import I3F_BLUE, I3F_BLUE_LIGHT, SEVERITY_COLORS

COLUMNS = [
    ("UUID", 38),
    ("Classe IFC", 18),
    ("Nom", 32),
    ("Étage", 18),
    ("Zone", 18),
    ("Thème", 30),
    ("Type erreur", 24),
    ("Sévérité", 12),
    ("Attendu", 50),
    ("Réel", 50),
    ("Référence CCH", 14),
    ("Action recommandée", 60),
]


def _fmt_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        sample = list(v)[:8]
        more = " …" if len(v) > 8 else ""
        return ", ".join(map(str, sample)) + more
    if isinstance(v, dict):
        return "; ".join(f"{k}={vv}" for k, vv in v.items())
    return str(v)


def _build_formats(wb: xlsxwriter.Workbook) -> dict:
    fmts = {
        "title": wb.add_format(
            {
                "bold": True,
                "font_size": 16,
                "font_color": I3F_BLUE,
                "align": "left",
            }
        ),
        "h2": wb.add_format(
            {"bold": True, "font_size": 12, "font_color": I3F_BLUE}
        ),
        "header": wb.add_format(
            {
                "bold": True,
                "bg_color": I3F_BLUE,
                "font_color": "FFFFFF",
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "text_wrap": True,
            }
        ),
        "row_alt": wb.add_format({"bg_color": I3F_BLUE_LIGHT, "border": 1, "text_wrap": True, "valign": "top"}),
        "row": wb.add_format({"border": 1, "text_wrap": True, "valign": "top"}),
        "kpi_key": wb.add_format({"bold": True, "bg_color": I3F_BLUE_LIGHT, "border": 1}),
        "kpi_val": wb.add_format({"border": 1, "align": "right"}),
        "label": wb.add_format({"bold": True}),
    }
    for sev, color in SEVERITY_COLORS.items():
        fmts[f"sev_{sev}"] = wb.add_format(
            {"bg_color": color, "font_color": "FFFFFF", "border": 1, "bold": True, "align": "center"}
        )
    return fmts


def _write_findings_sheet(
    wb,
    name: str,
    findings: list,
    fmts: dict,
    suggestions_map: Optional[dict] = None,
):
    """Écrit un onglet de findings. Si ``suggestions_map`` est fourni, deux
    colonnes supplémentaires (Classification proposée, Indice de confiance)
    sont ajoutées en bout de tableau, alimentées pour les findings dont
    ``element_uuid`` figure dans la map.
    """
    ws = wb.add_worksheet(name[:31])
    ws.freeze_panes(1, 0)
    columns = list(COLUMNS)
    if suggestions_map is not None:
        columns += [("Classification proposée", 30), ("Indice de confiance", 14)]
    for c, (label, width) in enumerate(columns):
        ws.set_column(c, c, width)
        ws.write(0, c, label, fmts["header"])
    ws.set_row(0, 28)

    for i, f in enumerate(findings, start=1):
        fmt = fmts["row_alt"] if i % 2 == 0 else fmts["row"]
        values = [
            f.element_uuid or "",
            f.ifc_type or "",
            f.name or "",
            f.storey or "",
            f.zone or "",
            f.theme.value,
            f.error_type.value,
            f.severity.value,
            _fmt_cell(f.expected),
            _fmt_cell(f.actual),
            f.ref_cch or "",
            f.recommended_action or "",
        ]
        if suggestions_map is not None:
            sug = suggestions_map.get(f.element_uuid) if f.element_uuid else None
            if sug:
                values.append(f"{sug['code']} — {sug['label']}")
                values.append(sug["confidence"])
            else:
                values.extend(["", ""])
        for c, v in enumerate(values):
            cell_fmt = fmts[f"sev_{f.severity.value}"] if c == 7 else fmt
            ws.write(i, c, v, cell_fmt)
    ws.autofilter(0, 0, max(0, len(findings)), len(columns) - 1)


def _write_synthesis(wb, result: AuditResult, fmts: dict):
    ws = wb.add_worksheet("Synthèse")
    ws.set_column("A:A", 36)
    ws.set_column("B:B", 22)
    ws.set_column("D:D", 36)
    ws.set_column("E:E", 14)

    project = result.snapshot.project or {}
    model = result.snapshot.model or {}

    ws.write("A1", "Audit BIM — I3F", fmts["title"])
    ws.write("A2", f"Phase auditée : {result.phase.value}", fmts["h2"])
    ws.write("A3", f"Projet : {project.get('name', '?')}")
    ws.write("A4", f"Modèle : {model.get('name', '?')}")
    ws.write("A5", f"CCH version : {result.catalog.cch_version or '?'}")
    ws.write("A6", f"Référentiel : {Path(result.catalog.data_spec_source or '').name or '—'}")

    # KPIs
    ws.write("A8", "KPI global", fmts["h2"])
    kpis = [
        ("Anomalies totales", len(result.findings)),
        ("Taux de conformité (pondéré)", f"{result.conformity_rate()*100:.1f} %"),
        ("Éléments dans le modèle", len(result.snapshot.element_by_uuid)),
        ("Pièces (IfcSpace)", len(result.snapshot.spaces)),
        ("Zones (IfcZone)", len(result.snapshot.zones)),
        ("Étages (IfcBuildingStorey)", len(result.snapshot.storeys)),
    ]
    for i, (k, v) in enumerate(kpis):
        ws.write(8 + i, 0, k, fmts["kpi_key"])
        ws.write(8 + i, 1, v, fmts["kpi_val"])

    # Détail par sévérité
    ws.write("D8", "Anomalies par sévérité", fmts["h2"])
    by_sev = result.count_by_severity()
    for i, sev in enumerate(Severity.ordered()):
        ws.write(8 + i, 3, sev.value, fmts[f"sev_{sev.value}"])
        ws.write(8 + i, 4, by_sev.get(sev.value, 0), fmts["kpi_val"])

    # Détail par thème
    ws.write("A18", "Anomalies par thème", fmts["h2"])
    for i, (theme, count) in enumerate(sorted(result.count_by_theme().items(), key=lambda x: -x[1])):
        ws.write(18 + i, 0, theme, fmts["kpi_key"])
        ws.write(18 + i, 1, count, fmts["kpi_val"])

    # Détail par type d'erreur
    ws.write("D18", "Anomalies par type d'erreur", fmts["h2"])
    for i, (et, count) in enumerate(sorted(result.count_by_error_type().items(), key=lambda x: -x[1])):
        ws.write(18 + i, 3, et, fmts["kpi_key"])
        ws.write(18 + i, 4, count, fmts["kpi_val"])


def _write_referential(wb, result: AuditResult, fmts: dict):
    ws = wb.add_worksheet("Référentiel I3F")
    ws.set_column("A:A", 28)
    ws.set_column("B:B", 28)
    ws.set_column("C:C", 16)
    ws.set_column("D:D", 60)

    cat = result.catalog
    ws.write("A1", "Référentiel CCH BIM I3F", fmts["title"])

    row = 3
    ws.write(row, 0, "Étages admis", fmts["h2"])
    row += 1
    for s in cat.storey_names:
        ws.write(row, 0, s.name, fmts["row"])
        row += 1

    row += 1
    ws.write(row, 0, "Types de zones", fmts["h2"])
    ws.write(row, 1, "Localisation", fmts["h2"])
    ws.write(row, 2, "Définition", fmts["h2"])
    row += 1
    for z in cat.zone_specs:
        ws.write(row, 0, z.type_label, fmts["row"])
        ws.write(row, 1, z.localisation, fmts["row"])
        ws.write(row, 2, z.definition or "", fmts["row"])
        row += 1

    row += 1
    ws.write(row, 0, "Noms de pièces", fmts["h2"])
    ws.write(row, 1, "Type", fmts["h2"])
    ws.write(row, 2, "Loc", fmts["h2"])
    ws.write(row, 3, "Surface", fmts["h2"])
    row += 1
    for r in cat.room_specs:
        ws.write(row, 0, r.name, fmts["row"])
        ws.write(row, 1, r.type_label or "", fmts["row"])
        ws.write(row, 2, r.localisation, fmts["row"])
        ws.write(row, 3, r.surface_type or "", fmts["row"])
        row += 1


def write_xlsx_annex(result: AuditResult, output_path: str | Path) -> Path:
    """Génère l'annexe xlsx complète."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = xlsxwriter.Workbook(str(output_path))
    fmts = _build_formats(wb)

    _write_synthesis(wb, result, fmts)

    # Pré-calcul des suggestions de classification pour pouvoir les afficher
    # dans les onglets « Findings (tous) » et « Classification manquante ».
    suggestions_map = _build_suggestions_map(result)

    _write_findings_sheet(
        wb, "Findings (tous)", result.findings, fmts, suggestions_map=suggestions_map
    )

    # 1 onglet par type d'erreur (humanisé)
    by_type: dict[str, list] = defaultdict(list)
    for f in result.findings:
        by_type[f.error_type.value].append(f)

    label_for = {
        ErrorType.NAMING_MISSING.value: "Nommage manquant",
        ErrorType.NAMING_INVALID_FORMAT.value: "Nommage format invalide",
        ErrorType.NAMING_NOT_IN_LIST.value: "Nommage hors liste",
        ErrorType.NAMING_TOO_LONG.value: "Nommage trop long",
        ErrorType.PROPERTY_MISSING.value: "Propriété manquante",
        ErrorType.PROPERTY_EMPTY.value: "Propriété vide",
        ErrorType.PROPERTY_TYPE_INVALID.value: "Valeur de propriété invalide",
        ErrorType.CLASSIFICATION_MISSING.value: "Classification manquante",
        ErrorType.CLASSIFICATION_INVALID.value: "Classification erronée",
        ErrorType.SPATIAL_ORPHAN.value: "Hiérarchie spatiale",
        ErrorType.SPATIAL_MISSING_QUANTITY.value: "Quantité manquante",
        ErrorType.DOCUMENT_MISSING.value: "Document manquant",
    }
    for et, items in by_type.items():
        if not items:
            continue
        # Les suggestions ne sont pertinentes que pour 'classification_missing'.
        smap = suggestions_map if et == ErrorType.CLASSIFICATION_MISSING.value else None
        _write_findings_sheet(wb, label_for.get(et, et), items, fmts, suggestions_map=smap)

    _write_referential(wb, result, fmts)
    _write_classification_suggestions(wb, result, fmts)

    wb.close()
    return output_path


def _build_suggestions_map(result: AuditResult) -> dict:
    """Retourne ``{element_uuid: {code, label, confidence}}`` pour les findings
    'classification_missing' — utilisé pour décorer les onglets findings.

    On garde la suggestion *de plus haute confiance* uniquement (top 1).
    """
    suggestions = suggest_for_findings(
        result.findings, result.snapshot, min_confidence=0.4, top_n=1
    )
    out: dict[str, dict] = {}
    for item in suggestions:
        uuid = item.get("element_uuid")
        sugs = item.get("suggestions") or []
        if not uuid or not sugs:
            continue
        out[uuid] = sugs[0]
    return out


def _write_classification_suggestions(wb, result: AuditResult, fmts: dict):
    """Onglet 'Classifications suggérées' : pour chaque élément en
    classification_missing, propose les 1-3 codes UniFormat II les plus
    probables avec confiance et signaux d'appui.
    """
    suggestions = suggest_for_findings(
        result.findings, result.snapshot, min_confidence=0.4, top_n=3
    )
    ws = wb.add_worksheet("Classifications suggérées")
    ws.freeze_panes(1, 0)
    cols = [
        ("UUID", 38), ("Classe IFC", 22), ("Nom", 32),
        ("Layers (sample)", 24), ("IsExternal", 10),
        ("Suggestion 1 — code", 12), ("Sug. 1 — libellé", 28), ("Conf. 1", 8),
        ("Suggestion 2 — code", 12), ("Sug. 2 — libellé", 28), ("Conf. 2", 8),
        ("Signaux", 60),
    ]
    for c, (lbl, w) in enumerate(cols):
        ws.set_column(c, c, w)
        ws.write(0, c, lbl, fmts["header"])
    ws.set_row(0, 28)

    for i, item in enumerate(suggestions, start=1):
        fmt = fmts["row_alt"] if i % 2 == 0 else fmts["row"]
        sugs = item.get("suggestions") or []
        s1 = sugs[0] if len(sugs) >= 1 else {}
        s2 = sugs[1] if len(sugs) >= 2 else {}
        ws.write(i, 0, item.get("element_uuid") or "", fmt)
        ws.write(i, 1, item.get("ifc_type") or "", fmt)
        ws.write(i, 2, (item.get("name") or "")[:120], fmt)
        ws.write(i, 3, ", ".join(item.get("layers") or [])[:120], fmt)
        ws.write(i, 4, "" if item.get("is_external") is None else ("oui" if item["is_external"] else "non"), fmt)
        ws.write(i, 5, s1.get("code", ""), fmt)
        ws.write(i, 6, s1.get("label", ""), fmt)
        ws.write(i, 7, s1.get("confidence", ""), fmt)
        ws.write(i, 8, s2.get("code", ""), fmt)
        ws.write(i, 9, s2.get("label", ""), fmt)
        ws.write(i, 10, s2.get("confidence", ""), fmt)
        reasons = []
        for s in sugs[:2]:
            reasons.extend(s.get("reasons") or [])
        ws.write(i, 11, " ; ".join(reasons)[:300], fmt)
    if suggestions:
        ws.autofilter(0, 0, len(suggestions), len(cols) - 1)
