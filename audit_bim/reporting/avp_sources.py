"""Lecture des fichiers sources I3F du pack AVP (Tarare 0546L).

Lit les .xlsx transmis par I3F et les normalise en structures mémoire
(tables à plat + scalaires de synthèse), **sans rien inventer** : un
fichier, un onglet, une colonne ou une valeur absent reste ``None`` et
sera rendu « Information non disponible dans les documents fournis. » par
les builders.

Design :

- ``_read_table`` détecte la ligne d'en-tête via une **ancre** (nom de
  colonne connu), préserve l'**ordre** des colonnes I3F, lit les lignes
  jusqu'à la première ligne totalement vide, et **écarte** les lignes de
  synthèse/notes (``Nombre de types…``, ``SHAB :``, ``= appuis…``).
- ``_scan_value`` récupère un scalaire de synthèse en cherchant un
  libellé (sous-chaîne) et en prenant la 1re valeur numérique à droite.

Aucune écriture ; ``read_only``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl

# Jetons signalant une ligne de synthèse / note à écarter d'une table.
_SUMMARY_TOKENS = (
    "nombre de types",
    "superficie des",
    "shab :",
    "shab:",
    "ratio ",
    "seuil ",
    "écart :",
    "ecart :",
    "= appuis",
    "somme de",
)


@dataclass
class SheetTable:
    """Table à plat : en-têtes ordonnés + lignes alignées."""

    title: str
    headers: list[str]
    rows: list[list[Any]] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.rows)


@dataclass
class ControleMaquettesSource:
    header: dict[str, Any] = field(default_factory=dict)  # projet, esi, phase, dates, version
    grille: SheetTable | None = None
    legend: dict[int, str] = field(default_factory=dict)  # 0/1/2 -> libellé
    stats: dict[str, dict[str, Any]] = field(default_factory=dict)  # onglet -> stats conformité


@dataclass
class EnveloppeSource:
    table: SheetTable | None = None
    superficie_facades: float | None = None
    superficie_menuiseries: float | None = None
    shab: float | None = None
    ratio_fac_shab: float | None = None
    seuil_3f: float | None = None


@dataclass
class MenuiseriesSource:
    table: SheetTable | None = None
    nombre_types: int | None = None


@dataclass
class TabularSource:
    table: SheetTable | None = None


@dataclass
class AvpSources:
    controle: ControleMaquettesSource | None = None
    shab: TabularSource | None = None
    zones_espaces: TabularSource | None = None
    enveloppe: EnveloppeSource | None = None
    menuiseries: MenuiseriesSource | None = None


# ── Helpers de lecture ────────────────────────────────────────────────────


def _is_summary_row(vals: list[Any]) -> bool:
    for v in vals:
        if isinstance(v, str):
            lv = v.strip().lower()
            for tok in _SUMMARY_TOKENS:
                if tok and lv.startswith(tok):
                    return True
    return False


def _find_sheet(wb, *name_fragments: str):
    """Retourne le 1er onglet dont le titre contient un des fragments."""
    for ws in wb.worksheets:
        low = ws.title.lower()
        if any(frag.lower() in low for frag in name_fragments):
            return ws
    return None


def _read_table(ws, anchor: str, *, max_header_scan: int = 40) -> SheetTable | None:
    """Lit une table à plat en détectant l'en-tête via ``anchor``."""
    if ws is None:
        return None
    header_row = None
    for r in range(1, min(ws.max_row, max_header_scan) + 1):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and anchor.lower() in v.lower():
                header_row = r
                break
        if header_row:
            break
    if header_row is None:
        return None

    cols: list[tuple[int, str]] = []
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        if isinstance(v, str) and v.strip():
            cols.append((c, v.strip()))
    if not cols:
        return None
    idxs = [c for c, _ in cols]
    headers = [h for _, h in cols]

    rows: list[list[Any]] = []
    for r in range(header_row + 1, ws.max_row + 1):
        vals = [ws.cell(r, c).value for c in idxs]
        if all(v in (None, "") for v in vals):
            break
        if _is_summary_row(vals):
            continue
        rows.append(vals)
    return SheetTable(title=ws.title, headers=headers, rows=rows)


def _scan_value(ws, *label_fragments: str) -> float | int | None:
    """Cherche un libellé (sous-chaîne) et renvoie la 1re valeur numérique
    à droite sur la même ligne. ``None`` si introuvable."""
    if ws is None:
        return None
    for r in range(1, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and any(f.lower() in v.lower() for f in label_fragments):
                for c2 in range(c + 1, ws.max_column + 1):
                    v2 = ws.cell(r, c2).value
                    if isinstance(v2, (int, float)) and not isinstance(v2, bool):
                        return v2
    return None


def _open(path: str | Path):
    return openpyxl.load_workbook(str(path), read_only=False, data_only=True)


# ── Lecteurs par livrable ──────────────────────────────────────────────────


def read_controle(path: str | Path) -> ControleMaquettesSource:
    wb = _open(path)
    src = ControleMaquettesSource()
    ws = _find_sheet(wb, "grille")
    if ws is not None:
        # Bloc entête (label en col B, valeur col C).
        header: dict[str, Any] = {}
        for r in range(1, min(ws.max_row, 12) + 1):
            label = ws.cell(r, 2).value
            val = ws.cell(r, 3).value
            if isinstance(label, str) and label.strip() and val not in (None, ""):
                header[label.strip().lower()] = val
        src.header = header
        # Légende 0/1/2 (col E numérique, col F libellé).
        for r in range(1, min(ws.max_row, 15) + 1):
            code = ws.cell(r, 5).value
            lib = ws.cell(r, 6).value
            if isinstance(code, int) and isinstance(lib, str) and lib.strip():
                src.legend[code] = lib.strip()
        src.grille = _read_table(ws, "POINTS DE CONTROLE")
    # Onglets de stats conformité.
    for sheet_name in (
        "Zones Nommage",
        "Pièces Nommage",
        "ARC bsence de matériau",
        "Zones ObjectType",
    ):
        ws_s = _find_sheet(wb, sheet_name.lower()) or (
            wb[sheet_name] if sheet_name in wb.sheetnames else None
        )
        if ws_s is None:
            continue
        src.stats[sheet_name] = _read_stats(ws_s)
    wb.close()
    return src


def _read_stats(ws) -> dict[str, Any]:
    """Extrait les stats conformité d'un onglet (ligne « Nombre… »)."""
    out: dict[str, Any] = {}
    for r in range(1, min(ws.max_row, 12) + 1):
        label = ws.cell(r, 2).value
        if isinstance(label, str) and label.strip().lower().startswith("nombre"):
            out["label"] = label.strip()
            out["total"] = ws.cell(r, 3).value
            out["conforme"] = ws.cell(r, 4).value
            out["conforme_ratio"] = ws.cell(r, 5).value
            out["non_conforme"] = ws.cell(r, 6).value
            out["non_conforme_ratio"] = ws.cell(r, 7).value
            break
    return out


def read_shab(path: str | Path) -> TabularSource:
    wb = _open(path)
    table = _read_table(
        _find_sheet(wb, "export zones", "tdb 2022 01") or wb.worksheets[-1], "Composant"
    )
    wb.close()
    return TabularSource(table=table)


def read_zones_espaces(path: str | Path) -> TabularSource:
    wb = _open(path)
    table = _read_table(
        _find_sheet(wb, "export zones", "tdb 2022 01") or wb.worksheets[0], "Composant"
    )
    wb.close()
    return TabularSource(table=table)


def read_enveloppe(path: str | Path) -> EnveloppeSource:
    wb = _open(path)
    ws = wb.worksheets[0]
    src = EnveloppeSource(table=_read_table(ws, "Composant"))
    src.superficie_facades = _scan_value(ws, "superficie des façades")
    src.superficie_menuiseries = _scan_value(ws, "superficie des menuiseries")
    src.shab = _scan_value(ws, "shab")
    src.ratio_fac_shab = _scan_value(ws, "ratio fac/shab")
    src.seuil_3f = _scan_value(ws, "seuil 3f")
    wb.close()
    return src


def read_menuiseries(path: str | Path) -> MenuiseriesSource:
    wb = _open(path)
    ws = wb.worksheets[0]
    src = MenuiseriesSource(table=_read_table(ws, "Composant"))
    nb = _scan_value(ws, "nombre de types")
    src.nombre_types = int(nb) if isinstance(nb, (int, float)) else None
    wb.close()
    return src


@dataclass
class AvpSourcePaths:
    """Chemins des 5 .xlsx sources I3F (tous optionnels)."""

    controle: str | Path | None = None
    shab: str | Path | None = None
    zones_espaces: str | Path | None = None
    enveloppe: str | Path | None = None
    menuiseries: str | Path | None = None


def load_sources(paths: AvpSourcePaths) -> AvpSources:
    """Charge les sources disponibles ; chaque livrable absent reste ``None``."""
    out = AvpSources()
    if paths.controle:
        out.controle = read_controle(paths.controle)
    if paths.shab:
        out.shab = read_shab(paths.shab)
    if paths.zones_espaces:
        out.zones_espaces = read_zones_espaces(paths.zones_espaces)
    if paths.enveloppe:
        out.enveloppe = read_enveloppe(paths.enveloppe)
    if paths.menuiseries:
        out.menuiseries = read_menuiseries(paths.menuiseries)
    return out
