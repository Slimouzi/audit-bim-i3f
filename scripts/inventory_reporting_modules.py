#!/usr/bin/env python
"""Inventaire du module ``audit_bim/reporting`` — façade, socle, ou livrable I3F.

Contrairement à ``audit_bim/query``, qui était un passe-plat de 152 lignes,
``reporting`` est un module à part entière : ~8 200 lignes qui **produisent des
fichiers**. La question n'est donc pas « peut-on supprimer la façade », mais
« qu'est-ce qui, là-dedans, est déjà de la façade, et qu'est-ce qui est de
l'orchestration I3F qu'aucun socle ne doit absorber ».

Trois axes mesurés par module :

``delegation``
    Ce qu'il emprunte à ``bim-reporting`` — le socle déjà externalisé.
``attaches``
    Ce qui le lie au référentiel I3F : catalogue d'exigences, phase BIM, règles
    d'audit, pack AVP, profil.
``contrat``
    Ce qu'il **écrit** : un module qui produit un ``.docx`` ou un ``.xlsx`` porte
    un contrat de sortie, et toute recomposition doit prouver la parité du
    fichier — pas seulement celle du code.
``consommateurs``
    Qui l'importe. Un module peut être neutre par dépendances et n'exister que
    pour le pack AVP : son code ne connaît pas le référentiel, mais personne
    d'autre ne l'appelle. L'inventaire du socle partagé avait rencontré la même
    nuance sous une autre forme — du code générique suspendu à un amont I3F. La
    classer « neutre » sans le dire promettrait un socle qui ne sert personne.

Le troisième axe est le plus important ici, et c'est ce qui distingue ce lot du
précédent. Un livrable est relu par un humain, ouvert par des outils MOA, parfois
référencé par un TCD : un nom d'onglet ou un ordre de colonnes change de statut
dès qu'il est écrit sur disque.

Usage::

    python scripts/inventory_reporting_modules.py            # tableau
    python scripts/inventory_reporting_modules.py --json     # données brutes
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPORTING_DIR = REPO / "audit_bim" / "reporting"

#: Le socle de rendu déjà externalisé.
SOCLE_ROOTS = ("bim_reporting",)

#: Modules qui portent le référentiel client ou son pack de livrables.
I3F_ROOTS = (
    "audit_bim.requirements",
    "audit_bim.audit.rules",
    "audit_bim.profiles",
)

#: Vocabulaire client cherché dans les **textes servis ou écrits** : titres de
#: sections, en-têtes de colonnes, noms d'onglets, messages. Une docstring qui
#: explique la frontière ne compte pas — la distinction a déjà été tranchée sur
#: le profil BIM in Motion.
CLIENT_TERMS = ("i3f", "cch", "avp", "3f")

#: Signatures d'écriture de fichier. Un module qui en porte une a un contrat de
#: sortie : sa recomposition se recette en ouvrant le fichier produit.
WRITE_HINTS = (
    "Document(",
    "doc.save",
    "Workbook(",
    "xlsxwriter",
    "add_worksheet",
    "openpyxl",
    ".save(",
    "write_safe",
    "safe_export_path",
)


def _module_imports(tree: ast.Module, path: Path) -> list[str]:
    package = ".".join(path.relative_to(REPO).parts[:-1])
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                parts = package.split(".")
                base = parts[: len(parts) - node.level + 1]
                module = ".".join([*base, module] if module else base)
            found += [f"{module}.{a.name}" for a in node.names]
    return found


def _shipped_texts(tree: ast.Module) -> list[str]:
    """Chaînes littérales hors docstrings — celles qui finissent dans un fichier."""
    skip: set[int] = set()
    if tree.body and isinstance(tree.body[0], ast.Expr):
        skip.add(id(tree.body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and isinstance(node.body[0], ast.Expr) and ast.get_docstring(node):
                skip.add(id(node.body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
    ]


def _reverse_dependencies() -> dict[str, list[str]]:
    """``module de reporting -> modules d'audit_bim qui l'importent``.

    Mesuré sur tout le paquet, imports relatifs résolus. C'est ce qui distingue
    un module réutilisable d'un module qui n'a qu'un seul appelant, lequel se
    trouve être le pack de livrables d'un client.
    """
    consumers: dict[str, set[str]] = defaultdict(set)
    for path in sorted((REPO / "audit_bim").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        caller = ".".join(path.relative_to(REPO).with_suffix("").parts)
        for imported in _module_imports(tree, path):
            if not imported.startswith("audit_bim.reporting"):
                continue
            target = imported[len("audit_bim.reporting.") :]
            for candidate in (target, target.rsplit(".", 1)[0]):
                rel = candidate.replace(".", "/") + ".py"
                if (REPORTING_DIR / rel).exists() and caller != f"audit_bim.reporting.{candidate}":
                    consumers[rel].add(caller)
                    break
    return {k: sorted(v) for k, v in consumers.items()}


def analyse() -> dict:
    consumers = _reverse_dependencies()
    modules: list[dict] = []
    for path in sorted(REPORTING_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = _module_imports(tree, path)
        texts = _shipped_texts(tree)

        client_hits = sorted(
            {
                term
                for text in texts
                for term in CLIENT_TERMS
                if re.search(rf"\b{re.escape(term)}\b", text, re.I)
            }
        )
        writes = sorted({hint for hint in WRITE_HINTS if hint in source})

        delegation = sorted({i for i in imports if i.startswith(SOCLE_ROOTS)})
        attaches = sorted({i for i in imports if i.startswith(I3F_ROOTS)})

        rel = str(path.relative_to(REPORTING_DIR))
        callers = consumers.get(rel, [])
        avp_only = bool(callers) and all(
            "avp" in c.rsplit(".", 1)[-1] or ".avp" in c for c in callers
        )

        if delegation and not attaches and len(source.splitlines()) < 120:
            kind = "façade"
        elif attaches or client_hits:
            kind = "orchestration_i3f"
        elif avp_only:
            kind = "neutre_lié_avp"
        else:
            kind = "neutre"

        modules.append(
            {
                "module": rel,
                "consumers": callers,
                "avp_only": avp_only,
                "lines": len(source.splitlines()),
                "kind": kind,
                "delegation": delegation,
                "attaches": attaches,
                "client_terms": client_hits,
                "writes_files": writes,
            }
        )
    return {"modules": modules}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = analyse()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for entry in report["modules"]:
        by_kind[entry["kind"]].append(entry)

    total = sum(m["lines"] for m in report["modules"])
    print(f"{len(report['modules'])} modules, {total} lignes\n")
    for kind in ("façade", "neutre", "neutre_lié_avp", "orchestration_i3f"):
        entries = by_kind[kind]
        lines = sum(e["lines"] for e in entries)
        print(f"── {kind} : {len(entries)} modules, {lines} lignes")
        for e in sorted(entries, key=lambda x: -x["lines"]):
            flags = []
            if e["writes_files"]:
                flags.append("écrit")
            if e["client_terms"]:
                flags.append("+".join(e["client_terms"]))
            if e["delegation"]:
                flags.append(f"socle×{len(e['delegation'])}")
            if e["consumers"]:
                flags.append(f"{len(e['consumers'])} appelant(s)")
            print(f"   {e['module']:28} {e['lines']:>5}  {' | '.join(flags)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
