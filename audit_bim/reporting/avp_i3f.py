"""Pack de livrables AVP I3F (Tarare 0546L) — génération BIMData.

Produit, à partir d'un ``AuditResult`` (snapshot/audit BIMData) **et** des
fichiers sources I3F fournis (hybride), le pack de livrables AVP :

1. ``… Contrôle Maquettes AVP.xlsx`` — grille de contrôle + stats conformité.
2. ``… AVP - export SHAB maquette.xlsx``.
3. ``… Export Zones et Espaces.xlsx``.
4. ``… Extraction surface enveloppe.xlsx`` (+ ratio FAC/SHAB, Seuil 3F).
5. ``… export Menuiseries.xlsx``.
6. ``… Analyse BIM AVP.docx`` (+ ``.pdf`` best-effort) — rapport consolidé.

Principes :

- **Réutilise** l'infra de reporting existante : ``xlsx_annex._build_formats``
  / ``write_safe`` (charte BIMData, anti-injection) pour l'Excel, et les
  helpers ``word_report`` pour le Word. Pas de stack parallèle.
- **Ne jamais inventer** : donnée absente (snapshot ET source) →
  ``NOT_AVAILABLE``. Une cellule vide d'une table source reste vide (elle
  n'est pas « manquante »).
- **Hybride, source-first** pour les exports (les .xlsx I3F sont
  l'extraction autoritaire des outils externes Solibri/ArchiCAD) ;
  l'audit BIMData fournit les stats de contrôle en repli et les
  croisements agrégés du consolidé.
- **Fidélité « tables à plat »** : mêmes onglets, colonnes, ordre, unités
  et vocabulaire que les sources ; les tableaux croisés / blocs de
  synthèse sont rendus en tables structurées équivalentes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import openpyxl
import xlsxwriter
from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from ..audit.engine import AuditResult
from .avp_snapshot import build_sources_from_snapshot, count_envelope_walls
from .avp_sources import AvpSourcePaths, AvpSources, SheetTable, load_sources
from .context import ReportProjectContext
from .pdf_export import docx_to_pdf
from .theming import (
    BIMDATA_FONT_FALLBACK,
    BIMDATA_FONT_PRIMARY,
    BIMDATA_GRANITE,
    BIMDATA_PRIMARY,
    BIMDATA_SECONDARY,
)
from .word_report import NOT_AVAILABLE, _add_heading, _hex_to_rgb, _kpi_table, _shade_cell
from .xlsx_annex import _build_formats, write_safe

# Convention de nommage documentaire I3F, **générée à partir de données
# projet confirmées** :
#
#     YYMMDD <NomProjet> <CodeProjet> <Phase> - <TypeLivrable>.<ext>
#
# ``YYMMDD`` = date de génération du livrable. Chaque livrable a un libellé
# de type et une extension fixes ; le nom du projet, le code (ESI) et la
# phase sont injectés depuis les valeurs confirmées par l'utilisateur.
_DELIVERABLE_LABELS: dict[str, tuple[str, str]] = {
    "controle": ("Contrôle Maquettes", "xlsx"),
    "shab": ("export SHAB maquette", "xlsx"),
    "zones_espaces": ("Export Zones et Espaces", "xlsx"),
    "enveloppe": ("Extraction surface enveloppe", "xlsx"),
    "menuiseries": ("export Menuiseries", "xlsx"),
    "analyse": ("Rapport analyse BIM", "docx"),
}

# Caractères interdits / risqués dans un nom de fichier (séparateurs de
# chemin, caractères réservés Windows). Remplacés par un espace.
_FILENAME_BAD = '/\\:*?"<>|\r\n\t'


def _sanitize_filename_part(value: str | None) -> str:
    """Nettoie un fragment de nom de fichier (séparateurs, espaces)."""
    if not value:
        return ""
    out = "".join(" " if c in _FILENAME_BAD else c for c in str(value))
    return " ".join(out.split()).strip()


def _deliverable_filename(
    key: str, *, date: str, project_name: str, project_code: str, phase: str
) -> str:
    """Construit le nom d'un livrable selon la convention I3F.

    ``YYMMDD Nom Code Phase - TypeLivrable.ext`` — les fragments vides
    (code / phase absents) sont simplement omis (jamais inventés).
    """
    label, ext = _DELIVERABLE_LABELS[key]
    head_parts = [
        _sanitize_filename_part(date),
        _sanitize_filename_part(project_name),
        _sanitize_filename_part(project_code),
        _sanitize_filename_part(phase),
    ]
    head = " ".join(p for p in head_parts if p)
    label = _sanitize_filename_part(label)
    return f"{head} - {label}.{ext}"


_CONTROLE_STATS_SHEETS = (
    "Zones Nommage",
    "Pièces Nommage",
    "ARC absence de matériau",
    "Zones ObjectType",
)


@dataclass
class AvpMeta:
    # Défauts **génériques** : aucune identité client codée en dur (le nom
    # et le code réels viennent des données confirmées / des sources I3F).
    project_name: str = "Projet"
    project_code: str = ""
    phase: str = "AVP"
    auditor: str = "AMO BIM"
    # Métadonnées opérationnelles du contrôle (issues du rapport I3F de
    # référence, fournies par l'appelant). Absentes → NOT_AVAILABLE, jamais
    # inventées.
    usages_bim: list[str] | None = None
    nombre_logements: str | None = None
    temoin_virtuel: str | None = None
    date_controle: str | None = None
    auteur_controle: str | None = None


@dataclass
class AvpReportPack:
    controle_xlsx: Path
    shab_xlsx: Path
    zones_espaces_xlsx: Path
    enveloppe_xlsx: Path
    menuiseries_xlsx: Path
    analyse_docx: Path
    analyse_pdf: Path | None = None

    def paths(self) -> list[Path]:
        out = [
            self.controle_xlsx,
            self.shab_xlsx,
            self.zones_espaces_xlsx,
            self.enveloppe_xlsx,
            self.menuiseries_xlsx,
            self.analyse_docx,
        ]
        if self.analyse_pdf is not None:
            out.append(self.analyse_pdf)
        return out


class AvpQaError(RuntimeError):
    """Livrable(s) client vide(s) alors que la maquette contient des données.

    Levée par la QA gate post-génération : un export sort sans aucune ligne
    métier alors que le snapshot expose des espaces / murs / zones
    exploitables. On refuse de livrer un fichier qui ne contient que le
    bandeau.
    """

    def __init__(self, empty: list[str]):
        self.empty = empty
        super().__init__(
            "Annexe(s) vide(s) malgré des données exploitables dans la maquette : "
            + ", ".join(empty)
            + ". Livraison refusée (ni sources I3F ni extraction snapshot n'ont "
            "produit de lignes)."
        )


# Marqueurs d'échafaudage à ignorer lors du comptage des lignes métier.
_QA_SCAFFOLD = {
    _n
    for _n in (
        NOT_AVAILABLE.strip().lower(),
        "(onglet vide dans la source i3f)",
        "synthèse",
    )
}


def _count_business_rows(path: Path) -> int:
    """Ouvre une annexe et compte ses **lignes métier**.

    Ignore le bandeau (3 premières lignes), la ligne d'en-tête de chaque
    onglet, les marqueurs d'échafaudage (``NOT_AVAILABLE``, onglet vide) et
    le bloc « Synthèse » (KPI). Sert de garde qualité anti-livrable vide.
    """
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return 0
    total = 0
    try:
        for ws in wb.worksheets:
            header_seen = False
            for row in ws.iter_rows(min_row=4, values_only=True):
                cells = [c for c in row if c not in (None, "")]
                if not cells:
                    continue
                first = str(cells[0]).strip().lower()
                if first == "synthèse":
                    break  # début du bloc KPI → stop pour cet onglet
                if first in _QA_SCAFFOLD:
                    continue
                if not header_seen:
                    header_seen = True  # 1re ligne utile = en-tête
                    continue
                total += 1
    finally:
        wb.close()
    return total


# ── Helpers Excel (charte BIMData réutilisée) ──────────────────────────────


def _cell(v):
    """Valeur cellule sûre : blanc pour vide, date ISO, sinon brut."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return v


def _write_banner(ws, fmts, supertitle: str, title: str) -> int:
    """Bannière BIMData (supertitle + filet jaune + titre). Renvoie la
    prochaine ligne libre."""
    write_safe(ws, 0, 0, f"BIMDATA — {supertitle}", fmts["supertitle"])
    write_safe(ws, 1, 0, "", fmts["accent_filet"])
    ws.set_row(1, 4)  # filet jaune fin
    write_safe(ws, 2, 0, title, fmts["title"])
    return 4


def _write_flat_table(ws, fmts, table: SheetTable | None, *, start_row: int) -> int:
    """Écrit une table à plat (en-têtes brandés + lignes zébrées).

    ``table is None`` → mention ``NOT_AVAILABLE``. Renvoie la ligne suivante.
    """
    if table is None or not table.headers:
        write_safe(ws, start_row, 0, NOT_AVAILABLE, fmts["row"])
        return start_row + 1
    for c, h in enumerate(table.headers):
        write_safe(ws, start_row, c, h, fmts["header"])
        ws.set_column(c, c, max(12, min(42, len(str(h)) + 3)))
    ws.set_row(start_row, 28)
    r = start_row
    for i, rowvals in enumerate(table.rows):
        r = start_row + 1 + i
        fmt = fmts["row_alt"] if i % 2 == 0 else fmts["row"]
        for c, v in enumerate(rowvals):
            write_safe(ws, r, c, _cell(v), fmt)
    ws.freeze_panes(start_row + 1, 0)
    return r + 1


def _new_workbook(path: Path):
    wb = xlsxwriter.Workbook(str(path), {"strings_to_formulas": False})
    return wb, _build_formats(wb)


# ── Builders des 5 Excel ───────────────────────────────────────────────────


def _build_controle_maquettes_xlsx(path, result, sources, meta) -> Path:
    src = sources.controle if sources else None
    wb, fmts = _new_workbook(path)
    ws = wb.add_worksheet("Grille de contrôle")
    row = _write_banner(
        ws,
        fmts,
        "CONTRÔLE MAQUETTES AVP",
        f"{meta.project_name} {meta.project_code} — Contrôle Maquettes {meta.phase}",
    )

    # Bloc entête projet (source I3F, sinon métadonnées d'appel).
    header = (src.header if src else {}) or {}
    fallbacks = {"projet": meta.project_name, "esi": meta.project_code, "phase": meta.phase}
    for label, key in (("Projet", "projet"), ("ESI", "esi"), ("Phase", "phase")):
        val = header.get(key)
        if val in (None, ""):
            val = fallbacks[key]
        write_safe(ws, row, 0, label, fmts["kpi_key"])
        write_safe(ws, row, 1, _cell(val), fmts["kpi_val"])
        row += 1
    row += 1

    # Légende.
    write_safe(ws, row, 0, "Légende", fmts["h2"])
    row += 1
    legend = (src.legend if src else {}) or {
        0: "Non fourni / non trouvé",
        1: "Insuffisant : à reprendre ou compléter",
        2: "Satisfaisant",
    }
    for code in sorted(legend):
        write_safe(ws, row, 0, code, fmts["kpi_key"])
        write_safe(ws, row, 1, legend[code], fmts["kpi_val"])
        row += 1
    row += 1

    # Grille de contrôle.
    write_safe(ws, row, 0, "Grille de contrôle", fmts["h2"])
    row += 1
    _write_flat_table(ws, fmts, src.grille if src else None, start_row=row)

    # Onglets de stats conformité : synthèse KPI + **grille détaillée
    # complète** (listes de contrôle exploitables I3F : noms, éléments…).
    for name in _CONTROLE_STATS_SHEETS:
        ws_s = wb.add_worksheet(name[:31])
        r = _write_banner(ws_s, fmts, "CONTRÔLE MAQUETTES AVP", name)
        stats = _controle_stats(name, result, src)
        write_safe(ws_s, r, 0, "Synthèse", fmts["h2"])
        _write_stats_block(ws_s, fmts, stats, start_row=r + 1)
        grid = _controle_grid(name, src)
        if grid:
            write_safe(ws_s, r + 4, 0, "Détail", fmts["h2"])
            _write_grid(ws_s, fmts, grid.rows, start_row=r + 5)
    wb.close()
    return path


def _controle_grid(name: str, src):
    """Grille détaillée d'un onglet de contrôle (matching nom normalisé)."""
    if not src or not src.stat_grids:
        return None
    for key, grid in src.stat_grids.items():
        if _norm(key).replace("bsence", "absence") == _norm(name):
            return grid
    return None


def _controle_stats(name: str, result: AuditResult | None, src) -> dict | None:
    """Stats conformité d'un onglet — source-first, audit en repli, sinon None."""
    if src and src.stats:
        # La clé source peut porter la faute d'origine ("ARC bsence…").
        for key, val in src.stats.items():
            if _norm(key) == _norm(name) or _norm(key).replace("bsence", "absence") == _norm(name):
                if val:
                    return val
    # Repli audit (si snapshot chargé) — comptage simple.
    if result is not None:
        return _audit_stats(name, result)
    return None


def _audit_stats(name: str, result: AuditResult) -> dict | None:
    from ..audit.findings import Theme

    snap = result.snapshot
    theme_map = {
        "Zones Nommage": (Theme.NAMING_ZONE, len(snap.zones or [])),
        "Pièces Nommage": (Theme.NAMING_SPACE, len(snap.spaces or [])),
        "Zones ObjectType": (Theme.NAMING_ZONE, len(snap.zones or [])),
    }
    if name in theme_map:
        theme, total = theme_map[name]
        nc = len({f.element_uuid for f in result.findings if f.theme == theme and f.element_uuid})
        if total == 0:
            return None
        conf = total - nc
        return {
            "label": "Nombre de Noms",
            "total": total,
            "conforme": conf,
            "conforme_ratio": conf / total if total else None,
            "non_conforme": nc,
            "non_conforme_ratio": nc / total if total else None,
        }
    if "matériau" in name.lower():
        elements = snap.elements or []
        total = len(elements)
        if total == 0:
            return None
        sans = sum(1 for e in elements if not (e.get("materials")))
        return {
            "label": "Nombre d'éléments sans matériau",
            "total": total,
            "non_conforme": sans,
            "non_conforme_ratio": sans / total if total else None,
        }
    return None


def _write_stats_block(ws, fmts, stats: dict | None, *, start_row: int) -> None:
    if not stats:
        write_safe(ws, start_row, 0, NOT_AVAILABLE, fmts["row"])
        return
    # Structure « nommage » (avec conforme) ou « matériau » (sans conforme).
    if "conforme" in stats:
        labels = [
            ("Indicateur", "label"),
            ("Total", "total"),
            ("Conforme", "conforme"),
            ("Taux conforme", "conforme_ratio"),
            ("Non conforme", "non_conforme"),
            ("Taux non conforme", "non_conforme_ratio"),
        ]
    else:
        labels = [
            ("Indicateur", "label"),
            ("Total éléments", "total"),
            ("Sans matériau", "non_conforme"),
            ("Taux sans matériau", "non_conforme_ratio"),
        ]
    for c, (title, _key) in enumerate(labels):
        write_safe(ws, start_row, c, title, fmts["header"])
        ws.set_column(c, c, 20)
    for c, (_title, key) in enumerate(labels):
        v = stats.get(key)
        write_safe(ws, start_row + 1, c, "" if v is None else v, fmts["row_alt"])


def _looks_like_header(vals: list) -> bool:
    return sum(1 for v in vals if isinstance(v, str) and v.strip()) >= 3


def _write_grid(ws, fmts, rows: list[list], *, start_row: int) -> int:
    """Reproduit une grille brute (pivot/synthèse I3F) en table à plat.

    La 1re ligne « en-tête » (≥ 3 cellules texte) est stylée ; les autres
    sont zébrées. Préserve l'ordre et le contenu source.
    """
    if not rows:
        write_safe(ws, start_row, 0, NOT_AVAILABLE, fmts["row"])
        return start_row + 1
    header_idx = next((i for i, r in enumerate(rows) if _looks_like_header(r)), None)
    ncols = max(len(r) for r in rows)
    for c in range(ncols):
        ws.set_column(c, c, 18)
    r = start_row
    for i, rowvals in enumerate(rows):
        r = start_row + i
        if i == header_idx:
            fmt = fmts["header"]
            ws.set_row(r, 26)
        else:
            fmt = fmts["row_alt"] if i % 2 == 0 else fmts["row"]
        for c in range(ncols):
            v = rowvals[c] if c < len(rowvals) else None
            write_safe(ws, r, c, _cell(v), fmt)
    if header_idx is not None:
        ws.freeze_panes(start_row + header_idx + 1, 0)
    return r + 1


def _build_multisheet_export_xlsx(path, banner: str, title: str, multi, meta) -> Path:
    """Export reproduisant **tous** les onglets source (pivots + détail)."""
    wb, fmts = _new_workbook(path)
    grids = (multi.grids if multi else None) or []
    if not grids:
        ws = wb.add_worksheet(_safe_sheet(title))
        row = _write_banner(ws, fmts, banner, f"{meta.project_name} {meta.project_code} — {title}")
        write_safe(ws, row, 0, NOT_AVAILABLE, fmts["row"])
        wb.close()
        return path
    for g in grids:
        ws = wb.add_worksheet(_safe_sheet(g.title))
        row = _write_banner(
            ws, fmts, banner, f"{meta.project_name} {meta.project_code} — {g.title}"
        )
        if g.rows:
            _write_grid(ws, fmts, g.rows, start_row=row)
        else:
            # Onglet source vide : préservé (structure I3F stricte) mais
            # signalé comme tel (ce n'est PAS une donnée manquante).
            write_safe(ws, row, 0, "(onglet vide dans la source I3F)", fmts["row"])
    wb.close()
    return path


def _build_enveloppe_xlsx(path, sources, meta) -> Path:
    src = sources.enveloppe if sources else None
    wb, fmts = _new_workbook(path)
    # Proximité I3F : conserver le nom d'onglet source (« TDB 2022 04.2… »).
    ws = wb.add_worksheet(
        _safe_sheet((src.sheet_title if src else None) or "Extraction surface enveloppe")
    )
    row = _write_banner(
        ws,
        fmts,
        "EXTRACTION SURFACE ENVELOPPE",
        f"{meta.project_name} {meta.project_code} — Extraction surface enveloppe",
    )
    row = _write_flat_table(ws, fmts, src.table if src else None, start_row=row)
    row += 1
    # Bloc synthèse.
    write_safe(ws, row, 0, "Synthèse", fmts["h2"])
    row += 1
    synth = [
        ("Superficie des façades", src.superficie_facades if src else None),
        ("Superficie des menuiseries", src.superficie_menuiseries if src else None),
        ("SHAB", src.shab if src else None),
        ("ratio FAC/SHAB", src.ratio_fac_shab if src else None),
        ("Seuil 3F 2026", src.seuil_3f if src else None),
    ]
    for label, val in synth:
        write_safe(ws, row, 0, label, fmts["kpi_key"])
        write_safe(ws, row, 1, NOT_AVAILABLE if val is None else val, fmts["kpi_val"])
        row += 1
    wb.close()
    return path


def _build_menuiseries_xlsx(path, sources, meta) -> Path:
    src = sources.menuiseries if sources else None
    wb, fmts = _new_workbook(path)
    # Proximité I3F : conserver le nom d'onglet source (« TDB 2022 05.1… »).
    ws = wb.add_worksheet(_safe_sheet((src.sheet_title if src else None) or "Menuiseries"))
    row = _write_banner(
        ws,
        fmts,
        "EXPORT MENUISERIES",
        f"{meta.project_name} {meta.project_code} — Export Menuiseries",
    )
    row = _write_flat_table(ws, fmts, src.table if src else None, start_row=row)
    row += 1
    write_safe(ws, row, 0, "Nombre de types de menuiseries", fmts["kpi_key"])
    nb = src.nombre_types if src else None
    write_safe(ws, row, 1, NOT_AVAILABLE if nb is None else nb, fmts["kpi_val"])
    wb.close()
    return path


# ── Consolidé « Analyse BIM AVP » (.docx, helpers word_report réutilisés) ───


def _setup_docx() -> Document:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = BIMDATA_FONT_PRIMARY
    style.font.size = Pt(10)
    style.font.color.rgb = _hex_to_rgb(BIMDATA_GRANITE)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), BIMDATA_FONT_PRIMARY)
    rfonts.set(qn("w:hAnsi"), BIMDATA_FONT_PRIMARY)
    rfonts.set(qn("w:cs"), BIMDATA_FONT_FALLBACK)
    return doc


def _pct(v) -> str:
    return f"{v * 100:.0f} %" if isinstance(v, (int, float)) else NOT_AVAILABLE


def _build_analyse_bim_avp_docx(path, result, sources, meta) -> Path:
    doc = _setup_docx()

    # Titre / bandeau.
    title = doc.add_paragraph()
    run = title.add_run(f"BIMDATA — Analyse BIM {meta.phase}")
    run.bold = True
    run.font.size = Pt(12)
    run.font.color.rgb = _hex_to_rgb(BIMDATA_SECONDARY)
    h = doc.add_paragraph()
    run = h.add_run(f"Rapport d'analyse BIM {meta.phase} — {meta.project_name} {meta.project_code}")
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = _hex_to_rgb(BIMDATA_PRIMARY)

    _kpi_table(
        doc,
        [
            ("Projet", f"{meta.project_name} {meta.project_code}"),
            ("Phase", meta.phase),
            ("Date", date.today().isoformat()),
            ("Auteur", meta.auditor),
        ],
    )

    ctrl = sources.controle if sources else None
    env = sources.enveloppe if sources else None
    pieces = _stat_lookup(ctrl, "Pièces Nommage")
    zones = _stat_lookup(ctrl, "Zones Nommage")
    materiau = _stat_lookup(ctrl, "ARC absence de matériau")

    # 1. Données d'entrée
    _add_heading(doc, "1. Données d'entrée", level=1)
    _write_donnees_entree(doc, ctrl, meta)

    # 2. Usages BIM 3F
    _add_heading(doc, "2. Usages BIM 3F", level=1)
    if meta.usages_bim:
        for u in meta.usages_bim:
            doc.add_paragraph(f"• {u}", style="List Bullet")
    else:
        doc.add_paragraph("Usages BIM 3F : " + NOT_AVAILABLE + ".")

    # 3. Synthèse
    _add_heading(doc, "3. Synthèse", level=1)
    doc.add_paragraph(
        f"Analyse BIM de la maquette {meta.project_name} {meta.project_code} en phase "
        f"{meta.phase}, consolidant le contrôle des maquettes, les exports SHAB, "
        "zones/espaces, enveloppe et menuiseries. Les indicateurs ci-dessous "
        "proviennent des livrables d'extraction ; toute donnée absente est "
        "signalée « Information non disponible dans les documents fournis. »."
    )
    _write_audit_synthese(doc, result)

    # 4. Indicateurs de conformité
    _add_heading(doc, "4. Indicateurs de conformité", level=1)
    ratio = env.ratio_fac_shab if env else None
    seuil = env.seuil_3f if env else None  # jamais inventé : None si absent de la source
    if isinstance(ratio, (int, float)) and isinstance(seuil, (int, float)):
        ratio_ok = "Conforme" if ratio >= seuil else "Non conforme"
    else:
        ratio_ok = NOT_AVAILABLE
    seuil_label = (
        f"Seuil 3F 2026 (≥ {seuil})" if isinstance(seuil, (int, float)) else "Seuil 3F 2026"
    )
    _kpi_table(
        doc,
        [
            (
                "Taux de conformité nommage pièces",
                _pct(pieces.get("conforme_ratio")) if pieces else NOT_AVAILABLE,
            ),
            (
                "Taux de conformité nommage zones",
                _pct(zones.get("conforme_ratio")) if zones else NOT_AVAILABLE,
            ),
            (
                "Éléments sans matériau (taux)",
                _pct(materiau.get("non_conforme_ratio")) if materiau else NOT_AVAILABLE,
            ),
            (
                "Ratio FAC/SHAB",
                f"{ratio:.3f}" if isinstance(ratio, (int, float)) else NOT_AVAILABLE,
            ),
            (seuil_label, ratio_ok),
        ],
    )

    # 5. Écarts (source vs snapshot BIMData quand disponible)
    _add_heading(doc, "5. Écarts", level=1)
    _write_ecarts(doc, result, sources)

    # 6. Grille de contrôle (paysage pour la lisibilité des 6 colonnes)
    _set_orientation(doc, WD_ORIENT.LANDSCAPE)
    _add_heading(doc, "6. Grille de contrôle", level=1)
    _write_grille_table(doc, ctrl)
    _set_orientation(doc, WD_ORIENT.PORTRAIT)

    # 7. Points bloquants
    _add_heading(doc, "7. Points bloquants", level=1)
    blockers = _points_bloquants(ctrl, env, ratio, seuil)
    if blockers:
        for b in blockers:
            doc.add_paragraph(f"• {b}", style="List Bullet")
    else:
        doc.add_paragraph("Aucun point bloquant identifié à partir des livrables fournis.")

    # 8. Recommandations AMO BIM
    _add_heading(doc, "8. Recommandations AMO BIM", level=1)
    recs = _recommandations(pieces, zones, materiau, ratio, seuil)
    for r in recs:
        doc.add_paragraph(f"• {r}", style="List Bullet")

    # 9. Annexes — statistiques de conformité
    _add_heading(doc, "9. Annexes — statistiques de conformité", level=1)
    _write_stats_annex(doc, ctrl)

    doc.save(str(path))
    return path


def _fmt_meta(v) -> str:
    if v in (None, ""):
        return NOT_AVAILABLE
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return str(v)


def _set_orientation(doc, orient) -> None:
    """Nouvelle section avec orientation portrait/paysage (lisibilité des
    tableaux larges en livrable client)."""
    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    sec.orientation = orient
    w, h = sec.page_width, sec.page_height
    if orient == WD_ORIENT.LANDSCAPE and w < h:
        sec.page_width, sec.page_height = h, w
    elif orient == WD_ORIENT.PORTRAIT and w > h:
        sec.page_width, sec.page_height = h, w
    sec.left_margin = Cm(1.5)
    sec.right_margin = Cm(1.5)


# Largeurs (cm) des 6 colonnes de la grille de contrôle en paysage.
_GRILLE_COL_WIDTHS = (2.0, 6.5, 5.0, 3.0, 3.0, 7.0)


def _docx_header_table(doc, headers, *, col_widths=None):
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl.style = "Light Grid Accent 1"
    tbl.autofit = False
    tbl.allow_autofit = False
    for i, h in enumerate(headers):
        cell = tbl.rows[0].cells[i]
        cell.text = str(h)
        if col_widths and i < len(col_widths):
            cell.width = Cm(col_widths[i])
        _shade_cell(cell, BIMDATA_PRIMARY)
        for p in cell.paragraphs:
            for r in p.runs:
                r.font.color.rgb = RGBColor(255, 255, 255)
                r.bold = True
    return tbl


def _write_audit_synthese(doc, result) -> None:
    """Synthèse de l'audit BIMData réel (sévérité, thèmes, quantités
    manquantes) — le consolidé ne doit pas ignorer l'``AuditResult``."""
    if result is None:
        doc.add_paragraph("Audit BIMData automatisé : " + NOT_AVAILABLE + " (aucun audit chargé).")
        return
    by_sev = result.count_by_severity()
    by_theme = result.count_by_theme()
    by_type = result.count_by_error_type()
    p = doc.add_paragraph()
    p.add_run("Audit BIMData automatisé de la maquette active").bold = True
    # Répartition par sévérité COMPLÈTE (CRITICAL→INFO) pour que le total
    # se réconcilie côté client.
    _kpi_table(
        doc,
        [
            ("Anomalies détectées", str(len(result.findings))),
            ("Taux de conformité (pondéré)", f"{result.conformity_rate() * 100:.0f} %"),
            ("CRITICAL", str(by_sev.get("CRITICAL", 0))),
            ("HIGH", str(by_sev.get("HIGH", 0))),
            ("MEDIUM", str(by_sev.get("MEDIUM", 0))),
            ("LOW", str(by_sev.get("LOW", 0))),
            ("INFO", str(by_sev.get("INFO", 0))),
            ("Quantités manquantes", str(by_type.get("spatial_missing_quantity", 0))),
        ],
    )
    top = sorted(by_theme.items(), key=lambda kv: -kv[1])[:5]
    if top:
        doc.add_paragraph("Principaux thèmes en écart :")
        for theme, count in top:
            doc.add_paragraph(f"• {theme} : {count}", style="List Bullet")


def _write_donnees_entree(doc, ctrl, meta) -> None:
    h = (ctrl.header if ctrl else {}) or {}
    _kpi_table(
        doc,
        [
            ("Opération", _fmt_meta(meta.nombre_logements)),
            ("Maquettes IFC transmises le", _fmt_meta(h.get("maquettes ifc transmises le"))),
            ("Date d'analyse", _fmt_meta(h.get("date d'analyse"))),
            ("Version d'analyse", _fmt_meta(h.get("version d'analyse"))),
            ("Date du contrôle", _fmt_meta(meta.date_controle)),
            ("Auteur du contrôle", _fmt_meta(meta.auteur_controle)),
            ("Témoin virtuel", _fmt_meta(meta.temoin_virtuel)),
        ],
    )


def _write_grille_table(doc, ctrl, *, cap: int = 40) -> None:
    g = ctrl.grille if ctrl else None
    if not g or not g.headers:
        doc.add_paragraph(NOT_AVAILABLE)
        return
    # Largeurs adaptées uniquement pour la grille standard 6 colonnes.
    widths = _GRILLE_COL_WIDTHS if len(g.headers) == len(_GRILLE_COL_WIDTHS) else None
    tbl = _docx_header_table(doc, g.headers, col_widths=widths)
    for rowvals in g.rows[:cap]:
        cells = tbl.add_row().cells
        for i in range(len(cells)):
            v = rowvals[i] if i < len(rowvals) else None
            cells[i].text = "" if v in (None, "") else str(_cell(v))
            if widths and i < len(widths):
                cells[i].width = Cm(widths[i])
    if len(g.rows) > cap:
        doc.add_paragraph(
            f"… {len(g.rows) - cap} lignes supplémentaires dans le fichier "
            "« Contrôle Maquettes AVP ».",
            style="Intense Quote",
        )


def _write_stats_annex(doc, ctrl) -> None:
    stats = (ctrl.stats if ctrl else {}) or {}
    if not any(stats.values()):
        doc.add_paragraph(NOT_AVAILABLE)
        return
    for name, st in stats.items():
        if not st:
            continue
        p = doc.add_paragraph()
        p.add_run(name).bold = True
        if "conforme" in st:
            detail = (
                f"total {st.get('total')} · conformes {st.get('conforme')} "
                f"({_pct(st.get('conforme_ratio'))}) · non conformes {st.get('non_conforme')}"
            )
        else:
            detail = (
                f"total {st.get('total')} · sans matériau {st.get('non_conforme')} "
                f"({_pct(st.get('non_conforme_ratio'))})"
            )
        doc.add_paragraph(f"• {detail}", style="List Bullet")


def _write_ecarts(doc, result, sources) -> None:
    env = sources.enveloppe if sources else None
    src_shab = env.shab if env else None
    snap_shab = _snapshot_shab_total(result)
    tbl = doc.add_table(rows=1, cols=4)
    tbl.style = "Light Grid Accent 1"
    for i, txt in enumerate(["Indicateur", "Source I3F", "Snapshot BIMData", "Écart"]):
        cell = tbl.rows[0].cells[i]
        cell.text = txt
        _shade_cell(cell, BIMDATA_PRIMARY)
        for p in cell.paragraphs:
            for r in p.runs:
                r.font.color.rgb = RGBColor(255, 255, 255)
                r.bold = True
    ecart = ""
    if isinstance(src_shab, (int, float)) and isinstance(snap_shab, (int, float)):
        ecart = f"{src_shab - snap_shab:+.2f}"
    row = tbl.add_row().cells
    row[0].text = "SHAB totale (m²)"
    row[1].text = f"{src_shab:.2f}" if isinstance(src_shab, (int, float)) else NOT_AVAILABLE
    row[2].text = f"{snap_shab:.2f}" if isinstance(snap_shab, (int, float)) else NOT_AVAILABLE
    row[3].text = ecart or NOT_AVAILABLE
    doc.add_paragraph(
        "L'écart n'est calculé que lorsque la valeur source ET la valeur "
        "snapshot BIMData sont disponibles.",
        style="Intense Quote",
    )


def _snapshot_shab_total(result: AuditResult | None) -> float | None:
    if result is None or result.snapshot is None:
        return None
    total = 0.0
    found = False
    for sp in result.snapshot.spaces or []:
        for pset in sp.get("property_sets") or []:
            pn = (pset.get("name") or "").lower()
            if not (pn.startswith("basequantities") or pn.startswith("qto_")):
                continue
            for prop in pset.get("properties") or []:
                if (prop.get("definition") or {}).get("name", "").lower() in (
                    "netfloorarea",
                    "grossfloorarea",
                ):
                    v = prop.get("value")
                    if isinstance(v, (int, float)):
                        total += float(v)
                        found = True
    return round(total, 2) if found else None


def _points_bloquants(ctrl, env, ratio, seuil) -> list[str]:
    out: list[str] = []
    if isinstance(ratio, (int, float)) and isinstance(seuil, (int, float)) and ratio < seuil:
        out.append(
            f"Ratio FAC/SHAB {ratio:.3f} inférieur au Seuil 3F 2026 ({seuil}) — enveloppe à revoir."
        )
    # Points de contrôle évalués 0 (Non fourni / non trouvé) dans la grille.
    if ctrl and ctrl.grille:
        try:
            eval_idx = ctrl.grille.headers.index("EVALUATION")
            pts_idx = ctrl.grille.headers.index("POINTS DE CONTROLE")
        except ValueError:
            eval_idx = pts_idx = None
        if eval_idx is not None:
            zeros = [
                r[pts_idx] for r in ctrl.grille.rows if str(r[eval_idx]).strip() in ("0", "0.0")
            ]
            for pt in zeros[:8]:
                out.append(f"Point de contrôle non satisfait (éval. 0) : {pt}")
    return out


def _recommandations(pieces, zones, materiau, ratio, seuil) -> list[str]:
    recs: list[str] = []
    for label, stat in (("pièces", pieces), ("zones", zones)):
        nc = stat.get("non_conforme") if stat else None
        if isinstance(nc, (int, float)) and nc > 0:
            recs.append(
                f"Reprendre le nommage de {int(nc)} {label} non conformes (CCH BIM I3F chap. 6.3)."
            )
    if (
        materiau
        and isinstance(materiau.get("non_conforme"), (int, float))
        and materiau["non_conforme"] > 0
    ):
        recs.append(
            f"Compléter le matériau sur {int(materiau['non_conforme'])} éléments ARC sans matériau."
        )
    if isinstance(ratio, (int, float)) and isinstance(seuil, (int, float)) and ratio < seuil:
        recs.append(
            "Revoir la modélisation de l'enveloppe pour atteindre le ratio FAC/SHAB attendu."
        )
    if not recs:
        recs.append("Aucune action corrective majeure identifiée à partir des livrables fournis.")
    return recs


# ── Utilitaires ────────────────────────────────────────────────────────────


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _safe_sheet(title: str) -> str:
    bad = set(r"[]:*?/\\")
    return "".join(c for c in title if c not in bad)[:31] or "Feuille"


def _stat_lookup(ctrl, name: str) -> dict:
    if not ctrl or not ctrl.stats:
        return {}
    for key, val in ctrl.stats.items():
        if _norm(key).replace("bsence", "absence") == _norm(name):
            return val or {}
    return {}


# ── Orchestrateur ──────────────────────────────────────────────────────────


def write_avp_i3f_report_pack(
    result: AuditResult | None,
    output_dir: str | Path,
    *,
    sources: AvpSourcePaths | AvpSources | None = None,
    project_name: str = "Projet",
    project_code: str = "",
    phase: str = "AVP",
    auditor: str = "AMO BIM",
    date: str | None = None,
    usages_bim: list[str] | None = None,
    nombre_logements: str | None = None,
    temoin_virtuel: str | None = None,
    date_controle: str | None = None,
    auteur_controle: str | None = None,
    export_pdf: bool = True,
    context: ReportProjectContext | None = None,  # noqa: ARG001 (compat future)
) -> AvpReportPack:
    """Génère le pack de livrables AVP I3F dans ``output_dir``.

    Les noms de livrables suivent la convention documentaire I3F,
    **générés à partir des données projet confirmées** :
    ``YYMMDD <NomProjet> <CodeProjet> <Phase> - <TypeLivrable>.<ext>``.

    Args:
        result: ``AuditResult`` BIMData (peut être ``None`` : le pack se
            limite alors aux données sources fournies).
        output_dir: dossier de sortie (créé si besoin).
        sources: chemins des .xlsx I3F (``AvpSourcePaths``) ou sources déjà
            chargées (``AvpSources``). ``None`` → pack sans données externes
            (colonnes → ``NOT_AVAILABLE``).
        project_name, project_code, phase: identité projet **confirmée**
            injectée dans les noms de livrables (et les entêtes).
        date: préfixe daté ``YYMMDD`` des noms de livrables. ``None`` →
            date de génération (aujourd'hui).
        usages_bim, nombre_logements, temoin_virtuel, date_controle,
            auteur_controle: métadonnées opérationnelles du contrôle (issues
            du rapport I3F de référence) pour les sections « Données
            d'entrée » et « Usages BIM 3F ». Absentes → ``NOT_AVAILABLE``.
            Exception : ``auteur_controle`` non fourni est aligné sur
            ``auditor`` (le rédacteur AMO est aussi l'auteur du contrôle
            par défaut) plutôt que ``NOT_AVAILABLE``.
        export_pdf: tente la conversion .docx → .pdf (best-effort).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Date de génération du livrable (YYMMDD) si non imposée par l'appelant.
    gen_date = (
        date.strip()
        if isinstance(date, str) and date.strip()
        else datetime.now().strftime("%y%m%d")
    )
    # « Auteur du contrôle » : champ opérationnel distinct du rédacteur
    # AMO (``auditor``). Sur le pack I3F il est facultatif ; plutôt que
    # d'écrire ``NOT_AVAILABLE`` quand il n'est pas précisé, on l'aligne
    # sur ``auditor`` (donnée fournie par l'utilisateur, jamais inventée).
    # L'appelant peut toujours le distinguer en passant ``auteur_controle``.
    eff_auteur_controle = (
        auteur_controle if auteur_controle and auteur_controle.strip() else auditor
    )
    meta = AvpMeta(
        project_name=project_name,
        project_code=project_code,
        phase=phase,
        auditor=auditor,
        usages_bim=usages_bim,
        nombre_logements=nombre_logements,
        temoin_virtuel=temoin_virtuel,
        date_controle=date_controle,
        auteur_controle=eff_auteur_controle,
    )

    # Noms de livrables générés depuis l'identité projet confirmée
    # (convention I3F uniforme). On n'hérite plus du basename des sources :
    # le livrable BIMData porte l'identité et la date de génération.
    def _name(key: str) -> str:
        return _deliverable_filename(
            key,
            date=gen_date,
            project_name=project_name,
            project_code=project_code,
            phase=phase,
        )

    fn_controle = _name("controle")
    fn_shab = _name("shab")
    fn_zones = _name("zones_espaces")
    fn_env = _name("enveloppe")
    fn_men = _name("menuiseries")
    fn_analyse = _name("analyse")

    if isinstance(sources, AvpSourcePaths):
        sources = load_sources(sources)
    # sources est désormais AvpSources | None

    # ── Source-first, snapshot en repli ─────────────────────────────────
    # Les fichiers I3F priment (extraction autoritaire des outils externes).
    # Pour chaque export absent/vide, on génère depuis ``result.snapshot``
    # afin de ne jamais livrer une annexe réduite au seul bandeau.
    snap = result.snapshot if result is not None else None
    if snap is not None:
        fallback = build_sources_from_snapshot(snap)
        if sources is None:
            sources = AvpSources()
        if _multisheet_is_empty(sources.shab):
            sources.shab = fallback.shab
        if _multisheet_is_empty(sources.zones_espaces):
            sources.zones_espaces = fallback.zones_espaces
        if _tabular_is_empty(sources.enveloppe):
            sources.enveloppe = fallback.enveloppe
        if _tabular_is_empty(sources.menuiseries):
            sources.menuiseries = fallback.menuiseries

    controle = _build_controle_maquettes_xlsx(out / fn_controle, result, sources, meta)
    shab = _build_multisheet_export_xlsx(
        out / fn_shab,
        "EXPORT SHAB MAQUETTE",
        "AVP - export SHAB maquette",
        (sources.shab if sources else None),
        meta,
    )
    zones = _build_multisheet_export_xlsx(
        out / fn_zones,
        "EXPORT ZONES ET ESPACES",
        "Export Zones et Espaces",
        (sources.zones_espaces if sources else None),
        meta,
    )
    enveloppe = _build_enveloppe_xlsx(out / fn_env, sources, meta)
    menuiseries = _build_menuiseries_xlsx(out / fn_men, sources, meta)
    analyse = _build_analyse_bim_avp_docx(out / fn_analyse, result, sources, meta)

    pdf = docx_to_pdf(analyse) if export_pdf else None

    pack = AvpReportPack(
        controle_xlsx=controle,
        shab_xlsx=shab,
        zones_espaces_xlsx=zones,
        enveloppe_xlsx=enveloppe,
        menuiseries_xlsx=menuiseries,
        analyse_docx=analyse,
        analyse_pdf=pdf,
    )

    # ── QA gate : anti-livrable vide ────────────────────────────────────
    # On rouvre chaque annexe et on compte les lignes métier. Échec si un
    # export sort sans ligne alors que la maquette contient des entités
    # exploitables (espaces / murs / zones). On lève : le tool renverra un
    # statut d'erreur explicite plutôt qu'un fichier vide.
    empty = _qa_empty_deliverables(pack, snap)
    if empty:
        raise AvpQaError(empty)

    return pack


def _multisheet_is_empty(multi) -> bool:
    """Un ``MultiSheetSource`` est vide si aucun onglet ne porte de ligne."""
    if multi is None:
        return True
    grids = getattr(multi, "grids", None) or []
    return not any(getattr(g, "rows", None) for g in grids)


def _tabular_is_empty(src) -> bool:
    """Une source tabulaire (enveloppe/menuiseries) est vide sans lignes."""
    if src is None:
        return True
    table = getattr(src, "table", None)
    return table is None or not getattr(table, "rows", None)


def _qa_empty_deliverables(pack: AvpReportPack, snap) -> list[str]:
    """Liste des annexes vides alors que la maquette a des données."""
    if snap is None:
        return []
    problems: list[str] = []
    has_spaces_or_zones = bool(getattr(snap, "spaces", None)) or bool(getattr(snap, "zones", None))
    if has_spaces_or_zones:
        if _count_business_rows(pack.shab_xlsx) == 0:
            problems.append("SHAB")
        if _count_business_rows(pack.zones_espaces_xlsx) == 0:
            problems.append("Zones/Espaces")
    if count_envelope_walls(snap) > 0 and _count_business_rows(pack.enveloppe_xlsx) == 0:
        problems.append("Enveloppe")
    return problems
