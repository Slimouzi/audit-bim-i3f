#!/usr/bin/env python3
"""Inventaire des chaînes porteuses de vocabulaire client dans le reporting.

Sert à cadrer PR C (extraction du narratif vers ``bim-reporting``). Aucune
modification de code : lecture seule, sortie sur stdout.

**Le contrôle qui compte est la distinction commentaire / docstring / chaîne
vive.** Un grep brut mélange les trois et surestime massivement le travail : sur
`word_report.py`, plus d'un tiers des occurrences sont des docstrings, qui ne
coûtent rien à traiter. À l'inverse, une chaîne vive est du texte imprimé dans
le livrable — la toucher change ce que le maître d'ouvrage reçoit.

On classe donc chaque occurrence par :

- **contexte** : ``docstring`` / ``comment`` / ``live`` (chaîne évaluée) ;
- **nature** : à quel axe de vocabulaire elle appartient ;
- **destination** : où elle doit vivre après extraction.

Usage : ``python scripts/inventory_client_strings.py [--format table|csv]``
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import tokenize
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTING = ROOT / "audit_bim" / "reporting"

#: Fichiers à traiter en PR C.
TARGETS = ["context.py", "word_report.py", "xlsx_annex.py"]

#: Pack AVP — inventorié pour COMPARAISON seulement (pack client légitime).
COMPARISON = sorted(
    [p.relative_to(REPORTING).as_posix() for p in REPORTING.glob("avp_*.py")]
    + [p.relative_to(REPORTING).as_posix() for p in REPORTING.glob("avp/*.py")]
)

#: Vocabulaire client recherché. L'ordre compte : la première nature qui
#: matche gagne, du plus spécifique au plus général.
NATURES: list[tuple[str, re.Pattern]] = [
    (
        "classification_system",
        re.compile(r"\btable(?:\s+interne)?\s+3F\b|\bUniFormat\b|\bOmniclass\b|\bCCI\b", re.I),
    ),
    ("owner", re.compile(r"\bcodification\s+I3F\b|\bI3F\b|\b3F\b", re.I)),
    ("reference_framework", re.compile(r"\bCCBIM\b|\bCCH\b|chap\.\s*\d|Charges\s+BIM", re.I)),
    ("moa_role", re.compile(r"\bMOA\b|\bMOE\b")),
    ("project_sample", re.compile(r"\bTarare\b|\bDieppe\b|\b0546L\b", re.I)),
]

#: Destination proposée, par (nature, contexte). Le contexte prime : une
#: docstring ne part nulle part, quelle que soit sa nature.
DESTINATIONS = {
    "classification_system": "ClassificationNarrativeSpec",
    "owner": "profil I3F (owner_name)",
    "reference_framework": "ReportNarrativeSpec",
    "moa_role": "ReportNarrativeSpec",
    "project_sample": "rester dans I3F",
}


def _docstring_lines(tree: ast.AST) -> set[int]:
    """Lignes occupées par une docstring (module, classe, fonction)."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            out.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return out


def _comment_lines(src: str) -> set[int]:
    out: set[int] = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            out.add(tok.start[0])
    return out


def _internal_lines(src: str) -> set[int]:
    """Chaînes VIVES qui n'atteignent pourtant jamais le livrable.

    Deux cas, tous deux trompeurs pour un grep comme pour un AST naïf :

    - ``Field(description=…)`` — documentation de schéma Pydantic, lue par un
      développeur, jamais imprimée dans un rapport ;
    - listes de mots-clés de détection (``["uniformat", "omniclass", …]``) —
      elles servent à RECONNAÎTRE un objectif BIM dans un texte projet, pas à
      l'écrire. Les paramétrer par profil serait un contresens : un profil tiers
      doit lui aussi savoir reconnaître « uniformat » dans un descriptif.

    Les compter comme du narratif à extraire surestimerait le travail et, pire,
    orienterait vers la mauvaise destination.
    """
    out: set[int] = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        # Field(..., description="…")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Field"
        ):
            for kw in node.keywords:
                if kw.arg == "description":
                    out.update(range(kw.value.lineno, (kw.value.end_lineno or kw.value.lineno) + 1))
        # {"…": ["mot", "clé", …]} — dictionnaire de détection
        if isinstance(node, ast.Dict):
            for value in node.values:
                if isinstance(value, ast.List) and all(
                    isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts
                ):
                    out.update(range(value.lineno, (value.end_lineno or value.lineno) + 1))
    return out


def _excel_structure_lines(src: str, filename: str) -> set[int]:
    """Lignes qui définissent la STRUCTURE du classeur (onglets, colonnes).

    Les toucher ne change pas une phrase : ça change le nom d'une feuille ou
    d'une colonne, donc le gabarit que la MOA ouvre et compare d'un audit à
    l'autre. Ça ne se recette pas comme du texte.
    """
    if filename != "xlsx_annex.py":
        return set()
    out: set[int] = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_worksheet"
        ):
            out.add(node.lineno)
    # Table des colonnes : COLUMNS = [("Référence CCH", 14), …]
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "COLUMNS" for t in node.targets
        ):
            out.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return out


def scan(path: Path) -> list[dict]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    docs = _docstring_lines(tree)
    comments = _comment_lines(src)
    internal = _internal_lines(src)
    structure = _excel_structure_lines(src, path.name)

    rows: list[dict] = []
    for lineno, line in enumerate(src.splitlines(), 1):
        for nature, pattern in NATURES:
            m = pattern.search(line)
            if not m:
                continue
            if lineno in docs:
                context, dest = "docstring", "ignorer (docstring)"
            elif lineno in comments:
                context, dest = "comment", "ignorer (commentaire)"
            elif lineno in internal:
                context, dest = "internal", "rester dans I3F (non imprimé)"
            elif lineno in structure:
                context, dest = "printed", "ReportStructureSpec"
            else:
                context, dest = "printed", DESTINATIONS[nature]
            rows.append(
                {
                    "file": path.name,
                    "line": lineno,
                    "nature": nature,
                    "context": context,
                    "destination": dest,
                    "match": m.group(0),
                    "excerpt": line.strip()[:92],
                }
            )
            break  # une nature par ligne : la plus spécifique
    return rows


def _print_table(rows: list[dict]) -> None:
    print(f"{'fichier':16} {'ligne':>5}  {'nature':22} {'ctx':9} {'destination':30} extrait")
    print("─" * 150)
    for r in rows:
        print(
            f"{r['file']:16} {r['line']:>5}  {r['nature']:22} {r['context']:9} "
            f"{r['destination']:30} {r['excerpt']}"
        )


def _counts(rows: list[dict], label: str) -> None:
    live = [r for r in rows if r["context"] == "printed"]
    struct = [r for r in live if r["destination"] == "ReportStructureSpec"]
    print(f"\n=== {label} : {len(rows)} occurrence(s), dont {len(live)} IMPRIMÉES ===")
    print("\npar fichier (total / imprimées) :")
    per_file = Counter(r["file"] for r in rows)
    per_file_live = Counter(r["file"] for r in live)
    for f, n in sorted(per_file.items()):
        print(f"  {f:20} {n:>3} / {per_file_live.get(f, 0):>3}")
    print("\npar nature (imprimées seulement) :")
    for n, c in Counter(r["nature"] for r in live).most_common():
        print(f"  {n:24} {c:>3}")
    print("\npar destination (imprimées seulement) :")
    for d, c in Counter(r["destination"] for r in live).most_common():
        print(f"  {d:32} {c:>3}")
    print(f"\nparamétrable SANS changer le livrable : {len(live) - len(struct)}")
    print(f"changerait la STRUCTURE du classeur    : {len(struct)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--format", choices=("table", "csv"), default="table")
    ap.add_argument("--comparison", action="store_true", help="inclure le pack AVP")
    args = ap.parse_args()

    rows = [r for name in TARGETS for r in scan(REPORTING / name)]
    if args.format == "csv":
        print("file,line,nature,context,destination,match")
        for r in rows:
            print(
                f'{r["file"]},{r["line"]},{r["nature"]},{r["context"]},{r["destination"]},"{r["match"]}"'
            )
        return 0

    _print_table(rows)
    _counts(rows, "PÉRIMÈTRE PR C")

    if args.comparison:
        comp = [r for name in COMPARISON for r in scan(REPORTING / name)]
        _counts(comp, "PACK AVP (comparaison — hors périmètre)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
