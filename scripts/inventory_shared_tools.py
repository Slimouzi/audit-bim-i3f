#!/usr/bin/env python
"""Inventaire des dépendances réelles de chaque outil MCP du profil I3F.

**Mesure, pas estimation.** Une première approche classait les outils par
présence de mots — « CCH », « AVP », « phase ». Elle produisait un signal utile
et deux erreurs de sens contraire : ``generate_xlsx_annex`` ne porte aucun
marqueur mais tire sa structure du profil, et ``set_active_model``, l'outil le
plus « socle » qui soit, mentionne AVP et phase dans sa seule docstring. Un mot
dans un texte ne dit rien de ce dont un outil dépend.

Ce script lit donc ce que chaque fonction **utilise** : les symboles importés
qu'elle référence effectivement (imports de module et imports différés dans le
corps), et les champs de ``_State`` auxquels elle accède.

Trois catégories, dans l'ordre de coût croissant :

``extractible``
    Ne touche que des briques neutres et des champs de session neutres. Le
    socle peut l'accueillir tel quel.
``parametrable``
    Neutre une fois son narratif ou sa structure lus dans le profil — le
    mécanisme existe déjà (``ReportNarrativeSpec``, ``ReportStructureSpec``).
``i3f``
    Dépend du référentiel : catalogue d'exigences, règles d'audit CCH, pack AVP.
    Extraire ces outils reviendrait à extraire le référentiel avec.
``inconnu``
    Lit un champ de ``_State`` qu'aucune des trois listes ci-dessus ne connaît.
    **Échec fermé délibéré** : un champ ajouté demain peut porter du contexte
    client, et le présumer neutre ferait entrer le référentiel d'un AMO dans le
    socle sans qu'aucun compteur ne bouge. Le script sort alors en erreur.

Usage::

    python scripts/inventory_shared_tools.py            # tableau lisible
    python scripts/inventory_shared_tools.py --json     # données brutes
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
I3F_DIR = REPO / "audit_bim" / "profiles" / "i3f"
BIM_IN_MOTION_DIR = REPO / "audit_bim" / "profiles" / "bim_in_motion"
SHARED_DIR = REPO / "audit_bim" / "tools_shared"

# ── Classement des origines ──────────────────────────────────────────────────

#: Modules du dépôt qui portent le référentiel client. Un outil qui en dépend
#: ne peut pas rejoindre un socle sans emporter le CCH avec lui.
I3F_BOUND_PREFIXES = (
    "audit_bim.requirements",
    "audit_bim.audit.rules",
    "audit_bim.reporting.avp",
)

#: Modules dont la part client passe déjà par le profil (specs narratives et
#: structurelles, lots C1/C2). Le mécanisme de paramétrage existe.
PARAMETERISED_PREFIXES = (
    "audit_bim.reporting",
    "audit_bim.profiles",
)

#: Champs de session porteurs du référentiel I3F.
I3F_STATE_FIELDS = {
    "catalog",
    "ensure_catalog",
    "cch_pdf",
    "data_spec_xlsx",
    "naming_spec_xlsx",
    "phase",
}

#: Champs **produits par un amont**. Distinction essentielle : le code qui les
#: lit est générique, son type vient de briques déjà externalisées — mais il n'y
#: a rien à lire tant qu'un audit n'a pas tourné, et le seul moteur d'audit
#: câblé aujourd'hui applique les règles CCH. Ces outils sont donc extractibles
#: comme code et inutilisables seuls. Les classer « extractibles » sans le dire
#: promettrait un socle qui ne rend rien à un second AMO.
UPSTREAM_STATE_FIELDS = {
    "result",
    "ensure_result",
    "suggestion_store",
}

#: Champs de session neutres : une cible, une lecture, un fichier rapatrié.
NEUTRAL_STATE_FIELDS = {
    "client",
    "cloud_id",
    "project_id",
    "model_id",
    "snapshot",
    "ifc_path",
    "classification_system",
    "doe_available",
    "ensure_client",
    "ensure_snapshot",
    "lock",
}


def _tool_functions(path: Path) -> list[ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(getattr(getattr(d, "func", d), "attr", None) == "tool" for d in node.decorator_list)
    ]


def _module_import_map(tree: ast.Module, path: Path) -> dict[str, str]:
    """``nom local -> module d'origine``, imports relatifs résolus."""
    package = ".".join(path.relative_to(REPO).parts[:-1])
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mapping[(alias.asname or alias.name).split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                parts = package.split(".")
                base = parts[: len(parts) - node.level + 1]
                module = ".".join([*base, module] if module else base)
            for alias in node.names:
                mapping[alias.asname or alias.name] = f"{module}.{alias.name}"
    return mapping


def _referenced_names(func: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                names.add(base.id)
    return names


def _state_fields(func: ast.AST) -> set[str]:
    """Champs de session **lus**. Les écritures ne sont pas des dépendances.

    La distinction n'est pas cosmétique : ``set_active_model`` fait
    ``_State.result = None`` pour invalider l'audit de la cible précédente.
    Compter cette ligne en ferait un outil « qui a besoin d'un audit », soit
    l'inverse exact de ce qu'elle signifie — c'est l'outil par lequel on
    commence.
    """
    fields: set[str] = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Attribute)
            and getattr(node.value, "id", None) == "_State"
            and isinstance(node.ctx, ast.Load)
        ):
            fields.add(node.attr)
    return fields


def _origin_kind(origin: str) -> str:
    if origin.startswith(I3F_BOUND_PREFIXES):
        return "i3f"
    if origin.startswith(PARAMETERISED_PREFIXES):
        return "parametrable"
    return "neutre"


def _proven_neutral_modules() -> set[str]:
    """Modules consommés par du code que **deux profils** déclarent.

    C'est la seule liste de ce fichier qui ne soit pas un jugement : elle est
    lue sur disque, dans des profils qui tournent.

    Le socle compte au même titre que le profil tiers, et il le faut : depuis
    E7, ``bim_in_motion`` n'importe plus l'extraction directement, il passe par
    ``tools_shared``. Ne regarder que ses fichiers propres ferait *retomber* le
    nombre de modules prouvés au moment précis où la mutualisation a lieu — la
    preuve serait détruite par son propre aboutissement.
    """
    proven: set[str] = set()
    for path in sorted(BIM_IN_MOTION_DIR.rglob("*.py")) + sorted(SHARED_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for origin in _module_import_map(tree, path).values():
            if origin.startswith("audit_bim."):
                proven.add(origin.rsplit(".", 1)[0])
    return proven


def analyse() -> dict:
    proven = _proven_neutral_modules()
    tools: list[dict] = []

    # Le socle partagé est analysé avec le profil : E7 en a sorti cinq outils,
    # et les cesser de compter ferait « disparaître » un tiers du premier cercle
    # de l'inventaire au lieu de montrer qu'il a été extrait.
    sources = sorted(I3F_DIR.glob("tools_*.py")) + sorted(SHARED_DIR.glob("*.py"))
    for path in sources:
        if path.stem == "__init__":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_map = _module_import_map(tree, path)
        helpers = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        for func in _tool_functions(path):
            # Fermeture transitive sur les helpers du **même module**. Sans
            # elle, un outil qui délègue son travail à une fonction privée
            # important le catalogue d'exigences paraîtrait neutre : la
            # dépendance existe, elle est juste une ligne plus bas.
            visited: set[str] = set()
            frontier = [func]
            origins_set: set[str] = set()
            fields: set[str] = set()
            while frontier:
                current = frontier.pop()
                local_map = dict(module_map)
                local_map.update(
                    _module_import_map(ast.Module(body=current.body, type_ignores=[]), path)
                )
                used = _referenced_names(current)
                origins_set |= {local_map[n] for n in used if n in local_map}
                fields |= _state_fields(current)
                for name in used & set(helpers):
                    if name not in visited:
                        visited.add(name)
                        frontier.append(helpers[name])

            origins = sorted(origins_set)

            kinds = {_origin_kind(o) for o in origins}
            i3f_fields = sorted(fields & I3F_STATE_FIELDS)
            upstream_fields = sorted(fields & UPSTREAM_STATE_FIELDS)
            unclassified_fields = sorted(
                fields - I3F_STATE_FIELDS - UPSTREAM_STATE_FIELDS - NEUTRAL_STATE_FIELDS
            )

            if unclassified_fields:
                # Fail-closed : on ne devine pas la nature d'un champ inconnu.
                category = "inconnu"
            elif "i3f" in kinds or i3f_fields:
                category = "i3f"
            elif "parametrable" in kinds:
                category = "parametrable"
            else:
                category = "extractible"

            tools.append(
                {
                    "tool": func.name,
                    "module": path.stem,
                    "extracted": SHARED_DIR in path.parents,
                    "helpers_followed": sorted(visited),
                    "category": category,
                    "i3f_origins": sorted(o for o in origins if _origin_kind(o) == "i3f"),
                    "parameterised_origins": sorted(
                        o for o in origins if _origin_kind(o) == "parametrable"
                    ),
                    "i3f_state_fields": i3f_fields,
                    "upstream_state_fields": upstream_fields,
                    "requires_upstream": bool(upstream_fields),
                    "unclassified_state_fields": unclassified_fields,
                    "neutral_origins_proven": sorted(
                        o for o in origins if o.rsplit(".", 1)[0] in proven
                    ),
                    "neutral_origins_unproven": sorted(
                        o
                        for o in origins
                        if _origin_kind(o) == "neutre"
                        and o.startswith("audit_bim.")
                        and o.rsplit(".", 1)[0] not in proven
                    ),
                }
            )

    return {"proven_neutral_modules": sorted(proven), "tools": tools}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="données brutes")
    args = parser.parse_args()

    report = analyse()

    # Calculé AVANT le branchement de sortie. Placé après, le fail-closed ne
    # protégeait que le mode lisible : ``--json`` — le mode qu'un test ou un
    # script consomme, donc celui qui compte — imprimait et rendait 0. Un
    # garde-fou qui dépend du format d'affichage n'en est pas un.
    unclassified = sorted({f for e in report["tools"] for f in e["unclassified_state_fields"]})

    if args.json:
        # On imprime quand même : c'est ce qui permet de voir quel outil lit
        # quel champ. Mais le code de retour reste non nul.
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if unclassified else 0

    by_category: dict[str, list[dict]] = defaultdict(list)
    for entry in report["tools"]:
        by_category[entry["category"]].append(entry)

    print(f"{len(report['tools'])} outils analysés\n")
    for category in ("extractible", "parametrable", "i3f", "inconnu"):
        entries = by_category[category]
        print(f"── {category} : {len(entries)}")
        for entry in entries:
            cause = (
                entry["i3f_origins"] + entry["i3f_state_fields"] + entry["parameterised_origins"]
            )
            detail = f"  ← {', '.join(cause[:3])}" if cause else ""
            flag = "  [amont requis]" if entry["requires_upstream"] else ""
            flag = ("  [socle]" + flag) if entry["extracted"] else flag
            print(f"   {entry['tool']:38} {entry['module']:16}{flag}{detail}")
        print()

    if unclassified:
        print(
            "ERREUR — champs de session non classés : "
            f"{', '.join(unclassified)}.\nClasser chacun dans I3F_STATE_FIELDS, "
            "UPSTREAM_STATE_FIELDS ou NEUTRAL_STATE_FIELDS avant de citer cet "
            "inventaire : un champ inconnu n'est pas un champ neutre."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
