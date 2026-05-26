"""Rapport d'audit Word (livrable AMO BIM I3F).

Structure du document (enrichie depuis 0.2.2) :

1. Page de garde
2. Résumé exécutif
3. Contexte de la mission (NOUVEAU)
4. Description du projet (NOUVEAU)
5. Référentiels et documents analysés
6. Attendus du projet (NOUVEAU)
7. Objectifs BIM (NOUVEAU)
8. Liste des contrôles réalisés (NOUVEAU)
9. Synthèse par thème (camembert + tableau)
10. Détail des anomalies par thème
11. Recommandations AMO BIM (enrichies)
12. Informations non disponibles (NOUVEAU si applicable)
13. Annexes

Les nouvelles sections (3, 4, 6, 7, 8, 12) sont alimentées par
:class:`audit_bim.reporting.context.ReportProjectContext`. Si aucune
information n'est disponible pour une section donnée, la mention
« Information non disponible dans les documents fournis. » est
affichée — **on n'invente jamais**.

Les graphes sont générés via matplotlib et insérés en PNG.
"""

from __future__ import annotations

import io
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from ..audit.engine import AuditResult
from ..audit.findings import Finding, Severity, Theme
from ..classifier import suggest_for_findings
from .context import ReportProjectContext, build_report_context
from .korhus_brand import find_logo
from .theming import (
    I3F_BLUE,
    I3F_BLUE_LIGHT,
    I3F_GREY,
    KORHUS_FONT_FALLBACK,
    KORHUS_FONT_PRIMARY,
    KORHUS_GRANITE_LIGHT,
    KORHUS_PRIMARY,
    KORHUS_SECONDARY,
    KORHUS_TERTIARY,
    KORHUS_WHITE,
    SEVERITY_COLORS,
    THEME_COLORS,
)

# Phrase de fallback : utilisée chaque fois qu'une donnée contextuelle
# manque, pour éviter toute hallucination et garder un ton AMO BIM.
NOT_AVAILABLE = "Information non disponible dans les documents fournis."

# Suffixe affiché en fin de valeur pour les données extraites des
# sources documentaires sans validation utilisateur. Indique au
# lecteur que la valeur est issue d'une déduction automatique et
# doit être confirmée par la MOA / MOE.
SOURCE_SUFFIX_EXTRACTED = "(déduit de la maquette — à confirmer)"
SOURCE_SUFFIX_DEDUCED = "(déduit par heuristique — à confirmer)"


def _render_with_source(value: str, source: str) -> str:
    """Ajoute un suffixe de traçabilité selon la source du champ.

    - ``"user"`` → valeur brute (fiable, fournie par l'utilisateur).
    - ``"extracted"`` → valeur + ``(déduit de la maquette — à confirmer)``.
    - ``"deduced"`` → valeur + ``(déduit par heuristique — à confirmer)``.
    - autre / ``"missing"`` → valeur brute (le caller a déjà géré le None).
    """
    if not value:
        return value
    if source == "extracted":
        return f"{value} {SOURCE_SUFFIX_EXTRACTED}"
    if source == "deduced":
        return f"{value} {SOURCE_SUFFIX_DEDUCED}"
    return value


MAX_FINDINGS_PER_THEME = 25  # cap par thème pour garder un rendu équilibré
PIE_OTHER_THRESHOLD = 0.02  # tranches < 2 % regroupées en « Autres »


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
    """H1/H2/... colorés en Korhus Primary, font Roboto/Arial.

    Pour les H1, on ajoute un filet d'accent cyan (Korhus Secondary)
    sous le titre — la marque demande explicitement le cyan en accent,
    pas en couleur dominante.
    """
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = _hex_to_rgb(KORHUS_PRIMARY)
        run.font.name = KORHUS_FONT_PRIMARY
        # rFonts est nécessaire pour que Word applique vraiment la
        # police (le nom dans run.font.name ne suffit pas seul).
        rpr = run._element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:ascii"), KORHUS_FONT_PRIMARY)
        rfonts.set(qn("w:hAnsi"), KORHUS_FONT_PRIMARY)
        rfonts.set(qn("w:cs"), KORHUS_FONT_FALLBACK)
    if level == 1:
        # Filet d'accent cyan : paragraphe minuscule entièrement shadé.
        accent = doc.add_paragraph()
        accent.paragraph_format.space_before = Pt(0)
        accent.paragraph_format.space_after = Pt(6)
        pPr = accent._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), KORHUS_SECONDARY)
        pPr.append(shd)
        # On force une hauteur de ligne ultra-courte pour obtenir un filet.
        run = accent.add_run(" ")
        run.font.size = Pt(2)
    return h


def _pie_chart(values: dict[str, int], colors_map: dict[str, str], title: str) -> io.BytesIO:
    """Camembert avec regroupement des tranches < 2 % en « Autres » et légende externe.

    Les labels en bordure se chevauchent dès qu'on a plusieurs tranches < 1 % ;
    on bascule donc sur une légende latérale pour rester lisible.
    """
    fig, ax = plt.subplots(figsize=(7.0, 4.5), dpi=140)
    total = sum(values.values())
    if total == 0:
        ax.text(0.5, 0.5, "Aucune anomalie", ha="center", va="center")
        ax.axis("off")
        ax.set_title(title, fontsize=11)
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf

    # Trier décroissant + grouper les tranches négligeables
    items = sorted(values.items(), key=lambda kv: -kv[1])
    big: list[tuple[str, int]] = []
    small_sum = 0
    for k, v in items:
        if v / total < PIE_OTHER_THRESHOLD:
            small_sum += v
        else:
            big.append((k, v))
    if small_sum > 0:
        big.append(("Autres", small_sum))

    labels = [k for k, _ in big]
    sizes = [v for _, v in big]
    colors = [f"#{colors_map.get(lbl, 'BFBFBF')}" for lbl in labels]

    # Affiche % directement sur les tranches mais pas les labels (légende externe)
    wedges, _texts, autotexts = ax.pie(
        sizes,
        colors=colors,
        autopct=lambda pct: f"{pct:.0f}%" if pct >= 3 else "",
        startangle=90,
        textprops={"fontsize": 9, "color": "white", "weight": "bold"},
        pctdistance=0.72,
    )
    ax.axis("equal")
    ax.set_title(title, fontsize=11)

    # Légende externe avec libellé + valeur absolue
    legend_labels = [
        f"{lbl}  ({s:,})".replace(",", " ") for lbl, s in zip(labels, sizes, strict=True)
    ]
    ax.legend(
        wedges,
        legend_labels,
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
        fontsize=9,
        frameon=False,
    )

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
    colors = [f"#{colors_map.get(lbl, '888888')}" for lbl in labels]
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
    """Attache un saut de page au dernier paragraphe existant.

    Évite la création d'un paragraphe vide additionnel — qui se rend en marge
    gauche dans certains visionneurs (Quick Look macOS, par ex.) comme un
    petit marqueur indésirable.
    """
    if doc.paragraphs:
        last = doc.paragraphs[-1]
        run = last.add_run()
        run.add_break(WD_BREAK.PAGE)
    else:
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
        # Colonne libellé sur fond Blue Neutral Light (charte Korhus).
        _shade_cell(c0, I3F_BLUE_LIGHT)
        for run in c0.paragraphs[0].runs:
            run.bold = True


def _findings_table(
    doc: Document,
    items: Iterable[Finding],
    suggestions_map: dict | None = None,
):
    """Tableau Word des findings.

    Si ``suggestions_map`` est fourni (typiquement pour le thème
    *Classification IFC*), deux colonnes supplémentaires sont ajoutées :
    *Suggestion* (code + label UniFormat) et *Conf.* (indice de confiance).
    """
    items = list(items)
    if not items:
        doc.add_paragraph("Aucune anomalie pour ce thème.").italic = True
        return
    with_sug = suggestions_map is not None
    ncols = 7 if with_sug else 5
    tbl = doc.add_table(rows=1, cols=ncols)
    tbl.style = "Light Grid Accent 1"
    headers = ["Sév.", "Classe IFC", "Élément", "Attendu", "Réel"]
    if with_sug:
        headers += ["Suggestion", "Conf."]
    hdr = tbl.rows[0].cells
    for i, txt in enumerate(headers):
        hdr[i].text = txt
        _shade_cell(hdr[i], I3F_BLUE)
        for p in hdr[i].paragraphs:
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
        if with_sug:
            sug = suggestions_map.get(f.element_uuid) if f.element_uuid else None
            if sug:
                row[5].text = f"{sug['code']} — {sug['label']}"
                row[6].text = f"{sug['confidence']:.2f}"
            else:
                row[5].text = ""
                row[6].text = ""


def _write_cover_page(
    doc: Document,
    *,
    project_name: str,
    model_name: str,
    phase_value: str,
    cch_version: str | None,
    auditor: str,
) -> None:
    """Rend la page de couverture brandée Korhus.

    Structure :

    - **Hero sombre** (Korhus Primary ``#0C101B``) : logo Korhus
      (variante claire/inversée) centré, supertitle « AUDIT BIM » en
      cyan accent, titre du programme en blanc.
    - **Filet cyan** plein-largeur (Korhus Secondary).
    - **Bloc métadonnées** (Blue Neutral Light) : modèle, phase,
      référentiel, date, auditeur — alignés gauche, hiérarchie nette.
    """
    # ── Hero sombre ───────────────────────────────────────────────────
    hero = doc.add_table(rows=1, cols=1)
    hero.autofit = False
    hero_cell = hero.rows[0].cells[0]
    hero_cell.width = Cm(17)
    _shade_cell(hero_cell, KORHUS_PRIMARY)
    # Vider le paragraphe par défaut puis ajouter notre contenu.
    hero_cell.text = ""

    # Logo Korhus (variante claire/inversée pour fond sombre).
    logo_path = find_logo("light")
    logo_para = hero_cell.paragraphs[0]
    logo_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    logo_para.paragraph_format.space_before = Pt(36)
    if logo_path is not None:
        # Si le logo est introuvable on dégrade en wordmark texte.
        run = logo_para.add_run()
        try:
            run.add_picture(str(logo_path), width=Cm(6.5))
        except Exception:
            # Fichier corrompu ou format inattendu : fallback texte.
            run.text = "KORHUS.AI"
            run.font.color.rgb = _hex_to_rgb(KORHUS_WHITE)
            run.font.size = Pt(22)
            run.bold = True
    else:
        run = logo_para.add_run("KORHUS.AI")
        run.font.color.rgb = _hex_to_rgb(KORHUS_WHITE)
        run.font.size = Pt(22)
        run.bold = True

    # Espacement.
    spacer = hero_cell.add_paragraph()
    spacer.paragraph_format.space_after = Pt(10)

    # Supertitle cyan.
    supertitle = hero_cell.add_paragraph()
    supertitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = supertitle.add_run("AUDIT BIM")
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = _hex_to_rgb(KORHUS_SECONDARY)

    # Titre principal blanc.
    title = hero_cell.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(project_name)
    run.bold = True
    run.font.size = Pt(28)
    run.font.color.rgb = _hex_to_rgb(KORHUS_WHITE)

    # Sous-titre référentiel (blanc cassé via tertiaire).
    subtitle = hero_cell.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(48)
    run = subtitle.add_run(f"Conformité au Cahier des Charges BIM I3F — V{cch_version or '—'}")
    run.font.size = Pt(12)
    run.font.color.rgb = _hex_to_rgb(KORHUS_TERTIARY)

    # ── Filet cyan ────────────────────────────────────────────────────
    accent = doc.add_table(rows=1, cols=1)
    accent_cell = accent.rows[0].cells[0]
    accent_cell.width = Cm(17)
    _shade_cell(accent_cell, KORHUS_SECONDARY)
    accent_para = accent_cell.paragraphs[0]
    accent_para.paragraph_format.space_before = Pt(0)
    accent_para.paragraph_format.space_after = Pt(0)
    accent_run = accent_para.add_run(" ")
    accent_run.font.size = Pt(2)

    # ── Bloc métadonnées sur fond clair ───────────────────────────────
    meta = doc.add_table(rows=1, cols=1)
    meta_cell = meta.rows[0].cells[0]
    meta_cell.width = Cm(17)
    _shade_cell(meta_cell, I3F_BLUE_LIGHT)
    meta_cell.text = ""

    def _meta_line(label: str, value: str) -> None:
        para = meta_cell.add_paragraph()
        para.paragraph_format.space_before = Pt(2)
        para.paragraph_format.space_after = Pt(2)
        lbl = para.add_run(f"{label} : ")
        lbl.bold = True
        lbl.font.size = Pt(11)
        lbl.font.color.rgb = _hex_to_rgb(KORHUS_PRIMARY)
        val = para.add_run(value or "—")
        val.font.size = Pt(11)
        val.font.color.rgb = _hex_to_rgb(I3F_GREY)

    # Premier paragraphe : padding haut.
    first = meta_cell.paragraphs[0]
    first.paragraph_format.space_before = Pt(14)
    first_run = first.add_run("Synthèse de mission")
    first_run.bold = True
    first_run.font.size = Pt(10)
    first_run.font.color.rgb = _hex_to_rgb(KORHUS_GRANITE_LIGHT)

    _meta_line("Programme", project_name)
    _meta_line("Modèle audité", model_name)
    _meta_line("Phase BIM", phase_value)
    _meta_line("Date", date.today().isoformat())
    _meta_line("Auditeur", auditor)

    closing = meta_cell.add_paragraph()
    closing.paragraph_format.space_after = Pt(14)


def write_word_report(
    result: AuditResult,
    output_path: str | Path,
    auditor: str = "AMO BIM (audit automatisé)",
    xlsx_annex_path: str | Path | None = None,
    context: ReportProjectContext | None = None,
) -> Path:
    """Génère le rapport Word d'audit.

    Args:
        result: ``AuditResult`` complet (snapshot + catalog + findings).
        output_path: Destination ``.docx`` (parents créés si nécessaire).
        auditor: Nom affiché sur la page de garde.
        xlsx_annex_path: Chemin de l'annexe XLSX (référencé en annexe).
        context: ``ReportProjectContext`` enrichi. Si ``None`` (défaut),
            on appelle :func:`build_report_context` pour le construire
            automatiquement depuis ``result``. Cette indirection permet
            au caller de précharger un contexte enrichi (ex: adresse
            depuis ``enrich_with_public_data``) avant de générer le
            rapport.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    style = doc.styles["Normal"]
    style.font.name = KORHUS_FONT_PRIMARY  # Roboto (cf. charte Korhus)
    style.font.size = Pt(10)
    style.font.color.rgb = _hex_to_rgb(I3F_GREY)
    # rFonts pour propager la police à tous les scripts (ASCII, hAnsi, CS).
    # Sans ces attributs, Word retombe sur la police par défaut du doc.
    style_rpr = style.element.get_or_add_rPr()
    rfonts = style_rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        style_rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), KORHUS_FONT_PRIMARY)
    rfonts.set(qn("w:hAnsi"), KORHUS_FONT_PRIMARY)
    rfonts.set(qn("w:cs"), KORHUS_FONT_FALLBACK)

    # Contexte projet enrichi : auto-build si non fourni par le caller.
    if context is None:
        context = build_report_context(result)

    project_name = context.project_name or (result.snapshot.project or {}).get("name", "?")
    model_name = context.model_name or (result.snapshot.model or {}).get("name", "?")

    # L'auditeur affiché sur la page de garde et dans les KPIs vient en
    # priorité du contexte (fourni explicitement par l'utilisateur),
    # sinon du paramètre kwargs ``auditor`` (compat). Si l'utilisateur
    # a fourni auditor mais que ``context.auditor_name`` est vide, on
    # propage côté contexte pour que la section "Contexte de la
    # mission" l'affiche aussi.
    display_auditor = context.auditor_name or auditor
    if not context.auditor_name and auditor and auditor != "AMO BIM (audit automatisé)":
        # On garde le contexte cohérent avec ce qui est affiché.
        new_sources = dict(context.field_sources)
        new_sources["auditor_name"] = "user"
        context = context.model_copy(update={"auditor_name": auditor, "field_sources": new_sources})

    # 1. Page de garde — bandeau sombre Korhus Primary + logo, suivi
    # d'un bloc de métadonnées sur fond clair (Blue Neutral Light).
    #
    # Implémentation : on utilise des tables 1-cellule pour le shading
    # (python-docx ne sait pas peindre un fond de page complet ; cette
    # technique est portable et donne le rendu attendu sur Word /
    # Pages / LibreOffice).
    _write_cover_page(
        doc,
        project_name=project_name,
        model_name=model_name,
        phase_value=result.phase.value,
        cch_version=result.catalog.cch_version,
        auditor=display_auditor,
    )

    _section_break(doc)

    # 2. Résumé exécutif
    _add_heading(doc, "1. Résumé exécutif", level=1)
    by_sev = result.count_by_severity()
    by_theme = result.count_by_theme()

    conf = result.conformity_rate() * 100
    verdict = (
        "Conforme avec réserves légères"
        if conf >= 90
        else "Non conforme — corrections nécessaires"
        if conf >= 70
        else "Non conforme — anomalies majeures"
    )

    _kpi_table(
        doc,
        [
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
        ],
    )

    doc.add_paragraph(
        "Les deux figures ci-dessous synthétisent le profil global des "
        "anomalies. La répartition par thème indique quels domaines "
        "métier (nommage, classifications, propriétés…) concentrent les "
        "écarts ; la répartition par sévérité permet d'identifier "
        "rapidement si les écarts relèvent principalement de points "
        "bloquants ou d'améliorations de qualité.",
        style="Intense Quote",
    )
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

    # ── 2. Contexte de la mission ────────────────────────────────────────
    _write_section_mission_context(doc, context, result)
    _section_break(doc)

    # ── 3. Description du projet ─────────────────────────────────────────
    _write_section_project_description(doc, context, result)
    _section_break(doc)

    # ── 4. Référentiels et documents analysés ────────────────────────────
    _write_section_references(doc, context, result)

    # ── 5. Attendus du projet ────────────────────────────────────────────
    _write_section_expected_deliverables(doc, context, result)

    # ── 6. Objectifs BIM ─────────────────────────────────────────────────
    _write_section_bim_objectives(doc, context)

    # ── 7. Liste des contrôles réalisés ──────────────────────────────────
    _write_section_controls_performed(doc, context)

    _section_break(doc)

    # ── 8. Synthèse par thème (numérotation conservée + 5) ──────────────
    _add_heading(doc, "8. Synthèse par thème", level=1)
    doc.add_paragraph(
        "Cette synthèse regroupe les écarts par famille de contrôle. Elle "
        "aide à distinguer les problèmes structurels de modélisation des "
        "problèmes ponctuels de renseignement.",
        style="Intense Quote",
    )
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

    # 9. Détail par thème — on cap PAR thème pour qu'on voit un échantillon
    # de chacun, plutôt que de remplir le quota global avec un seul thème.
    _add_heading(doc, "9. Détail des anomalies par thème", level=1)
    doc.add_paragraph(
        "Ce chapitre détaille les objets concernés par les écarts détectés, "
        "thème par thème. Il constitue la base de travail pour les "
        "corrections à mener dans la maquette ou dans les données sources.",
        style="Intense Quote",
    )

    by_theme_all: dict[str, list[Finding]] = {}
    for f in result.findings:
        by_theme_all.setdefault(f.theme.value, []).append(f)

    capped_total = sum(min(len(items), MAX_FINDINGS_PER_THEME) for items in by_theme_all.values())
    if len(result.findings) > capped_total:
        doc.add_paragraph(
            f"⚠ Détail limité aux {MAX_FINDINGS_PER_THEME} anomalies les plus "
            "sévères par thème pour préserver la lisibilité — l'annexe Excel "
            "contient l'exhaustif.",
            style="Intense Quote",
        )

    # Ordre des thèmes : par nombre d'anomalies décroissant
    # Suggestions de classification pré-calculées une fois pour le thème
    # 'Classification IFC' (réutilisé dans la table dédiée).
    sug_list = suggest_for_findings(result.findings, result.snapshot, min_confidence=0.4, top_n=1)
    suggestions_map: dict[str, dict] = {}
    for item in sug_list:
        u = item.get("element_uuid")
        sugs = item.get("suggestions") or []
        if u and sugs:
            suggestions_map[u] = sugs[0]

    for theme, items in sorted(by_theme_all.items(), key=lambda kv: -len(kv[1])):
        n = len(items)
        label = f"{theme} ({n} anomalie{'s' if n > 1 else ''})"
        _add_heading(doc, label, level=2)
        smap = suggestions_map if theme == Theme.CLASSIFICATION.value else None
        _findings_table(doc, items[:MAX_FINDINGS_PER_THEME], suggestions_map=smap)

    _section_break(doc)

    # 10. Recommandations AMO BIM
    _add_heading(doc, "10. Recommandations AMO BIM", level=1)
    doc.add_paragraph(
        "Cette section propose des actions correctives priorisées à mener "
        "avant le prochain dépôt de maquette. Les recommandations sont "
        "déduites des anomalies détectées et organisées par lot/thème.",
        style="Intense Quote",
    )
    recs = _generate_recommendations(result)
    if not recs:
        doc.add_paragraph("Aucune action corrective majeure ne semble nécessaire à ce stade.")
    else:
        for r in recs:
            doc.add_paragraph(r, style="List Bullet")

    # 11. Limites de l'audit
    _add_heading(doc, "11. Limites de l'audit", level=1)
    doc.add_paragraph(
        "L'audit est exécuté de façon automatisée à partir des données "
        "exposées par l'API BIMData et des trois documents MOA chargés. "
        "Les limites suivantes doivent être prises en compte à la lecture "
        "du rapport :"
    )
    for a in context.assumptions or [
        "Les exigences sont interprétées selon le référentiel chargé au moment de l'audit.",
        "Le périmètre est limité aux objets présents dans le snapshot.",
    ]:
        doc.add_paragraph(f"• {a}", style="List Bullet")

    # 12. Informations non disponibles (si applicable)
    if context.missing_information:
        _add_heading(doc, "12. Informations non disponibles ou non explicites", level=1)
        doc.add_paragraph(
            "Cette section liste les éléments contextuels qui n'ont pas pu "
            "être extraits des sources analysées. Ils ne constituent pas "
            "des anomalies de la maquette, mais éclairent le lecteur sur "
            "ce que l'agent d'audit sait — et ce qu'il ne sait pas.",
            style="Intense Quote",
        )
        for item in context.missing_information:
            doc.add_paragraph(f"• {item}", style="List Bullet")

    # 13. Annexes
    _add_heading(doc, "13. Annexes", level=1)
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


# ── Helpers de sections contextuelles ────────────────────────────────────


def _para_intro(doc: Document, text: str) -> None:
    """Paragraphe d'introduction (italique / Intense Quote) pour situer
    une section auprès du lecteur non technique."""
    doc.add_paragraph(text, style="Intense Quote")


def _para_or_na(doc: Document, value: str | None) -> None:
    """Insère ``value`` si fourni, sinon la mention NOT_AVAILABLE."""
    if value and value.strip():
        doc.add_paragraph(value)
    else:
        doc.add_paragraph(NOT_AVAILABLE)


def _kv_or_na(
    doc: Document,
    label: str,
    value: str | None,
    *,
    source: str = "user",
) -> None:
    """Bullet « Label : valeur » avec fallback NOT_AVAILABLE.

    Args:
        doc: Document Word en cours.
        label: Libellé du champ (ex: ``"Adresse"``).
        value: Valeur à afficher (``None`` ou vide → ``NOT_AVAILABLE``).
        source: Source de la valeur (``"user"`` / ``"extracted"`` /
            ``"deduced"`` / ``"missing"``). Détermine si un suffixe
            de traçabilité ``(déduit — à confirmer)`` est ajouté.

    Garde la valeur sur la même ligne pour produire un rendu compact
    (utile pour les sections Contexte / Description du projet).
    """
    if value and value.strip():
        rendered = _render_with_source(value.strip(), source)
    else:
        rendered = NOT_AVAILABLE
    doc.add_paragraph(f"• {label} : {rendered}", style="List Bullet")


def _write_section_mission_context(
    doc: Document, context: ReportProjectContext, result: AuditResult
) -> None:
    """Section 2 — Contexte de la mission."""
    _add_heading(doc, "2. Contexte de la mission", level=1)
    _para_intro(
        doc,
        "Cette section précise le cadre dans lequel l'audit BIM a été "
        "réalisé. Elle permet de comprendre le périmètre contrôlé, les "
        "documents de référence utilisés et les limites éventuelles "
        "d'interprétation.",
    )
    _kv_or_na(doc, "Programme", context.project_name, source=context.source_of("project_name"))
    _kv_or_na(doc, "Maquette auditée", context.model_name, source=context.source_of("model_name"))
    _kv_or_na(
        doc,
        "Phase BIM",
        context.project_phase,
        source=context.source_of("project_phase"),
    )
    _kv_or_na(
        doc,
        "Référentiel appliqué",
        context.bim_reference,
        source=context.source_of("bim_reference"),
    )
    _kv_or_na(
        doc,
        "Auditeur",
        context.auditor_name,
        source=context.source_of("auditor_name"),
    )
    _kv_or_na(
        doc,
        "Périmètre",
        (
            f"{context.n_elements} éléments / {context.n_storeys} étage(s) / "
            f"{context.n_spaces} espace(s) / {context.n_zones} zone(s) — extraction "
            f"BIMData"
        )
        if context.n_elements
        else None,
        source="extracted",
    )


def _write_section_project_description(
    doc: Document, context: ReportProjectContext, result: AuditResult
) -> None:
    """Section 3 — Description du projet."""
    _add_heading(doc, "3. Description du projet", level=1)
    _para_intro(
        doc,
        "Cette section rassemble les informations générales disponibles "
        "sur l'opération. Elle distingue les données explicitement "
        "fournies des informations absentes afin d'éviter toute "
        "interprétation non justifiée.",
    )
    _add_heading(doc, "Description", level=2)
    _para_or_na(doc, context.project_description)

    _add_heading(doc, "Identification", level=2)
    _kv_or_na(doc, "Site", context.site_name, source=context.source_of("site_name"))
    _kv_or_na(
        doc,
        "Bâtiment",
        context.building_name,
        source=context.source_of("building_name"),
    )
    _kv_or_na(doc, "Adresse", context.address, source=context.source_of("address"))
    # MOA : on prend client_name en priorité ; sa source aussi.
    moa_value = context.client_name or context.owner_name
    moa_source = (
        context.source_of("client_name") if context.client_name else context.source_of("owner_name")
    )
    _kv_or_na(doc, "Maîtrise d'ouvrage", moa_value, source=moa_source)


def _write_section_references(
    doc: Document, context: ReportProjectContext, result: AuditResult
) -> None:
    """Section 4 — Référentiels et documents analysés."""
    _add_heading(doc, "4. Référentiels et documents analysés", level=1)
    _para_intro(
        doc,
        "Cette section liste les documents normatifs et MOA qui ont "
        "servi de base à l'audit. Elle permet à la maîtrise d'ouvrage "
        "de vérifier que les bonnes versions ont été utilisées et que "
        "la traçabilité est garantie.",
    )
    doc.add_paragraph(
        "L'audit est conduit conformément au Cahier des Charges BIM I3F "
        f"({context.bim_reference or '—'}). Les exigences sont extraites de "
        "trois sources :"
    )
    src_cch = context.cch_source or "non précisé"
    src_data = context.data_spec_source or "non précisé"
    src_naming = context.naming_spec_source or "non précisé"
    doc.add_paragraph(
        f"• Cahier des annexes CCH (PDF) — référence éditoriale et listes de valeurs : {src_cch}.",
        style="List Bullet",
    )
    doc.add_paragraph(
        "• Annexe « Spécification des données » (XLSX) — propriétés requises "
        f"par objet IFC et par phase BIM : {src_data}.",
        style="List Bullet",
    )
    doc.add_paragraph(
        "• Annexe « Nommage » (XLSX) — règles de nommage des sites, "
        f"bâtiments, étages, zones et pièces : {src_naming}.",
        style="List Bullet",
    )
    if context.n_property_specs or context.n_naming_rules:
        doc.add_paragraph(
            f"Le catalogue d'exigences chargé contient "
            f"{context.n_property_specs} spécification(s) de propriétés et "
            f"{context.n_naming_rules} règle(s) de nommage."
        )


def _write_section_expected_deliverables(
    doc: Document, context: ReportProjectContext, result: AuditResult
) -> None:
    """Section 5 — Attendus du projet."""
    _add_heading(doc, "5. Attendus du projet", level=1)
    _para_intro(
        doc,
        "Cette section synthétise les exigences utilisées comme base de "
        "contrôle. Elle explicite les attendus documentaires et "
        "informationnels retenus pour juger la conformité de la "
        "maquette.",
    )
    if context.expected_deliverables:
        for d in context.expected_deliverables:
            doc.add_paragraph(f"• {d}", style="List Bullet")
    else:
        doc.add_paragraph(
            "Les attendus opérationnels du projet ne sont pas explicitement "
            "détaillés dans les documents fournis. Les exigences retenues "
            "comme base de contrôle sont celles du Cahier des Charges BIM "
            f"I3F ({context.bim_reference or '—'}) et de ses annexes, à "
            f"savoir notamment {context.n_property_specs} spécification(s) de "
            f"propriétés par classe IFC et phase BIM, et "
            f"{context.n_naming_rules} règle(s) de nommage."
        )


def _write_section_bim_objectives(doc: Document, context: ReportProjectContext) -> None:
    """Section 6 — Objectifs BIM."""
    _add_heading(doc, "6. Objectifs BIM", level=1)
    _para_intro(
        doc,
        "Cette section présente les objectifs BIM associés au contrôle de "
        "la maquette. Elle permet de relier les anomalies détectées aux "
        "usages attendus du modèle numérique.",
    )
    if context.bim_objectives:
        for o in context.bim_objectives:
            doc.add_paragraph(f"• {o}", style="List Bullet")
    else:
        doc.add_paragraph(
            "Aucun objectif BIM explicite n'a été identifié dans les "
            "documents analysés. L'audit est donc limité à la vérification "
            "de conformité au référentiel chargé et aux données "
            "disponibles dans la maquette."
        )


def _write_section_controls_performed(doc: Document, context: ReportProjectContext) -> None:
    """Section 7 — Liste des contrôles réalisés (tableau)."""
    _add_heading(doc, "7. Liste des contrôles réalisés", level=1)
    _para_intro(
        doc,
        "Cette section liste les contrôles effectivement exécutés par "
        "l'agent d'audit. Elle donne une vision transparente du périmètre "
        "de vérification avant la lecture détaillée des anomalies.",
    )
    if not context.controls_performed:
        doc.add_paragraph(NOT_AVAILABLE)
        return
    tbl = doc.add_table(rows=1, cols=4)
    tbl.style = "Light Grid Accent 1"
    head = tbl.rows[0].cells
    head[0].text = "Thème de contrôle"
    head[1].text = "Objectif"
    head[2].text = "Données contrôlées"
    head[3].text = "Source de la règle"
    for c in head:
        _shade_cell(c, I3F_BLUE)
        for p in c.paragraphs:
            for r in p.runs:
                r.font.color.rgb = RGBColor(255, 255, 255)
                r.bold = True
    for ctrl in context.controls_performed:
        row = tbl.add_row().cells
        row[0].text = ctrl.theme
        row[1].text = ctrl.objective
        row[2].text = ctrl.checked_items
        row[3].text = ctrl.rule_source or "—"


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
