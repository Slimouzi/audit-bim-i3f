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

import xlsxwriter
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from ..audit.engine import AuditResult
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

# Noms de livrables (préfixe daté I3F conservé, opération Tarare 0546L).
_PREFIX = "260211 Tarare 0546L"
FILENAMES = {
    "controle": f"{_PREFIX} Contrôle Maquettes AVP.xlsx",
    "shab": f"{_PREFIX} AVP - export SHAB maquette.xlsx",
    "zones_espaces": "260130 Tarare Export Zones et Espaces.xlsx",
    "enveloppe": "260130 Tarare Extraction surface enveloppe.xlsx",
    "menuiseries": "260130 Tarare export Menuiseries.xlsx",
    "analyse": f"{_PREFIX} Analyse BIM AVP.docx",
}

_CONTROLE_STATS_SHEETS = (
    "Zones Nommage",
    "Pièces Nommage",
    "ARC absence de matériau",
    "Zones ObjectType",
)


@dataclass
class AvpMeta:
    project_name: str = "Tarare"
    project_code: str = "0546L"
    phase: str = "AVP"
    auditor: str = "AMO BIM"


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

    # Onglets de stats conformité.
    for name in _CONTROLE_STATS_SHEETS:
        ws_s = wb.add_worksheet(name[:31])
        _write_banner(ws_s, fmts, "CONTRÔLE MAQUETTES AVP", name)
        stats = _controle_stats(name, result, src)
        _write_stats_block(ws_s, fmts, stats, start_row=4)
    wb.close()
    return path


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
    labels = [
        ("Indicateur", "label"),
        ("Total", "total"),
        ("Conforme", "conforme"),
        ("Taux conforme", "conforme_ratio"),
        ("Non conforme", "non_conforme"),
        ("Taux non conforme", "non_conforme_ratio"),
    ]
    for c, (title, _key) in enumerate(labels):
        write_safe(ws, start_row, c, title, fmts["header"])
        ws.set_column(c, c, 18)
    for c, (_title, key) in enumerate(labels):
        v = stats.get(key)
        write_safe(ws, start_row + 1, c, "" if v is None else v, fmts["row_alt"])


def _build_export_xlsx(path, banner: str, title: str, table: SheetTable | None, meta) -> Path:
    wb, fmts = _new_workbook(path)
    ws = wb.add_worksheet(_safe_sheet(title))
    row = _write_banner(ws, fmts, banner, f"{meta.project_name} {meta.project_code} — {title}")
    _write_flat_table(ws, fmts, table, start_row=row)
    wb.close()
    return path


def _build_enveloppe_xlsx(path, sources, meta) -> Path:
    src = sources.enveloppe if sources else None
    wb, fmts = _new_workbook(path)
    ws = wb.add_worksheet("Extraction surface enveloppe")
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
    ws = wb.add_worksheet("Menuiseries")
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

    # 1. Synthèse
    _add_heading(doc, "1. Synthèse", level=1)
    doc.add_paragraph(
        f"Analyse BIM de la maquette {meta.project_name} {meta.project_code} en phase "
        f"{meta.phase}, consolidant le contrôle des maquettes, les exports SHAB, "
        "zones/espaces, enveloppe et menuiseries. Les indicateurs ci-dessous "
        "proviennent des livrables d'extraction ; toute donnée absente est "
        "signalée « Information non disponible dans les documents fournis. »."
    )

    # 2. Indicateurs de conformité
    _add_heading(doc, "2. Indicateurs de conformité", level=1)
    ratio = env.ratio_fac_shab if env else None
    seuil = (env.seuil_3f if env else None) or 0.9
    ratio_ok = (
        "Conforme"
        if isinstance(ratio, (int, float)) and ratio >= seuil
        else ("Non conforme" if isinstance(ratio, (int, float)) else NOT_AVAILABLE)
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
            (f"Seuil 3F 2026 (≥ {seuil})", ratio_ok),
        ],
    )

    # 3. Écarts (source vs snapshot BIMData quand disponible)
    _add_heading(doc, "3. Écarts", level=1)
    _write_ecarts(doc, result, sources)

    # 4. Points bloquants
    _add_heading(doc, "4. Points bloquants", level=1)
    blockers = _points_bloquants(ctrl, env, ratio, seuil)
    if blockers:
        for b in blockers:
            doc.add_paragraph(f"• {b}", style="List Bullet")
    else:
        doc.add_paragraph("Aucun point bloquant identifié à partir des livrables fournis.")

    # 5. Recommandations AMO BIM
    _add_heading(doc, "5. Recommandations AMO BIM", level=1)
    recs = _recommandations(pieces, zones, materiau, ratio, seuil)
    for r in recs:
        doc.add_paragraph(f"• {r}", style="List Bullet")

    doc.save(str(path))
    return path


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
    if isinstance(ratio, (int, float)) and ratio < seuil:
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
    if isinstance(ratio, (int, float)) and ratio < seuil:
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
    project_name: str = "Tarare",
    project_code: str = "0546L",
    phase: str = "AVP",
    auditor: str = "AMO BIM",
    export_pdf: bool = True,
    context: ReportProjectContext | None = None,  # noqa: ARG001 (compat future)
) -> AvpReportPack:
    """Génère le pack de livrables AVP I3F dans ``output_dir``.

    Args:
        result: ``AuditResult`` BIMData (peut être ``None`` : le pack se
            limite alors aux données sources fournies).
        output_dir: dossier de sortie (créé si besoin).
        sources: chemins des .xlsx I3F (``AvpSourcePaths``) ou sources déjà
            chargées (``AvpSources``). ``None`` → pack sans données externes
            (colonnes → ``NOT_AVAILABLE``).
        export_pdf: tente la conversion .docx → .pdf (best-effort).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = AvpMeta(
        project_name=project_name, project_code=project_code, phase=phase, auditor=auditor
    )

    if isinstance(sources, AvpSourcePaths):
        sources = load_sources(sources)
    # sources est désormais AvpSources | None

    controle = _build_controle_maquettes_xlsx(out / FILENAMES["controle"], result, sources, meta)
    shab = _build_export_xlsx(
        out / FILENAMES["shab"],
        "EXPORT SHAB MAQUETTE",
        "AVP - export SHAB maquette",
        (sources.shab.table if sources and sources.shab else None),
        meta,
    )
    zones = _build_export_xlsx(
        out / FILENAMES["zones_espaces"],
        "EXPORT ZONES ET ESPACES",
        "Export Zones et Espaces",
        (sources.zones_espaces.table if sources and sources.zones_espaces else None),
        meta,
    )
    enveloppe = _build_enveloppe_xlsx(out / FILENAMES["enveloppe"], sources, meta)
    menuiseries = _build_menuiseries_xlsx(out / FILENAMES["menuiseries"], sources, meta)
    analyse = _build_analyse_bim_avp_docx(out / FILENAMES["analyse"], result, sources, meta)

    pdf = docx_to_pdf(analyse) if export_pdf else None

    return AvpReportPack(
        controle_xlsx=controle,
        shab_xlsx=shab,
        zones_espaces_xlsx=zones,
        enveloppe_xlsx=enveloppe,
        menuiseries_xlsx=menuiseries,
        analyse_docx=analyse,
        analyse_pdf=pdf,
    )
