"""Rapport d'audit Word (livrable AMO BIM I3F).

Structure du document (refondue en 0.3 — modèle de rapport de conformité
de maquette numérique) :

1. Page de garde
   (Titre, Projet, Maquette auditée, Version, Date, Auteur, Référence CCBIM)
2. Synthèse exécutive (objectif, niveau de conformité, décision, indicateurs)
3. Périmètre de l'audit (documents de référence + maquette auditée)
4. Méthodologie (contrôles réalisés)
5. Résultats globaux (synthèse par domaine : Conforme / Avertissement / Non conforme)
6. Résultats détaillés
   6.1 Structure de la maquette
   6.2 Qualité des données
   6.3 Classification
   6.4 Conventions de nommage
   6.5 Contrôles géométriques
   6.6 Cohérence métier
   6.7 Détection des conflits
7. Liste des non-conformités
8. Recommandations (par priorité : Critique / Majeure / Mineure)
9. Conclusion (conformité globale, points bloquants, décision finale)
10. Annexes

Les sections contextuelles sont alimentées par
:class:`audit_bim.reporting.context.ReportProjectContext`. Si aucune
information n'est disponible pour une section donnée, la mention
« Information non disponible dans les documents fournis. » est
affichée — **on n'invente jamais**. Les contrôles non couverts par
l'audit automatisé (géométrie fine, détection de conflits, cohérence
métier détaillée) sont explicitement signalés comme hors périmètre
plutôt que présentés comme conformes.

Les graphes sont générés via matplotlib et insérés en PNG.
"""

from __future__ import annotations

import io
from collections import Counter
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
from .bimdata_brand import WORDMARK, find_logo
from .context import ReportProjectContext, build_report_context
from .theming import (
    BIMDATA_BLUE_NEUTRAL_LIGHT,
    BIMDATA_FONT_FALLBACK,
    BIMDATA_FONT_PRIMARY,
    BIMDATA_GRANITE,
    BIMDATA_GRANITE_LIGHT,
    BIMDATA_PRIMARY,
    BIMDATA_SECONDARY,
    BIMDATA_TERTIARY,
    BIMDATA_WHITE,
    SEVERITY_COLORS,
    THEME_COLORS,
)

# Phrase de fallback : utilisée chaque fois qu'une donnée contextuelle
# manque, pour éviter toute hallucination et garder un ton AMO BIM.
NOT_AVAILABLE = "Information non disponible dans les documents fournis."

# Mention pour les familles de contrôle non couvertes par l'audit
# automatisé (géométrie fine, clash detection, cohérence métier
# détaillée). On ne prétend JAMAIS qu'un contrôle non réalisé est conforme.
OUT_OF_SCOPE = (
    "Contrôle non réalisé dans le périmètre de cet audit automatisé "
    "(hors champ des données exposées par l'API BIMData)."
)

# Titre principal du livrable (page de garde).
REPORT_TITLE = "Rapport d'audit de conformité de la maquette numérique"

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
MAX_NONCONFORMITIES = 80  # cap de la table « Liste des non-conformités »
PIE_OTHER_THRESHOLD = 0.02  # tranches < 2 % regroupées en « Autres »

# ── Mapping sévérité (5 niveaux) → gravité métier (4 niveaux) ──────────────
# L'échelle métier française du rapport est plus grossière que l'échelle
# technique du moteur ; on agrège HIGH/MEDIUM côté « Majeure » et LOW côté
# « Mineure ».
GRAVITY_FR = {
    Severity.CRITICAL: "Critique",
    Severity.HIGH: "Majeure",
    Severity.MEDIUM: "Majeure",
    Severity.LOW: "Mineure",
    Severity.INFO: "Information",
}

# Une non-conformité « opposable » est une anomalie de gravité au moins
# MEDIUM. Les LOW/INFO relèvent de l'avertissement qualité.
NONCONFORMITY_SEVERITIES = {Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM}

# ── Mapping thèmes du moteur → domaines de la synthèse « Résultats globaux »
# Chaque domaine agrège un ou plusieurs ``Theme`` du moteur d'audit.
DOMAINS: list[tuple[str, set[Theme]]] = [
    ("Structure IFC / hiérarchie spatiale", {Theme.SPATIAL_HIERARCHY}),
    (
        "Conventions de nommage",
        {Theme.NAMING_SITE_BAT_ETAGE, Theme.NAMING_ZONE, Theme.NAMING_SPACE},
    ),
    ("Classification", {Theme.CLASSIFICATION}),
    ("Propriétés (Psets)", {Theme.PROPERTY_MISSING, Theme.PROPERTY_INVALID}),
    ("Quantités / géométrie", {Theme.QUANTITY}),
    ("Documents attendus", {Theme.DOCUMENT}),
]

# Statut domaine → libellé + couleur (charte feux tricolores).
_STATUS_LABEL = {
    "conforme": "✔ Conforme",
    "avertissement": "⚠ Avertissement",
    "non_conforme": "✖ Non conforme",
}
_STATUS_COLOR = {
    "conforme": "28A745",  # vert
    "avertissement": "FF8C00",  # orange
    "non_conforme": "DC3545",  # rouge
}

# Clés candidates pour extraire les métadonnées modèle depuis le dict
# BIMData ``get_model`` (les noms varient selon la version de l'API).
_MODEL_SOFTWARE_KEYS = ("source", "application", "software", "authoring_tool")
_MODEL_SCHEMA_KEYS = ("schema", "ifc_schema", "ifc_version", "version")
_MODEL_AUTHOR_KEYS = ("creator", "author", "created_by", "owner")
_MODEL_DATE_KEYS = ("created_at", "creation_date", "modified_date", "date")
_MODEL_DISCIPLINE_KEYS = ("type", "discipline", "domain")


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
    """H1/H2/... colorés en BIMData Primary, font Roboto/Arial.

    Pour les H1, on ajoute un filet d'accent jaune (BIMData Secondary)
    sous le titre — la charte BIMData utilise le jaune ``#F9C72C`` comme
    couleur d'accent, pas comme couleur dominante.
    """
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = _hex_to_rgb(BIMDATA_PRIMARY)
        run.font.name = BIMDATA_FONT_PRIMARY
        # rFonts est nécessaire pour que Word applique vraiment la
        # police (le nom dans run.font.name ne suffit pas seul).
        rpr = run._element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:ascii"), BIMDATA_FONT_PRIMARY)
        rfonts.set(qn("w:hAnsi"), BIMDATA_FONT_PRIMARY)
        rfonts.set(qn("w:cs"), BIMDATA_FONT_FALLBACK)
    if level == 1:
        # Filet d.accent jaune : paragraphe minuscule entièrement shadé.
        accent = doc.add_paragraph()
        accent.paragraph_format.space_before = Pt(0)
        accent.paragraph_format.space_after = Pt(6)
        pPr = accent._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), BIMDATA_SECONDARY)
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
        # Colonne libellé sur fond Blue Neutral Light (charte BIMData).
        _shade_cell(c0, BIMDATA_BLUE_NEUTRAL_LIGHT)
        for run in c0.paragraphs[0].runs:
            run.bold = True


def _header_row(tbl, headers: list[str]) -> None:
    """Peint la ligne d'en-tête d'un tableau (fond I3F Blue, texte blanc)."""
    cells = tbl.rows[0].cells
    for i, txt in enumerate(headers):
        cells[i].text = txt
        _shade_cell(cells[i], BIMDATA_PRIMARY)
        for p in cells[i].paragraphs:
            for r in p.runs:
                r.font.color.rgb = RGBColor(255, 255, 255)
                r.bold = True


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
    _header_row(tbl, headers)

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


# ── Page de garde ─────────────────────────────────────────────────────────


def _write_cover_page(
    doc: Document,
    *,
    project_name: str,
    model_name: str,
    version_label: str,
    cch_version: str | None,
    auditor: str,
) -> None:
    """Rend la page de couverture brandée BIMData.

    Structure :

    - **Hero sombre** (BIMData Primary ``#2F374A``) : logo BIMData
      (variante claire/inversée) centré, supertitle « AUDIT BIM » en
      jaune accent, titre du rapport en blanc, sous-titre = programme.
    - **Filet jaune** plein-largeur (BIMData Secondary ``#F9C72C``).
    - **Bloc métadonnées** (Blue Neutral Light) : Projet, Maquette
      auditée, Version, Date, Auteur, Référence du CCBIM utilisé.
    """
    # ── Hero sombre ───────────────────────────────────────────────────
    hero = doc.add_table(rows=1, cols=1)
    hero.autofit = False
    hero_cell = hero.rows[0].cells[0]
    hero_cell.width = Cm(17)
    _shade_cell(hero_cell, BIMDATA_PRIMARY)
    # Vider le paragraphe par défaut puis ajouter notre contenu.
    hero_cell.text = ""

    # Logo BIMData (variante claire/inversée pour fond sombre).
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
            run.text = WORDMARK
            run.font.color.rgb = _hex_to_rgb(BIMDATA_WHITE)
            run.font.size = Pt(22)
            run.bold = True
    else:
        run = logo_para.add_run(WORDMARK)
        run.font.color.rgb = _hex_to_rgb(BIMDATA_WHITE)
        run.font.size = Pt(22)
        run.bold = True

    # Espacement.
    spacer = hero_cell.add_paragraph()
    spacer.paragraph_format.space_after = Pt(10)

    # Supertitle jaune accent.
    supertitle = hero_cell.add_paragraph()
    supertitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = supertitle.add_run("AUDIT BIM")
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = _hex_to_rgb(BIMDATA_SECONDARY)

    # Titre principal blanc = titre du rapport.
    title = hero_cell.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(REPORT_TITLE)
    run.bold = True
    run.font.size = Pt(24)
    run.font.color.rgb = _hex_to_rgb(BIMDATA_WHITE)

    # Sous-titre = programme audité (blanc cassé via tertiaire).
    subtitle = hero_cell.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(48)
    run = subtitle.add_run(project_name)
    run.font.size = Pt(13)
    run.font.color.rgb = _hex_to_rgb(BIMDATA_TERTIARY)

    # ── Filet jaune ────────────────────────────────────────────────────
    accent = doc.add_table(rows=1, cols=1)
    accent_cell = accent.rows[0].cells[0]
    accent_cell.width = Cm(17)
    _shade_cell(accent_cell, BIMDATA_SECONDARY)
    accent_para = accent_cell.paragraphs[0]
    accent_para.paragraph_format.space_before = Pt(0)
    accent_para.paragraph_format.space_after = Pt(0)
    accent_run = accent_para.add_run(" ")
    accent_run.font.size = Pt(2)

    # ── Bloc métadonnées sur fond clair ───────────────────────────────
    meta = doc.add_table(rows=1, cols=1)
    meta_cell = meta.rows[0].cells[0]
    meta_cell.width = Cm(17)
    _shade_cell(meta_cell, BIMDATA_BLUE_NEUTRAL_LIGHT)
    meta_cell.text = ""

    def _meta_line(label: str, value: str) -> None:
        para = meta_cell.add_paragraph()
        para.paragraph_format.space_before = Pt(2)
        para.paragraph_format.space_after = Pt(2)
        lbl = para.add_run(f"{label} : ")
        lbl.bold = True
        lbl.font.size = Pt(11)
        lbl.font.color.rgb = _hex_to_rgb(BIMDATA_PRIMARY)
        val = para.add_run(value or "—")
        val.font.size = Pt(11)
        val.font.color.rgb = _hex_to_rgb(BIMDATA_GRANITE)

    # Premier paragraphe : padding haut.
    first = meta_cell.paragraphs[0]
    first.paragraph_format.space_before = Pt(14)
    first_run = first.add_run("Identification du livrable")
    first_run.bold = True
    first_run.font.size = Pt(10)
    first_run.font.color.rgb = _hex_to_rgb(BIMDATA_GRANITE_LIGHT)

    _meta_line("Projet", project_name)
    _meta_line("Maquette auditée", model_name)
    _meta_line("Version", version_label)
    _meta_line("Date", date.today().isoformat())
    _meta_line("Auteur", auditor)
    _meta_line("Référence du CCBIM utilisé", f"CCH BIM I3F V{cch_version or '—'}")

    closing = meta_cell.add_paragraph()
    closing.paragraph_format.space_after = Pt(14)


# ── Helpers de calcul (décision, statuts domaine, métadonnées modèle) ──────


def _decision(result: AuditResult) -> tuple[str, str]:
    """Décision d'acceptation de la maquette selon les anomalies + le taux.

    Returns:
        ``(décision, justification)`` — décision parmi *Acceptée*,
        *Acceptée sous réserve*, *Refusée*.
    """
    by_sev = result.count_by_severity()
    n_crit = by_sev.get("CRITICAL", 0)
    n_high = by_sev.get("HIGH", 0)
    conf = result.conformity_rate() * 100
    if n_crit == 0 and n_high == 0 and conf >= 90:
        return ("Acceptée", "Maquette conforme aux exigences contrôlées.")
    if n_crit == 0 and conf >= 70:
        return (
            "Acceptée sous réserve",
            "Conforme sous réserve de correction des anomalies signalées.",
        )
    return ("Refusée", "Non conforme — corrections requises avant acceptation.")


def _domain_status(findings: list[Finding]) -> str:
    """Statut d'un domaine d'après la gravité max de ses anomalies."""
    sevs = {f.severity for f in findings}
    if Severity.CRITICAL in sevs or Severity.HIGH in sevs:
        return "non_conforme"
    if sevs:
        return "avertissement"
    return "conforme"


def _model_meta(model: dict, keys: tuple[str, ...]) -> str | None:
    """Premier champ non vide du dict modèle parmi ``keys``."""
    for k in keys:
        v = (model or {}).get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)):
            return str(v)
    return None


# ── Assemblage du rapport ──────────────────────────────────────────────────


def write_word_report(
    result: AuditResult,
    output_path: str | Path,
    auditor: str = "AMO BIM (audit automatisé)",
    xlsx_annex_path: str | Path | None = None,
    context: ReportProjectContext | None = None,
) -> Path:
    """Génère le rapport Word d'audit (modèle de conformité de maquette).

    Args:
        result: ``AuditResult`` complet (snapshot + catalog + findings).
        output_path: Destination ``.docx`` (parents créés si nécessaire).
        auditor: Nom affiché sur la page de garde.
        xlsx_annex_path: Chemin de l'annexe XLSX (référencé en annexe).
        context: ``ReportProjectContext`` enrichi. Si ``None`` (défaut),
            on appelle :func:`build_report_context` pour le construire
            automatiquement depuis ``result``.
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
    style.font.name = BIMDATA_FONT_PRIMARY  # Roboto (cf. charte BIMData)
    style.font.size = Pt(10)
    style.font.color.rgb = _hex_to_rgb(BIMDATA_GRANITE)
    # rFonts pour propager la police à tous les scripts (ASCII, hAnsi, CS).
    style_rpr = style.element.get_or_add_rPr()
    rfonts = style_rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        style_rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), BIMDATA_FONT_PRIMARY)
    rfonts.set(qn("w:hAnsi"), BIMDATA_FONT_PRIMARY)
    rfonts.set(qn("w:cs"), BIMDATA_FONT_FALLBACK)

    # Contexte projet enrichi : auto-build si non fourni par le caller.
    if context is None:
        context = build_report_context(result)

    project_name = context.project_name or (result.snapshot.project or {}).get("name", "?")
    model_name = context.model_name or (result.snapshot.model or {}).get("name", "?")

    # L'auditeur affiché vient en priorité du contexte (fourni
    # explicitement par l'utilisateur), sinon du paramètre ``auditor``.
    display_auditor = context.auditor_name or auditor
    if not context.auditor_name and auditor and auditor != "AMO BIM (audit automatisé)":
        new_sources = dict(context.field_sources)
        new_sources["auditor_name"] = "user"
        context = context.model_copy(update={"auditor_name": auditor, "field_sources": new_sources})

    # ── 1. Page de garde ────────────────────────────────────────────────
    _write_cover_page(
        doc,
        project_name=project_name,
        model_name=model_name,
        version_label=f"Phase BIM {result.phase.value}",
        cch_version=result.catalog.cch_version,
        auditor=display_auditor,
    )
    _section_break(doc)

    # ── 2. Synthèse exécutive ───────────────────────────────────────────
    _write_section_executive_summary(doc, result, context, project_name, model_name)
    _section_break(doc)

    # ── 3. Périmètre de l'audit ─────────────────────────────────────────
    _write_section_scope(doc, context, result)
    _section_break(doc)

    # ── 4. Méthodologie ─────────────────────────────────────────────────
    _write_section_methodology(doc, context)
    _section_break(doc)

    # ── 5. Résultats globaux ────────────────────────────────────────────
    _write_section_global_results(doc, result)
    _section_break(doc)

    # ── 6. Résultats détaillés ──────────────────────────────────────────
    _write_section_detailed_results(doc, result)
    _section_break(doc)

    # ── 7. Liste des non-conformités ────────────────────────────────────
    _write_section_nonconformities(doc, result)
    _section_break(doc)

    # ── 8. Recommandations ──────────────────────────────────────────────
    _write_section_recommendations(doc, result)
    _section_break(doc)

    # ── 9. Conclusion ───────────────────────────────────────────────────
    _write_section_conclusion(doc, result, context)
    _section_break(doc)

    # ── 10. Annexes ─────────────────────────────────────────────────────
    _write_section_annexes(doc, xlsx_annex_path, context)

    doc.save(str(output_path))
    return output_path


# ── Sections ───────────────────────────────────────────────────────────────


def _para_intro(doc: Document, text: str) -> None:
    """Paragraphe d'introduction (Intense Quote) pour situer une section."""
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
    """Bullet « Label : valeur » avec fallback NOT_AVAILABLE."""
    if value and value.strip():
        rendered = _render_with_source(value.strip(), source)
    else:
        rendered = NOT_AVAILABLE
    doc.add_paragraph(f"• {label} : {rendered}", style="List Bullet")


def _write_section_executive_summary(
    doc: Document,
    result: AuditResult,
    context: ReportProjectContext,
    project_name: str,
    model_name: str,
) -> None:
    """Section 2 — Synthèse exécutive."""
    _add_heading(doc, "2. Synthèse exécutive", level=1)

    by_sev = result.count_by_severity()
    by_theme = result.count_by_theme()
    conf = result.conformity_rate() * 100
    decision, justification = _decision(result)

    n_crit = by_sev.get("CRITICAL", 0)
    n_high = by_sev.get("HIGH", 0)
    n_med = by_sev.get("MEDIUM", 0)
    n_low = by_sev.get("LOW", 0)
    n_info = by_sev.get("INFO", 0)
    n_nonconf = n_crit + n_high + n_med
    n_warn = n_low + n_info
    n_rules = context.n_property_specs + context.n_naming_rules

    # Points de vigilance = thèmes les plus impactés (top 3).
    top_themes = sorted(by_theme.items(), key=lambda kv: -kv[1])[:3]
    vigilance = (
        ", ".join(f"{t} ({c})" for t, c in top_themes)
        if top_themes
        else "aucun écart significatif détecté"
    )

    doc.add_paragraph(
        f"L'audit vise à vérifier la conformité de la maquette « {model_name} » "
        f"(programme {project_name}, phase {result.phase.value}) au Cahier des "
        f"Charges BIM I3F V{result.catalog.cch_version or '—'}. "
        f"Le niveau global de conformité (pondéré) s'établit à {conf:.0f} %. "
        f"Principaux points de vigilance : {vigilance}. "
        f"Décision : {decision} — {justification}",
        style="Intense Quote",
    )

    # Tableau d'indicateurs synthétiques.
    _kpi_table(
        doc,
        [
            ("Taux de conformité (pondéré)", f"{conf:.0f} %"),
            ("Éléments audités", str(context.n_elements)),
            ("Règles de conformité contrôlées (catalogue)", str(n_rules)),
            ("Non-conformités (Critique / Majeure)", str(n_nonconf)),
            ("Avertissements (Mineure / Information)", str(n_warn)),
            ("Décision", decision),
        ],
    )

    doc.add_paragraph(
        "Les deux figures ci-dessous synthétisent le profil global des "
        "anomalies : répartition par thème (quels domaines concentrent les "
        "écarts) et par sévérité (points bloquants vs améliorations de qualité).",
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


def _write_section_scope(doc: Document, context: ReportProjectContext, result: AuditResult) -> None:
    """Section 3 — Périmètre de l'audit (documents de référence + maquette)."""
    _add_heading(doc, "3. Périmètre de l'audit", level=1)
    _para_intro(
        doc,
        "Cette section précise les documents de référence opposables et "
        "identifie la maquette auditée. Elle garantit la traçabilité du "
        "périmètre contrôlé.",
    )

    # 3.1 Documents de référence
    _add_heading(doc, "Documents de référence", level=2)
    src_cch = context.cch_source or "non précisé"
    src_data = context.data_spec_source or "non précisé"
    src_naming = context.naming_spec_source or "non précisé"
    doc.add_paragraph(
        f"• CCBIM appliqué : {context.bim_reference or '—'} (Cahier des annexes — {src_cch}).",
        style="List Bullet",
    )
    doc.add_paragraph(
        f"• Convention / exigences BIM du maître d'ouvrage : annexe "
        f"« Spécification des données » ({src_data}) et annexe « Nommage » "
        f"({src_naming}).",
        style="List Bullet",
    )
    if context.n_property_specs or context.n_naming_rules:
        doc.add_paragraph(
            f"• Catalogue d'exigences chargé : {context.n_property_specs} "
            f"spécification(s) de propriétés et {context.n_naming_rules} "
            "règle(s) de nommage.",
            style="List Bullet",
        )

    # 3.2 Maquette auditée
    _add_heading(doc, "Maquette auditée", level=2)
    model = result.snapshot.model or {}
    _kv_or_na(doc, "Nom du modèle", context.model_name, source=context.source_of("model_name"))
    _kv_or_na(
        doc,
        "Discipline",
        _model_meta(model, _MODEL_DISCIPLINE_KEYS),
        source="extracted",
    )
    _kv_or_na(
        doc,
        "Auteur / producteur",
        _model_meta(model, _MODEL_AUTHOR_KEYS),
        source="extracted",
    )
    _kv_or_na(
        doc,
        "Date du modèle",
        _model_meta(model, _MODEL_DATE_KEYS),
        source="extracted",
    )
    _kv_or_na(
        doc,
        "Logiciel de production",
        _model_meta(model, _MODEL_SOFTWARE_KEYS),
        source="extracted",
    )
    _kv_or_na(
        doc,
        "Version IFC (schéma)",
        _model_meta(model, _MODEL_SCHEMA_KEYS),
        source="extracted",
    )
    _kv_or_na(
        doc,
        "Périmètre extrait",
        (
            f"{context.n_elements} éléments / {context.n_storeys} étage(s) / "
            f"{context.n_spaces} espace(s) / {context.n_zones} zone(s) — "
            "extraction BIMData"
        )
        if context.n_elements
        else None,
        source="extracted",
    )
    # Adresse / MOA si disponibles (utile pour le contexte projet).
    _kv_or_na(doc, "Adresse du projet", context.address, source=context.source_of("address"))
    moa_value = context.client_name or context.owner_name
    moa_source = (
        context.source_of("client_name") if context.client_name else context.source_of("owner_name")
    )
    _kv_or_na(doc, "Maîtrise d'ouvrage", moa_value, source=moa_source)


def _write_section_methodology(doc: Document, context: ReportProjectContext) -> None:
    """Section 4 — Méthodologie (description + tableau des contrôles)."""
    _add_heading(doc, "4. Méthodologie", level=1)
    _para_intro(
        doc,
        "L'audit est exécuté de façon automatisée à partir des données "
        "exposées par l'API BIMData et du catalogue d'exigences chargé. "
        "Les familles de contrôles réalisés sont décrites ci-dessous.",
    )
    doc.add_paragraph(
        "Contrôles réalisés : structure IFC et hiérarchie spatiale, "
        "conventions de nommage, classification, propriétés obligatoires "
        "(Psets par phase), validation des valeurs, quantités (surfaces / "
        "volumes), unicité des identifiants d'équipement et couverture des "
        "typologies attendues."
    )
    doc.add_paragraph(
        "Hors périmètre de cet audit automatisé : le contrôle géométrique "
        "fin (objets dupliqués, géométrie invalide), la cohérence métier "
        "détaillée et la détection de conflits (clash detection), qui "
        "requièrent l'analyse de la géométrie 3D non exposée par l'API."
    )

    if not context.controls_performed:
        doc.add_paragraph(NOT_AVAILABLE)
        return
    tbl = doc.add_table(rows=1, cols=4)
    tbl.style = "Light Grid Accent 1"
    _header_row(tbl, ["Thème de contrôle", "Objectif", "Données contrôlées", "Source de la règle"])
    for ctrl in context.controls_performed:
        row = tbl.add_row().cells
        row[0].text = ctrl.theme
        row[1].text = ctrl.objective
        row[2].text = ctrl.checked_items
        row[3].text = ctrl.rule_source or "—"


def _write_section_global_results(doc: Document, result: AuditResult) -> None:
    """Section 5 — Résultats globaux (synthèse par domaine)."""
    _add_heading(doc, "5. Résultats globaux", level=1)
    _para_intro(
        doc,
        "Vue d'ensemble du statut de conformité par domaine de contrôle. "
        "Un domaine est « Non conforme » s'il présente au moins une "
        "anomalie critique ou majeure, « Avertissement » pour des écarts "
        "mineurs, « Conforme » en l'absence d'anomalie.",
    )

    # Regrouper les findings par domaine.
    by_domain: dict[str, list[Finding]] = {label: [] for label, _ in DOMAINS}
    theme_to_domain: dict[Theme, str] = {}
    for label, themes in DOMAINS:
        for th in themes:
            theme_to_domain[th] = label
    for f in result.findings:
        label = theme_to_domain.get(f.theme)
        if label is not None:
            by_domain[label].append(f)

    tbl = doc.add_table(rows=1, cols=4)
    tbl.style = "Light Grid Accent 1"
    _header_row(tbl, ["Domaine", "Statut", "Nb anomalies", "Dont critiques/majeures"])
    for label, _themes in DOMAINS:
        items = by_domain[label]
        status = _domain_status(items)
        n_severe = sum(1 for f in items if f.severity in (Severity.CRITICAL, Severity.HIGH))
        row = tbl.add_row().cells
        row[0].text = label
        row[1].text = _STATUS_LABEL[status]
        _shade_cell(row[1], _STATUS_COLOR[status])
        for r in row[1].paragraphs[0].runs:
            r.font.color.rgb = RGBColor(255, 255, 255)
            r.bold = True
        row[2].text = str(len(items))
        row[3].text = str(n_severe)


def _write_section_detailed_results(doc: Document, result: AuditResult) -> None:
    """Section 6 — Résultats détaillés (6.1 → 6.7)."""
    _add_heading(doc, "6. Résultats détaillés", level=1)
    _para_intro(
        doc,
        "Détail des écarts par famille de contrôle. Constitue la base de "
        "travail pour les corrections à mener dans la maquette ou les "
        "données sources. Le détail est limité aux anomalies les plus "
        "sévères par thème ; l'annexe Excel contient l'exhaustif.",
    )

    # Findings groupés par thème.
    by_theme_all: dict[Theme, list[Finding]] = {}
    for f in result.findings:
        by_theme_all.setdefault(f.theme, []).append(f)

    def _theme_block(themes: set[Theme], *, with_suggestions: bool = False) -> None:
        items: list[Finding] = []
        for th in themes:
            items.extend(by_theme_all.get(th, []))
        # Tri par sévérité (CRITICAL d'abord) puis cap.
        order = {s: i for i, s in enumerate(Severity.ordered())}
        items.sort(key=lambda f: order.get(f.severity, 99))
        smap = _suggestions_map(result) if with_suggestions else None
        _findings_table(doc, items[:MAX_FINDINGS_PER_THEME], suggestions_map=smap)

    # 6.1 Structure de la maquette
    _add_heading(doc, "6.1 Structure de la maquette", level=2)
    doc.add_paragraph(
        "Organisation IFC (Site → Bâtiment → Niveau → Espace) et présence "
        "des entités spatiales attendues."
    )
    _theme_block({Theme.SPATIAL_HIERARCHY})

    # 6.2 Qualité des données
    _add_heading(doc, "6.2 Qualité des données", level=2)
    doc.add_paragraph(
        "Contrôle des propriétés obligatoires (Psets par phase) et de la "
        "validité des valeurs (présence, type, valeurs non vides)."
    )
    _theme_block({Theme.PROPERTY_MISSING, Theme.PROPERTY_INVALID})

    # 6.3 Classification
    _add_heading(doc, "6.3 Classification", level=2)
    doc.add_paragraph(
        "Présence et cohérence de la classification IFC (UniFormat II par "
        "défaut ; Omniclass / CCI / table interne 3F selon le référentiel)."
    )
    _theme_block({Theme.CLASSIFICATION}, with_suggestions=True)

    # 6.4 Conventions de nommage
    _add_heading(doc, "6.4 Conventions de nommage", level=2)
    doc.add_paragraph(
        "Contrôle du nommage des objets, niveaux, zones et espaces selon "
        "les listes fermées et la codification I3F (CCH chap. 6.3)."
    )
    _theme_block({Theme.NAMING_SITE_BAT_ETAGE, Theme.NAMING_ZONE, Theme.NAMING_SPACE})

    # 6.5 Contrôles géométriques
    _add_heading(doc, "6.5 Contrôles géométriques", level=2)
    quantity_items = by_theme_all.get(Theme.QUANTITY, [])
    doc.add_paragraph(
        "Présence des quantités géométriques (surfaces, volumes / "
        "BaseQuantities) sur les éléments quantifiables. Les contrôles "
        "géométriques fins (objets dupliqués, objets isolés, géométrie "
        "invalide, objets sans volume, intersections anormales) ne sont "
        "pas couverts par cet audit automatisé."
    )
    if quantity_items:
        order = {s: i for i, s in enumerate(Severity.ordered())}
        quantity_items = sorted(quantity_items, key=lambda f: order.get(f.severity, 99))
        _findings_table(doc, quantity_items[:MAX_FINDINGS_PER_THEME])
    else:
        doc.add_paragraph("Aucune anomalie de quantité détectée.").italic = True

    # 6.6 Cohérence métier
    _add_heading(doc, "6.6 Cohérence métier", level=2)
    doc.add_paragraph(
        "Cohérence métier par discipline (espaces fermés, portes dans les "
        "murs, fenêtres ; poteaux / poutres / dalles ; réseaux / "
        "équipements / connexions MEP). " + OUT_OF_SCOPE
    )

    # 6.7 Détection des conflits
    _add_heading(doc, "6.7 Détection des conflits", level=2)
    doc.add_paragraph(
        "Détection de conflits inter-disciplines (hard clash, soft clash, "
        "clearance). " + OUT_OF_SCOPE
    )


def _write_section_nonconformities(doc: Document, result: AuditResult) -> None:
    """Section 7 — Liste des non-conformités (tableau détaillé)."""
    _add_heading(doc, "7. Liste des non-conformités", level=1)
    _para_intro(
        doc,
        "Liste des anomalies opposables (gravité Critique ou Majeure). Les "
        "écarts mineurs et informationnels figurent dans l'annexe Excel.",
    )

    order = {s: i for i, s in enumerate(Severity.ordered())}
    ncs = sorted(
        (f for f in result.findings if f.severity in NONCONFORMITY_SEVERITIES),
        key=lambda f: order.get(f.severity, 99),
    )
    if not ncs:
        doc.add_paragraph("Aucune non-conformité critique ou majeure détectée.")
        return

    if len(ncs) > MAX_NONCONFORMITIES:
        doc.add_paragraph(
            f"⚠ {len(ncs)} non-conformités détectées — tableau limité aux "
            f"{MAX_NONCONFORMITIES} plus sévères ; l'exhaustif figure dans "
            "l'annexe Excel.",
            style="Intense Quote",
        )

    tbl = doc.add_table(rows=1, cols=6)
    tbl.style = "Light Grid Accent 1"
    _header_row(tbl, ["ID", "Règle", "Objet", "Gravité", "Commentaire", "Action"])
    for i, f in enumerate(ncs[:MAX_NONCONFORMITIES], start=1):
        row = tbl.add_row().cells
        row[0].text = f"NC-{i:03d}"
        row[1].text = (f.ref_cch or f.error_type.value or "")[:40]
        row[2].text = f.short_label()[:40]
        row[3].text = GRAVITY_FR.get(f.severity, f.severity.value)
        _shade_cell(row[3], SEVERITY_COLORS[f.severity.value])
        for r in row[3].paragraphs[0].runs:
            r.font.color.rgb = RGBColor(255, 255, 255)
            r.bold = True
        exp = f.expected
        if isinstance(exp, list):
            exp = ", ".join(map(str, exp[:3])) + ("…" if len(exp) > 3 else "")
        comment = f"Attendu : {exp or '—'} / Réel : {f.actual or '—'}"
        row[4].text = comment[:90]
        row[5].text = (f.recommended_action or "—")[:90]


def _write_section_recommendations(doc: Document, result: AuditResult) -> None:
    """Section 8 — Recommandations classées par priorité."""
    _add_heading(doc, "8. Recommandations", level=1)
    _para_intro(
        doc,
        "Actions correctives priorisées à mener avant le prochain dépôt de "
        "maquette. Les recommandations sont déduites des anomalies détectées.",
    )
    buckets = _recommendations_by_priority(result)
    any_rec = False
    for priority in ("Critique", "Majeure", "Mineure"):
        recs = buckets.get(priority, [])
        if not recs:
            continue
        any_rec = True
        _add_heading(doc, priority, level=2)
        for r in recs:
            doc.add_paragraph(r, style="List Bullet")
    if not any_rec:
        doc.add_paragraph("Aucune action corrective majeure ne semble nécessaire à ce stade.")


def _write_section_conclusion(
    doc: Document, result: AuditResult, context: ReportProjectContext
) -> None:
    """Section 9 — Conclusion (conformité globale, points bloquants, décision)."""
    _add_heading(doc, "9. Conclusion", level=1)
    by_sev = result.count_by_severity()
    conf = result.conformity_rate() * 100
    decision, justification = _decision(result)
    n_crit = by_sev.get("CRITICAL", 0)
    n_high = by_sev.get("HIGH", 0)
    n_blocking = n_crit + n_high

    # Domaines conformes (sans CRITICAL/HIGH) pour valoriser l'acquis.
    theme_to_domain: dict[Theme, str] = {}
    for label, themes in DOMAINS:
        for th in themes:
            theme_to_domain[th] = label
    severe_domains: set[str] = set()
    for f in result.findings:
        if f.severity in (Severity.CRITICAL, Severity.HIGH):
            d = theme_to_domain.get(f.theme)
            if d:
                severe_domains.add(d)
    conform_domains = [label for label, _ in DOMAINS if label not in severe_domains]

    if n_blocking:
        blocking_txt = (
            f"{n_blocking} point(s) bloquant(s) (anomalies critiques ou "
            "majeures) doivent être levés avant la prochaine livraison."
        )
    else:
        blocking_txt = "Aucun point bloquant (anomalie critique ou majeure) n'a été détecté."

    conform_txt = (
        f"Les domaines suivants sont conformes ou ne présentent que des "
        f"écarts mineurs : {', '.join(conform_domains)}. "
        if conform_domains
        else ""
    )

    doc.add_paragraph(
        f"La maquette « {context.model_name or '—'} » présente un niveau de "
        f"conformité (pondéré) de {conf:.0f} % au regard du CCH BIM I3F "
        f"V{result.catalog.cch_version or '—'} pour la phase {result.phase.value}. "
        f"{conform_txt}{blocking_txt}"
    )
    doc.add_paragraph(
        "Actions avant la prochaine livraison : corriger en priorité les "
        "non-conformités critiques et majeures (cf. § 7 et § 8), puis "
        "ré-itérer un audit pour valider la reprise."
    )

    # Décision finale mise en valeur.
    p = doc.add_paragraph()
    run = p.add_run(f"Décision finale : {decision}")
    run.bold = True
    run.font.size = Pt(12)
    run.font.color.rgb = _hex_to_rgb(BIMDATA_PRIMARY)
    doc.add_paragraph(justification)


def _write_section_annexes(
    doc: Document, xlsx_annex_path: str | Path | None, context: ReportProjectContext
) -> None:
    """Section 10 — Annexes."""
    _add_heading(doc, "10. Annexes", level=1)
    doc.add_paragraph(
        "• Liste complète des règles contrôlées et export exhaustif des "
        "résultats : voir l'annexe Excel.",
        style="List Bullet",
    )
    if xlsx_annex_path:
        doc.add_paragraph(
            f"• Annexe détaillée (Excel) : « {Path(xlsx_annex_path).name} » — "
            "intégralité des anomalies par type d'erreur, avec GUID IFC des "
            "objets concernés, exploitable directement par les équipes projet.",
            style="List Bullet",
        )
    doc.add_paragraph(
        f"• Paramètres d'exécution : phase BIM {context.project_phase or '—'}, "
        f"référentiel {context.bim_reference or '—'}, "
        f"{context.n_property_specs} spécification(s) de propriétés et "
        f"{context.n_naming_rules} règle(s) de nommage.",
        style="List Bullet",
    )
    doc.add_paragraph(
        "• Référentiel CCH I3F : documents transmis par la maîtrise "
        "d'ouvrage (Cahier des annexes, annexe Spécifications, annexe Nommage).",
        style="List Bullet",
    )
    # Limites de l'audit (rattachées aux annexes).
    if context.assumptions:
        _add_heading(doc, "Limites et hypothèses de l'audit", level=2)
        for a in context.assumptions:
            doc.add_paragraph(f"• {a}", style="List Bullet")
    if context.missing_information:
        _add_heading(doc, "Informations non disponibles", level=2)
        doc.add_paragraph(
            "Éléments contextuels non extraits des sources analysées (ne "
            "constituent pas des anomalies de la maquette)."
        )
        for item in context.missing_information:
            doc.add_paragraph(f"• {item}", style="List Bullet")


# ── Génération des recommandations ─────────────────────────────────────────


def _suggestions_map(result: AuditResult) -> dict[str, dict]:
    """Suggestions de classification (1 par élément) pour le thème dédié."""
    sug_list = suggest_for_findings(result.findings, result.snapshot, min_confidence=0.4, top_n=1)
    out: dict[str, dict] = {}
    for item in sug_list:
        u = item.get("element_uuid")
        sugs = item.get("suggestions") or []
        if u and sugs:
            out[u] = sugs[0]
    return out


# Indices correctifs par thème, réutilisés pour générer les recommandations
# priorisées (section 8).
_THEME_HINTS: dict[Theme, str] = {
    Theme.SPATIAL_HIERARCHY: (
        "compléter / corriger la hiérarchie spatiale Site → Bâtiment → "
        "Étage → Espace (CCH chap. 6.1)"
    ),
    Theme.NAMING_SITE_BAT_ETAGE: (
        "aligner le nommage des sites, bâtiments et étages sur les listes fermées du CCH chap. 6.3"
    ),
    Theme.NAMING_ZONE: "reprendre le nommage des zones (codification I3F, CCH chap. 6.3)",
    Theme.NAMING_SPACE: "reprendre le nommage des pièces (listes fermées, CCH chap. 6.3)",
    Theme.CLASSIFICATION: ("compléter la classification IFC (UniFormat / Omniclass / table 3F)"),
    Theme.PROPERTY_MISSING: "renseigner les propriétés / Psets manquants pour la phase",
    Theme.PROPERTY_INVALID: "corriger les valeurs de propriétés invalides ou hors domaine",
    Theme.QUANTITY: "compléter les quantités (NetFloorArea / BaseQuantities)",
    Theme.DOCUMENT: "fournir les documents attendus manquants",
}

# Sévérité → priorité métier de la recommandation.
_SEV_TO_PRIORITY = {
    Severity.CRITICAL: "Critique",
    Severity.HIGH: "Critique",
    Severity.MEDIUM: "Majeure",
    Severity.LOW: "Mineure",
    Severity.INFO: "Mineure",
}


def _recommendations_by_priority(result: AuditResult) -> dict[str, list[str]]:
    """Recommandations correctives groupées par priorité (Critique / Majeure / Mineure).

    Pour chaque (priorité, thème), on agrège le nombre d'anomalies et on
    produit une action concrète à partir de ``_THEME_HINTS``.
    """
    # (priority, theme) → count
    agg: dict[tuple[str, Theme], int] = Counter()
    for f in result.findings:
        priority = _SEV_TO_PRIORITY.get(f.severity, "Mineure")
        agg[(priority, f.theme)] += 1

    buckets: dict[str, list[str]] = {"Critique": [], "Majeure": [], "Mineure": []}
    # Tri stable : par priorité puis nombre décroissant.
    for (priority, theme), count in sorted(agg.items(), key=lambda kv: -kv[1]):
        hint = _THEME_HINTS.get(theme, "corriger les écarts identifiés")
        label = f"{count} anomalie{'s' if count > 1 else ''} — {hint}."
        buckets[priority].append(label[0].upper() + label[1:])

    # Recommandation transverse si conformité faible.
    if result.conformity_rate() < 0.7:
        buckets["Critique"].append(
            "Ré-itérer un audit après reprise : l'écart au CCH est important — "
            "prévoir une revue conjointe MOA / MOE avant la phase suivante."
        )
    return buckets


def _generate_recommendations(result: AuditResult) -> list[str]:
    """Recommandations stratégiques (haut niveau), dérivées des findings agrégés.

    Conservé pour compatibilité (réutilisé par d'éventuels appelants /
    tests) ; la section 8 du rapport utilise désormais
    :func:`_recommendations_by_priority`.
    """
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
