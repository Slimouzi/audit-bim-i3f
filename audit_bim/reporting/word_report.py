"""Rapport d'audit Word (livrable AMO BIM I3F).

Structure du document :
1. Page de garde (titre, programme, phase, date, auditeur)
2. Résumé exécutif (KPIs + verdict global)
3. Méthodologie et périmètre
4. Synthèse par thème (camembert + tableau)
5. Synthèse par sévérité (barres + tableau)
6. Détail des anomalies (groupées par thème, paginées si volumineuses)
7. Recommandations
8. Annexes (renvoi vers le xlsx détaillé)

Les graphes sont générés via matplotlib et insérés en PNG.
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from ..audit.engine import AuditResult
from ..audit.findings import Finding, Severity
from .theming import I3F_BLUE, I3F_GREY, SEVERITY_COLORS, THEME_COLORS

MAX_FINDINGS_DETAIL = 200  # cap pour ne pas exploser le docx


def _hex_to_rgb(h: str) -> RGBColor:
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _shade_cell(cell, hex_color: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def _add_heading(doc: Document, text: str, level: int = 1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = _hex_to_rgb(I3F_BLUE)
    return h


def _pie_chart(values: dict[str, int], colors_map: dict[str, str], title: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(5.5, 4.5), dpi=140)
    labels = list(values.keys())
    sizes = list(values.values())
    colors = [f"#{colors_map.get(l, '888888')}" for l in labels]
    if sum(sizes) == 0:
        ax.text(0.5, 0.5, "Aucune anomalie", ha="center", va="center")
        ax.axis("off")
    else:
        ax.pie(
            sizes,
            labels=labels,
            colors=colors,
            autopct="%1.0f%%",
            startangle=90,
            textprops={"fontsize": 9},
        )
        ax.axis("equal")
    ax.set_title(title, fontsize=11)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _bar_chart(values: dict[str, int], colors_map: dict[str, str], title: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(6.5, 3.5), dpi=140)
    labels = list(values.keys())
    sizes = list(values.values())
    colors = [f"#{colors_map.get(l, '888888')}" for l in labels]
    ax.bar(labels, sizes, color=colors)
    for i, v in enumerate(sizes):
        ax.text(i, v, str(v), ha="center", va="bottom", fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.set_ylabel("Nb anomalies")
    plt.xticks(rotation=20, ha="right", fontsize=9)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _section_break(doc: Document):
    doc.add_page_break()


def _kpi_table(doc: Document, kpis: list[tuple[str, str]]):
    tbl = doc.add_table(rows=len(kpis), cols=2)
    tbl.autofit = True
    for i, (k, v) in enumerate(kpis):
        row = tbl.rows[i]
        c0, c1 = row.cells
        c0.text = k
        c1.text = str(v)
        c0.width = Cm(8)
        c1.width = Cm(6)
        _shade_cell(c0, "D9E2F3")
        for run in c0.paragraphs[0].runs:
            run.bold = True


def _findings_table(doc: Document, items: Iterable[Finding]):
    items = list(items)
    if not items:
        doc.add_paragraph("Aucune anomalie pour ce thème.").italic = True
        return
    tbl = doc.add_table(rows=1, cols=5)
    tbl.style = "Light Grid Accent 1"
    hdr = tbl.rows[0].cells
    hdr[0].text = "Sév."
    hdr[1].text = "Classe IFC"
    hdr[2].text = "Élément"
    hdr[3].text = "Attendu"
    hdr[4].text = "Réel"
    for c in hdr:
        _shade_cell(c, I3F_BLUE)
        for p in c.paragraphs:
            for r in p.runs:
                r.font.color.rgb = RGBColor(255, 255, 255)
                r.bold = True

    for f in items:
        row = tbl.add_row().cells
        row[0].text = f.severity.value
        _shade_cell(row[0], SEVERITY_COLORS[f.severity.value])
        for r in row[0].paragraphs[0].runs:
            r.font.color.rgb = RGBColor(255, 255, 255)
            r.bold = True
        row[1].text = f.ifc_type or ""
        row[2].text = (f.name or f.element_uuid or "")[:40]
        exp = f.expected
        if isinstance(exp, list):
            exp = ", ".join(map(str, exp[:5])) + ("…" if len(exp) > 5 else "")
        row[3].text = str(exp or "")[:80]
        row[4].text = str(f.actual or "")[:60]


def write_word_report(
    result: AuditResult,
    output_path: str | Path,
    auditor: str = "AMO BIM (audit automatisé)",
    xlsx_annex_path: str | Path | None = None,
) -> Path:
    """Génère le rapport Word d'audit."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)
    style.font.color.rgb = _hex_to_rgb(I3F_GREY)

    project_name = (result.snapshot.project or {}).get("name", "?")
    model_name = (result.snapshot.model or {}).get("name", "?")

    # 1. Page de garde
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("\n\n\nAUDIT BIM\n")
    run.bold = True
    run.font.size = Pt(28)
    run.font.color.rgb = _hex_to_rgb(I3F_BLUE)
    run = p.add_run("Cahier des Charges BIM I3F (CCH)\n")
    run.font.size = Pt(14)
    run.font.color.rgb = _hex_to_rgb(I3F_BLUE)
    run = p.add_run(f"Version référentiel : {result.catalog.cch_version or '—'}\n")
    run.font.size = Pt(11)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(f"\n\nProgramme : {project_name}\n")
    run.bold = True
    run.font.size = Pt(16)
    p.add_run(f"Modèle audité : {model_name}\n").font.size = Pt(12)
    p.add_run(f"Phase BIM : {result.phase.value}\n").font.size = Pt(12)
    p.add_run(f"Date : {date.today().isoformat()}\n").font.size = Pt(11)
    p.add_run(f"Auditeur : {auditor}\n").font.size = Pt(11)

    _section_break(doc)

    # 2. Résumé exécutif
    _add_heading(doc, "1. Résumé exécutif", level=1)
    by_sev = result.count_by_severity()
    by_theme = result.count_by_theme()

    conf = result.conformity_rate() * 100
    verdict = (
        "Conforme avec réserves légères" if conf >= 90 else
        "Non conforme — corrections nécessaires" if conf >= 70 else
        "Non conforme — anomalies majeures"
    )

    _kpi_table(doc, [
        ("Phase auditée", result.phase.value),
        ("Programme", project_name),
        ("Modèle", model_name),
        ("Référentiel", f"CCH BIM I3F V{result.catalog.cch_version or '?'}"),
        ("Nombre d'anomalies", str(len(result.findings))),
        ("Taux de conformité (pondéré)", f"{conf:.1f} %"),
        ("Verdict", verdict),
        ("CRITICAL", str(by_sev.get("CRITICAL", 0))),
        ("HIGH", str(by_sev.get("HIGH", 0))),
        ("MEDIUM", str(by_sev.get("MEDIUM", 0))),
        ("LOW", str(by_sev.get("LOW", 0))),
        ("INFO", str(by_sev.get("INFO", 0))),
    ])

    doc.add_paragraph()
    doc.add_picture(
        _pie_chart(by_theme, THEME_COLORS, "Répartition des anomalies par thème"),
        width=Cm(13),
    )
    doc.add_picture(
        _bar_chart(
            {s.value: by_sev.get(s.value, 0) for s in Severity.ordered()},
            SEVERITY_COLORS,
            "Anomalies par sévérité",
        ),
        width=Cm(15),
    )

    _section_break(doc)

    # 3. Méthodologie
    _add_heading(doc, "2. Méthodologie et périmètre", level=1)
    doc.add_paragraph(
        "L'audit est conduit conformément au Cahier des Charges BIM I3F "
        f"(version {result.catalog.cch_version or '—'}). Les exigences sont "
        "extraites de trois sources :"
    )
    doc.add_paragraph(
        "• Cahier des annexes CCH (PDF) — référence éditoriale et listes de valeurs ;",
        style="List Bullet",
    )
    doc.add_paragraph(
        "• Annexe « Spécification des données » (XLSX) — propriétés requises par "
        "objet IFC et par phase BIM ;",
        style="List Bullet",
    )
    doc.add_paragraph(
        "• Annexe « Nommage » (XLSX) — règles de nommage des sites, bâtiments, "
        "étages, zones et pièces.",
        style="List Bullet",
    )
    doc.add_paragraph(
        f"Le périmètre audité est la maquette « {model_name} » du programme "
        f"« {project_name} », exposée via l'API BIMData. La phase BIM retenue est "
        f"{result.phase.value}."
    )
    doc.add_paragraph(
        "Les contrôles couvrent : hiérarchie spatiale, nommage IFC (site / "
        "bâtiment / étage / zone / pièce), classifications, propriétés "
        "(Psets attendus à la phase), quantités (surfaces et volumes) et "
        "documents de référence."
    )

    # 4. Synthèse par thème
    _add_heading(doc, "3. Synthèse par thème", level=1)
    if not by_theme:
        doc.add_paragraph("Aucune anomalie détectée — la maquette est conforme.")
    else:
        tbl = doc.add_table(rows=1, cols=2)
        tbl.style = "Light Grid Accent 1"
        h = tbl.rows[0].cells
        h[0].text = "Thème"
        h[1].text = "Nb anomalies"
        for c in h:
            _shade_cell(c, I3F_BLUE)
            for p in c.paragraphs:
                for r in p.runs:
                    r.font.color.rgb = RGBColor(255, 255, 255)
                    r.bold = True
        for theme, count in sorted(by_theme.items(), key=lambda x: -x[1]):
            row = tbl.add_row().cells
            row[0].text = theme
            row[1].text = str(count)

    _section_break(doc)

    # 5. Détail par thème
    _add_heading(doc, "4. Détail des anomalies par thème", level=1)
    by_theme_findings: dict[str, list[Finding]] = {}
    for f in result.findings[:MAX_FINDINGS_DETAIL]:
        by_theme_findings.setdefault(f.theme.value, []).append(f)

    if len(result.findings) > MAX_FINDINGS_DETAIL:
        doc.add_paragraph(
            f"⚠ Détail limité aux {MAX_FINDINGS_DETAIL} premières anomalies pour "
            "préserver la lisibilité — l'annexe Excel contient l'exhaustif.",
            style="Intense Quote",
        )

    for theme, items in by_theme_findings.items():
        _add_heading(doc, theme, level=2)
        _findings_table(doc, items)

    _section_break(doc)

    # 6. Recommandations
    _add_heading(doc, "5. Recommandations", level=1)
    recs = _generate_recommendations(result)
    if not recs:
        doc.add_paragraph(
            "Aucune action corrective majeure ne semble nécessaire à ce stade."
        )
    else:
        for r in recs:
            doc.add_paragraph(r, style="List Bullet")

    # 7. Annexes
    _add_heading(doc, "6. Annexes", level=1)
    if xlsx_annex_path:
        doc.add_paragraph(
            f"Annexe détaillée (Excel) : « {Path(xlsx_annex_path).name} ». "
            "Cette annexe contient l'intégralité des anomalies par type "
            "d'erreur, exploitables directement par les équipes de projet."
        )
    doc.add_paragraph(
        "Référentiel CCH I3F : voir documents transmis par la maîtrise "
        "d'ouvrage (Cahier des annexes, annexe Spécifications, annexe Nommage)."
    )

    doc.save(str(output_path))
    return output_path


def _generate_recommendations(result: AuditResult) -> list[str]:
    """Recommandations stratégiques (haut niveau), dérivées des findings agrégés."""
    recs: list[str] = []
    by_type = result.count_by_error_type()
    n_class_missing = by_type.get("classification_missing", 0)
    n_naming = sum(
        by_type.get(t, 0)
        for t in (
            "naming_missing",
            "naming_invalid_format",
            "naming_not_in_list",
            "naming_too_long",
        )
    )
    n_prop_missing = by_type.get("property_missing", 0)
    n_quantity = by_type.get("spatial_missing_quantity", 0)

    if n_naming:
        recs.append(
            f"Reprendre le nommage de {n_naming} éléments — aligner sur les "
            "listes fermées du chapitre 6.3 du CCH (étages, types de zones, "
            "noms de pièces) avant la livraison suivante."
        )
    if n_class_missing:
        recs.append(
            f"Compléter la classification IFC sur {n_class_missing} composants "
            "(UniFormat / Omniclass / table interne 3F) — pré-requis "
            "indispensable pour l'exploitation DOE/GMAO."
        )
    if n_prop_missing:
        recs.append(
            f"Renseigner les {n_prop_missing} propriétés manquantes par rapport "
            f"au cahier des données pour la phase {result.phase.value} "
            "(Pset_SpaceCommon, Pset_3F, attributs natifs, surfaces…)."
        )
    if n_quantity:
        recs.append(
            f"Compléter les quantités (NetFloorArea / BaseQuantities) sur "
            f"{n_quantity} pièces afin de permettre les contrôles SHAB / SU."
        )
    if result.conformity_rate() < 0.7:
        recs.append(
            "Ré-itérer un audit après reprise — l'écart au CCH est important : "
            "prévoir une revue conjointe MOA / MOE avant la prochaine phase."
        )
    return recs
