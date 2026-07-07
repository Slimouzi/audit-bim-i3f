"""Verrou d'architecture — règles de couches figées par analyse statique (ast).

Casse-cycle de PR1 (docs/instruct-refactor-pr-series.md §PR1). Une couche basse
n'importe JAMAIS une couche haute, même paresseusement. Ce test parse les imports
de **chaque** module de ``audit_bim/`` et échoue si une arête interdite réapparaît —
c'est lui qui empêche la re-dérive (les imports intra-fonction « pour éviter le
cycle » ne trompent pas l'ast).

Règles (liste blanche explicite, extensible) :
 - ``domain`` n'importe **rien** d'``audit_bim`` (couche la plus basse) ;
 - ``audit`` n'importe ni ``reporting`` ni ``mcp`` ;
 - ``requirements`` n'importe pas ``audit`` ;
 - ``doe`` n'importe pas ``enrichment``.
"""

from __future__ import annotations

import ast
import pathlib

import audit_bim

_PKG_ROOT = pathlib.Path(audit_bim.__file__).resolve().parent
_REPO_ROOT = _PKG_ROOT.parent

# layer interdit d'import → ensemble de couches cibles proscrites ("*" = toute
# couche audit_bim). Étendre ici (avec justification) si une nouvelle règle de
# couche doit être gelée.
_FORBIDDEN: dict[str, set[str]] = {
    "domain": {"*"},
    "audit": {"reporting", "mcp"},
    "requirements": {"audit"},
    "doe": {"enrichment"},
}


def _module_name(path: pathlib.Path) -> tuple[str, list[str]]:
    """(nom de module pointé, parts du package conteneur) pour la résolution des
    imports relatifs."""
    if path.name == "__init__.py":
        parts = list(path.parent.relative_to(_REPO_ROOT).parts)
        return ".".join(parts), parts  # un package : son propre package = lui-même
    parts = list(path.with_suffix("").relative_to(_REPO_ROOT).parts)
    return ".".join(parts), parts[:-1]  # un module : package = parent


def _layer(dotted: str) -> str | None:
    p = dotted.split(".")
    return p[1] if len(p) >= 2 and p[0] == "audit_bim" else None


def _imported_modules(path: pathlib.Path, pkg_parts: list[str]) -> set[str]:
    """Cibles d'import absolues (``audit_bim.…``) d'un module, imports relatifs
    résolus, y compris ceux au niveau fonction."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    out.add(node.module)
            else:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                out.add(".".join(base + ([node.module] if node.module else [])))
    return out


def _iter_modules():
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_layer_rules_hold_across_audit_bim():
    violations: list[str] = []
    for path in _iter_modules():
        dotted, pkg_parts = _module_name(path)
        src_layer = _layer(dotted)
        if src_layer not in _FORBIDDEN:
            continue
        banned = _FORBIDDEN[src_layer]
        for target in _imported_modules(path, pkg_parts):
            tgt_layer = _layer(target)
            if tgt_layer is None or tgt_layer == src_layer:
                continue
            if "*" in banned or tgt_layer in banned:
                violations.append(f"{dotted}  →  {target}  (couche {src_layer} ✗ {tgt_layer})")
    assert not violations, "arêtes de couche interdites :\n  " + "\n  ".join(violations)


# Couches cassées par PR1 (le cycle ``config ↔ session`` de ``mcp`` est un cycle
# distinct, hors périmètre PR1 — traité avec la restructuration mcp de PR2).
_PR1_LAYERS = {"domain", "audit", "reporting", "requirements", "doe", "enrichment"}


def test_no_cycle_motivated_intrafunction_imports_remain():
    """Aucun import intra-fonction motivé par « éviter le cycle » ne subsiste dans
    les couches cassées par PR1 (marqueur textuel des cycles résolus)."""
    offenders = [
        str(p.relative_to(_REPO_ROOT))
        for p in _iter_modules()
        if _layer(_module_name(p)[0]) in _PR1_LAYERS
        and "éviter le cycle" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"commentaires 'éviter le cycle' résiduels (couches PR1) : {offenders}"
