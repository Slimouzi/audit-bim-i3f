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

import bim_reporting.excel as _bx
import xlsxwriter

from ..audit.engine import AuditResult
from ..audit.findings import ErrorType, Severity
from ..classifier import suggest_for_findings, suggestions_map
from ..profiles import DEFAULT_PROFILE_ID, get_profile
from .context import build_reference_framework
from .theming import (
    SEVERITY_COLORS,
)

#: Repli neutre quand aucun profil ne déclare de structure.
DEFAULT_REFERENCE_COLUMN_LABEL = "Référence référentiel"
DEFAULT_REFERENTIAL_SHEET_NAME = "Référentiel"

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
    (DEFAULT_REFERENCE_COLUMN_LABEL, 14),
    ("Action recommandée", 60),
]


# Préfixes interprétés par Excel comme formules — cf. OWASP « Formula Injection
# (CSV Injection) ». Le jeu de référence vit dans le socle : une seule liste,
# testée à un seul endroit. La dupliquer ici est exactement ce qui a permis à
# une copie de diverger (bim-reporting v0.1.0, corrigé en v0.1.1).
_FORMULA_TRIGGERS = _bx.FORMULA_TRIGGERS

# ── Primitives déléguées au socle générique ``bim-reporting`` ───────────
# Ré-exports directs : mêmes objets, aucun changement de comportement.
_neutralize_formula = _bx.neutralize_formula
_fmt_cell = _bx.fmt_cell
write_safe = _bx.write_safe


def _build_formats(wb: xlsxwriter.Workbook) -> dict:
    """Formats brandés BIMData (socle générique) + un format par sévérité.

    ``SEVERITY_COLORS`` est passé explicitement : le socle ne connaît pas l'enum
    ``Severity``, il ne fige donc aucune convention de gravité.
    """
    return _bx.build_formats(wb, severity_colors=SEVERITY_COLORS)


def _structure(profile_id: str | None = None):
    """Structure de classeur déclarée par le profil actif, ou ``None``."""
    return get_profile(profile_id or DEFAULT_PROFILE_ID).report_structure


def _columns_for(profile_id: str | None = None) -> list[tuple[str, int]]:
    """Colonnes des onglets de findings, en-tête de référence issu du profil.

    Le gabarit — ordre et largeurs — reste figé ici : c'est de la mise en page,
    pas du vocabulaire. Seul le libellé de la colonne de référence dépend du
    client.
    """
    spec = _structure(profile_id)
    label = spec.finding_reference_column_label if spec else DEFAULT_REFERENCE_COLUMN_LABEL
    # Repérage par le libellé de repli plutôt que par un index figé : insérer
    # une colonne ailleurs dans le gabarit ne doit pas renommer silencieusement
    # la mauvaise.
    return [
        (label, width) if header == DEFAULT_REFERENCE_COLUMN_LABEL else (header, width)
        for header, width in COLUMNS
    ]


def _referential_sheet_name(profile_id: str | None = None) -> str:
    """Nom EXACT de l'onglet de référentiel — jamais composé.

    Composer ``f"Référentiel {framework.name}"`` donnerait « Référentiel CCH BIM
    I3F » au lieu de « Référentiel I3F » : un autre gabarit, pour un gain nul.
    """
    spec = _structure(profile_id)
    return spec.referential_sheet_name if spec else DEFAULT_REFERENTIAL_SHEET_NAME


def _write_findings_sheet(
    wb,
    name: str,
    findings: list,
    fmts: dict,
    suggestions_map: dict | None = None,
    profile_id: str | None = None,
):
    """Écrit un onglet de findings. Si ``suggestions_map`` est fourni, deux
    colonnes supplémentaires (Classification proposée, Indice de confiance)
    sont ajoutées en bout de tableau, alimentées pour les findings dont
    ``element_uuid`` figure dans la map.
    """
    ws = wb.add_worksheet(name[:31])
    ws.freeze_panes(1, 0)
    columns = _columns_for(profile_id)
    if suggestions_map is not None:
        columns += [("Classification proposée", 30), ("Indice de confiance", 14)]
    for c, (label, width) in enumerate(columns):
        ws.set_column(c, c, width)
        ws.write(0, c, label, fmts["header"])
    ws.set_row(0, 28)

    for i, f in enumerate(findings, start=1):
        fmt = fmts["row_alt"] if i % 2 == 0 else fmts["row"]
        # Tout ce qui provient de la maquette / DOE / suggestion est
        # neutralisé pour interdire l'injection de formule Excel.
        values = [
            _neutralize_formula(f.element_uuid or ""),
            _neutralize_formula(f.ifc_type or ""),
            _neutralize_formula(f.name or ""),
            _neutralize_formula(f.storey or ""),
            _neutralize_formula(f.zone or ""),
            f.theme.value,
            f.error_type.value,
            f.severity.value,
            _fmt_cell(f.expected),
            _fmt_cell(f.actual),
            _neutralize_formula(f.ref_cch or ""),
            _neutralize_formula(f.recommended_action or ""),
        ]
        if suggestions_map is not None:
            sug = suggestions_map.get(f.element_uuid) if f.element_uuid else None
            if sug:
                values.append(_neutralize_formula(f"{sug['code']} — {sug['label']}"))
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

    # Les noms projet/modèle/CCH sont concaténés à du texte fixe pour
    # contextualiser, mais ils proviennent in fine de données externes
    # — neutralisation systématique en amont.
    safe_project = _neutralize_formula(project.get("name", "?"))
    safe_model = _neutralize_formula(model.get("name", "?"))
    framework = build_reference_framework(result.catalog)
    safe_cch = _neutralize_formula(framework.version or "?")
    safe_ref = _neutralize_formula(Path(result.catalog.data_spec_source or "").name or "—")

    # En-tête brandé BIMData : supertitle gris + titre principal + filet jaune d.accent sur ligne 2 (charte BIMData).
    ws.write("A1", "BIMDATA — AUDIT BIM", fmts["supertitle"])
    ws.set_row(0, 14)
    ws.write("A2", "", fmts["accent_filet"])
    ws.write("B2", "", fmts["accent_filet"])
    ws.set_row(1, 4)  # hauteur fine pour le filet jaune
    ws.write("A3", "Audit BIM — Synthèse", fmts["title"])
    ws.write("A4", f"Phase auditée : {result.phase.value}", fmts["h2"])
    ws.write("A5", f"Projet : {safe_project}")
    ws.write("A6", f"Modèle : {safe_model}")
    ws.write("A7", f"{framework.short_name or 'Référentiel'} version : {safe_cch}")
    ws.write("A8", f"Référentiel : {safe_ref}")

    # KPIs (décalés de +2 lignes pour le bandeau brandé BIMData en haut).
    ws.write("A10", "KPI global", fmts["h2"])
    kpis = [
        ("Anomalies totales", len(result.findings)),
        ("Taux de conformité (pondéré)", f"{result.conformity_rate() * 100:.1f} %"),
        ("Éléments dans le modèle", len(result.snapshot.element_by_uuid)),
        ("Pièces (IfcSpace)", len(result.snapshot.spaces)),
        ("Zones (IfcZone)", len(result.snapshot.zones)),
        ("Étages (IfcBuildingStorey)", len(result.snapshot.storeys)),
    ]
    for i, (k, v) in enumerate(kpis):
        ws.write(10 + i, 0, k, fmts["kpi_key"])
        ws.write(10 + i, 1, v, fmts["kpi_val"])

    # Détail par sévérité
    ws.write("D10", "Anomalies par sévérité", fmts["h2"])
    by_sev = result.count_by_severity()
    for i, sev in enumerate(Severity.ordered()):
        ws.write(10 + i, 3, sev.value, fmts[f"sev_{sev.value}"])
        ws.write(10 + i, 4, by_sev.get(sev.value, 0), fmts["kpi_val"])

    # Détail par thème
    ws.write("A20", "Anomalies par thème", fmts["h2"])
    for i, (theme, count) in enumerate(
        sorted(result.count_by_theme().items(), key=lambda x: -x[1])
    ):
        ws.write(20 + i, 0, theme, fmts["kpi_key"])
        ws.write(20 + i, 1, count, fmts["kpi_val"])

    # Détail par type d'erreur
    ws.write("D20", "Anomalies par type d'erreur", fmts["h2"])
    for i, (et, count) in enumerate(
        sorted(result.count_by_error_type().items(), key=lambda x: -x[1])
    ):
        ws.write(20 + i, 3, et, fmts["kpi_key"])
        ws.write(20 + i, 4, count, fmts["kpi_val"])


def _write_referential(wb, result: AuditResult, fmts: dict, profile_id: str | None = None):
    ws = wb.add_worksheet(_referential_sheet_name(profile_id)[:31])
    ws.set_column("A:A", 28)
    ws.set_column("B:B", 28)
    ws.set_column("C:C", 16)
    ws.set_column("D:D", 60)

    cat = result.catalog
    # Bandeau brandé BIMData (cf. ``_write_synthesis``).
    ws.write("A1", "BIMDATA — RÉFÉRENTIEL", fmts["supertitle"])
    ws.set_row(0, 14)
    ws.write("A2", "", fmts["accent_filet"])
    ws.write("B2", "", fmts["accent_filet"])
    ws.set_row(1, 4)
    framework = build_reference_framework(result.catalog)
    ws.write("A3", f"Référentiel {framework.name or '—'}", fmts["title"])

    row = 5
    ws.write(row, 0, "Étages admis", fmts["h2"])
    row += 1
    for s in cat.storey_names:
        ws.write(row, 0, _neutralize_formula(s.name), fmts["row"])
        row += 1

    row += 1
    ws.write(row, 0, "Types de zones", fmts["h2"])
    ws.write(row, 1, "Localisation", fmts["h2"])
    ws.write(row, 2, "Définition", fmts["h2"])
    row += 1
    for z in cat.zone_specs:
        ws.write(row, 0, _neutralize_formula(z.type_label), fmts["row"])
        ws.write(row, 1, _neutralize_formula(z.localisation), fmts["row"])
        ws.write(row, 2, _neutralize_formula(z.definition or ""), fmts["row"])
        row += 1

    row += 1
    ws.write(row, 0, "Noms de pièces", fmts["h2"])
    ws.write(row, 1, "Type", fmts["h2"])
    ws.write(row, 2, "Loc", fmts["h2"])
    ws.write(row, 3, "Surface", fmts["h2"])
    row += 1
    for r in cat.room_specs:
        ws.write(row, 0, _neutralize_formula(r.name), fmts["row"])
        ws.write(row, 1, _neutralize_formula(r.type_label or ""), fmts["row"])
        ws.write(row, 2, _neutralize_formula(r.localisation), fmts["row"])
        ws.write(row, 3, _neutralize_formula(r.surface_type or ""), fmts["row"])
        row += 1


def write_xlsx_annex(
    result: AuditResult, output_path: str | Path, *, profile_id: str | None = None
) -> Path:
    """Génère l'annexe xlsx complète.

    ``profile_id`` choisit le profil qui nomme l'onglet de référentiel et
    l'en-tête de la colonne de référence. Sans lui, le profil par défaut : le
    classeur I3F reste identique à l'octet près.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ``strings_to_formulas=False`` : ceinture *et* bretelles avec
    # ``_neutralize_formula`` — XlsxWriter n'évalue plus aucune chaîne
    # commençant par ``=`` comme formule, même si la neutralisation a
    # été oubliée sur un site d'écriture.
    wb = xlsxwriter.Workbook(str(output_path), {"strings_to_formulas": False})
    fmts = _build_formats(wb)

    _write_synthesis(wb, result, fmts)

    # Pré-calcul des suggestions de classification pour pouvoir les afficher
    # dans les onglets « Findings (tous) » et « Classification manquante ».
    suggestions_map = _build_suggestions_map(result)

    _write_findings_sheet(
        wb,
        "Findings (tous)",
        result.findings,
        fmts,
        suggestions_map=suggestions_map,
        profile_id=profile_id,
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
        _write_findings_sheet(
            wb, label_for.get(et, et), items, fmts, suggestions_map=smap, profile_id=profile_id
        )

    _write_referential(wb, result, fmts, profile_id)
    _write_classification_suggestions(wb, result, fmts)

    wb.close()
    return output_path


def _build_suggestions_map(result: AuditResult) -> dict:
    """Retourne ``{element_uuid: {code, label, confidence}}`` pour les findings
    'classification_missing' — utilisé pour décorer les onglets findings.

    On garde la suggestion *de plus haute confiance* uniquement (top 1).
    """
    return suggestions_map(result.findings, result.snapshot)


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
        ("UUID", 38),
        ("Classe IFC", 22),
        ("Nom", 32),
        ("Layers (sample)", 24),
        ("IsExternal", 10),
        ("Suggestion 1 — code", 12),
        ("Sug. 1 — libellé", 28),
        ("Conf. 1", 8),
        ("Suggestion 2 — code", 12),
        ("Sug. 2 — libellé", 28),
        ("Conf. 2", 8),
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
        # Toutes ces valeurs proviennent du suggester / des IFC layers /
        # noms d'éléments → passées par ``write_safe`` (neutralisation
        # systématique).
        write_safe(ws, i, 0, item.get("element_uuid") or "", fmt)
        write_safe(ws, i, 1, item.get("ifc_type") or "", fmt)
        write_safe(ws, i, 2, (item.get("name") or "")[:120], fmt)
        write_safe(ws, i, 3, ", ".join(item.get("layers") or [])[:120], fmt)
        write_safe(
            ws,
            i,
            4,
            "" if item.get("is_external") is None else ("oui" if item["is_external"] else "non"),
            fmt,
        )
        write_safe(ws, i, 5, s1.get("code", ""), fmt)
        write_safe(ws, i, 6, s1.get("label", ""), fmt)
        write_safe(ws, i, 7, s1.get("confidence", ""), fmt)
        write_safe(ws, i, 8, s2.get("code", ""), fmt)
        write_safe(ws, i, 9, s2.get("label", ""), fmt)
        write_safe(ws, i, 10, s2.get("confidence", ""), fmt)
        reasons = []
        for s in sugs[:2]:
            reasons.extend(s.get("reasons") or [])
        write_safe(ws, i, 11, " ; ".join(reasons)[:300], fmt)
    if suggestions:
        ws.autofilter(0, 0, len(suggestions), len(cols) - 1)
