"""Builder « Extraction surface enveloppe » (.xlsx) — ratio FAC/SHAB, Seuil 3F."""

from __future__ import annotations

from pathlib import Path

import xlsxwriter

from ..avp_sources import ENVELOPPE_MOA_HEADERS
from ..word_report import NOT_AVAILABLE
from ..xlsx_annex import write_safe
from .xlsx_common import _cell, _first_number, _formula_cached, _safe_sheet, _sum_table_col


def _build_enveloppe_xlsx(path, sources, meta) -> Path:
    src = sources.enveloppe if sources else None
    wb = xlsxwriter.Workbook(str(path), {"strings_to_formulas": False})
    ws = wb.add_worksheet(
        _safe_sheet((src.sheet_title if src else None) or "TDB 2022 04.2 - Extraction s...")
    )
    fmts = _enveloppe_moa_formats(wb)

    rows = (src.table.rows if src and src.table else []) or []
    headers = (src.table.headers if src and src.table and src.table.headers else None) or list(
        ENVELOPPE_MOA_HEADERS
    )

    widths = [10.86, 47.29, 14.86, 14.57, 11.29, 14.0, 11.43, 11.86, 13.0, 13.0]
    for c, width in enumerate(widths):
        ws.set_column(c, c, width)
    ws.set_row(0, 60)

    for c, h in enumerate(headers[:10]):
        write_safe(
            ws, 0, c, _enveloppe_output_header(h), fmts["header_calc" if c == 3 else "header"]
        )

    for r_idx, rowvals in enumerate(rows, start=1):
        for c in range(10):
            value = rowvals[c] if c < len(rowvals) else None
            write_safe(ws, r_idx, c, _cell(value), fmts["data"])

    n_data = len(rows)
    first_data = 2
    last_data = max(first_data, n_data + 1)
    formula_end_with_blank = last_data + 1
    summary_row = n_data + 2  # Tarare : 8 lignes → ligne Excel 11.

    d_total = _sum_table_col(rows, 3)
    e_total = _sum_table_col(rows, 4)
    f_total = _sum_table_col(rows, 5)
    men_total = _first_number(src.superficie_menuiseries if src else None, f_total)
    shab = _first_number(src.shab if src else None)
    ratio = _first_number(src.ratio_fac_shab if src else None)
    if ratio is None and shab:
        ratio = d_total / shab if d_total is not None else None
    ecart = (e_total / d_total - 1) if d_total else None

    write_safe(ws, summary_row, 2, "Superficie des façades : ", fmts["summary_label_top"])
    ws.write_formula(
        summary_row,
        3,
        f"=SUM(D{first_data}:D{formula_end_with_blank})",
        fmts["summary_value_top"],
        _formula_cached(d_total),
    )
    ws.write_formula(
        summary_row,
        4,
        f"=SUM(E{first_data}:E{formula_end_with_blank})",
        fmts["summary_value"],
        _formula_cached(e_total),
    )
    ws.write_formula(
        summary_row,
        5,
        f"=SUM(F{first_data}:F{last_data})",
        fmts["summary_value"],
        _formula_cached(f_total),
    )
    write_safe(
        ws,
        summary_row,
        6,
        "non pertinent : inclus portes et fenêtres",
        fmts["note"],
    )

    write_safe(ws, summary_row + 1, 3, "écart : ", fmts["label"])
    ws.write_formula(
        summary_row + 1,
        4,
        f"=E{summary_row + 1}/D{summary_row + 1}-1",
        fmts["percent_fill"],
        _formula_cached(ecart),
    )
    write_safe(ws, summary_row + 2, 6, "écart calcul IFC OpenShell à contrôler", fmts["note"])

    write_safe(ws, summary_row + 3, 2, "Superficie des menuiseries : ", fmts["summary_label"])
    write_safe(
        ws,
        summary_row + 3,
        3,
        NOT_AVAILABLE if men_total is None else men_total,
        fmts["summary_value_top"],
    )
    write_safe(ws, summary_row + 3, 6, "(murs complexes : murs non découpés ", fmts["note"])
    write_safe(ws, summary_row + 4, 6, "sur 100% de la périphérie )", fmts["note"])

    write_safe(ws, summary_row + 5, 2, "SHAB : ", fmts["summary_label"])
    write_safe(
        ws, summary_row + 5, 3, NOT_AVAILABLE if shab is None else shab, fmts["summary_value_top"]
    )
    write_safe(ws, summary_row + 6, 2, "ratio FAC/SHAB : ", fmts["summary_label_plain"])
    ws.write_formula(
        summary_row + 6,
        3,
        f"=D{summary_row + 1}/D{summary_row + 6}",
        fmts["ratio"],
        _formula_cached(ratio),
    )
    write_safe(ws, summary_row + 7, 2, "Seuil 3F 2026 : ", fmts["summary_label_plain"])
    write_safe(
        ws,
        summary_row + 7,
        3,
        NOT_AVAILABLE if not src or src.seuil_3f is None else src.seuil_3f,
        fmts["threshold"],
    )
    wb.close()
    return path


def _enveloppe_moa_formats(wb) -> dict[str, xlsxwriter.format.Format]:
    base = {"font_name": "Aptos Narrow", "font_size": 11}
    return {
        "header": wb.add_format(
            {**base, "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True}
        ),
        "header_calc": wb.add_format(
            {
                **base,
                "bold": True,
                "border": 1,
                "align": "center",
                "valign": "vcenter",
                "text_wrap": True,
                "bg_color": "#D9EAD3",
            }
        ),
        "data": wb.add_format({**base, "left": 1, "right": 1, "top": 1, "bottom": 7}),
        "summary_label_top": wb.add_format(
            {**base, "bold": True, "align": "right", "top": 1, "bottom": 1}
        ),
        "summary_label": wb.add_format(
            {**base, "bold": True, "align": "right", "right": 1, "top": 1, "bottom": 1}
        ),
        "summary_label_plain": wb.add_format({**base, "bold": True, "align": "right"}),
        "summary_value_top": wb.add_format(
            {**base, "bold": True, "border": 1, "bg_color": "#D9EAD3", "num_format": "#,##0.00"}
        ),
        "summary_value": wb.add_format({**base, "border": 1, "num_format": "#,##0.00"}),
        "label": wb.add_format({**base}),
        "percent_fill": wb.add_format(
            {**base, "border": 1, "bg_color": "#D9EAD3", "num_format": "0.00%"}
        ),
        "note": wb.add_format({**base}),
        "ratio": wb.add_format(
            {**base, "bold": True, "font_color": "#C00000", "num_format": "#,##0.00"}
        ),
        "threshold": wb.add_format({**base, "num_format": "0.00"}),
    }


def _enveloppe_output_header(value) -> str:
    text = str(value or "")
    return (
        text.replace("Surface Solibri", "Surface IFC OpenShell")
        .replace("Solibri Surface des Fenêtres", "IFC OpenShell Surface des Fenêtres")
        .replace("Solibri Surface des Portes", "IFC OpenShell Surface des Portes")
    )


def _env_ecart(src) -> float | None:
    """Écart Σ « Surface IFC OpenShell » (col E) − Σ « Archicad BQ NetSideArea »
    (col D) de la table enveloppe. Nul quand une source unique alimente D et E."""
    if not src or not getattr(src, "table", None) or not src.table.rows:
        return None
    d = sum(r[3] for r in src.table.rows if len(r) > 3 and isinstance(r[3], (int, float)))
    e = sum(r[4] for r in src.table.rows if len(r) > 4 and isinstance(r[4], (int, float)))
    return round(e - d, 2)
