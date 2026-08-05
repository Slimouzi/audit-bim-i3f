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

import pytest

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
                base = node.module or ""
            else:
                base_parts = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                base = ".".join(base_parts + ([node.module] if node.module else []))
            if base:
                out.add(base)
            # Chaque **nom** importé peut être un SOUS-MODULE, pas seulement un
            # symbole : ``from audit_bim import reporting`` (base = ``audit_bim``,
            # nom = ``reporting``) est une arête ``audit_bim.reporting`` qui, sans
            # cette résolution, serait invisible (base seule = ``audit_bim``, couche
            # None) → contournement du verrou. On verrouille donc le **principe**,
            # pas seulement 4 arêtes nommées.
            for alias in node.names:
                out.add(f"{base}.{alias.name}" if base else alias.name)
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


def test_package_level_reexport_edge_is_visible(tmp_path):
    """Méta-test du verrou (E-arch) : une re-importation au niveau **package**
    (``from audit_bim import reporting``) doit être vue comme l'arête
    ``audit_bim.reporting`` — sinon un module bas contournerait la règle."""
    fake = tmp_path / "fake_domain_module.py"
    fake.write_text(
        "from audit_bim import reporting\n"
        "from audit_bim.mcp import server\n"
        "from __future__ import annotations\n",
        encoding="utf-8",
    )
    targets = _imported_modules(fake, ["audit_bim", "domain"])
    layers = {_layer(t) for t in targets}
    # Les couches hautes réexportées sont désormais visibles (pas seulement
    # ``audit_bim`` = couche None).
    assert "reporting" in layers
    assert "mcp" in layers


def test_forbidden_covers_the_four_frozen_edges():
    # Garde-fou : les 4 arêtes gelées restent déclarées (régression si supprimées).
    assert _FORBIDDEN["domain"] == {"*"}
    assert "reporting" in _FORBIDDEN["audit"] and "mcp" in _FORBIDDEN["audit"]
    assert "audit" in _FORBIDDEN["requirements"]
    assert "enrichment" in _FORBIDDEN["doe"]


# ── La façade audit_bim.query ne doit pas réapparaître ────────────────


def _query_offenders(source: str, package: str) -> list[str]:
    """Imports interdits dans ``source`` : façade locale, ou privé de ``bim_query``.

    Fonction unique, utilisée par le contrôle **et** par sa preuve de
    non-vacuité. Une version antérieure réimplémentait la détection dans le test
    de non-vacuité : elle prouvait que la copie fonctionnait, pas le contrôle.
    """
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                parts = package.split(".")
                base = parts[: len(parts) - node.level + 1]
                module = ".".join([*base, module] if module else base)
            if module.startswith("audit_bim.query"):
                offenders.append(f"{node.lineno} -> {module} (façade locale)")
            elif module.startswith("bim_query"):
                offenders += [
                    f"{node.lineno} -> {module}.{a.name} (privé)"
                    for a in node.names
                    if a.name.startswith("_")
                ]
        elif isinstance(node, ast.Import):
            offenders += [
                f"{node.lineno} -> {a.name} (façade locale)"
                for a in node.names
                if a.name.startswith("audit_bim.query")
            ]
    return offenders


def test_no_local_query_facade_is_reintroduced():
    """``audit-bim-i3f`` consomme ``bim-query`` par son API publique, sans couche locale.

    La façade ``audit_bim.query`` a été supprimée une fois le paquet stabilisé.
    Une couche locale « pour dépanner » la reconstituerait sans que rien ne
    l'annonce : elle rendrait de nouveau invisible ce que le dépôt emprunte au
    paquet, et masquerait au passage un éventuel retour à un nom privé.
    """
    repo = pathlib.Path(__file__).resolve().parents[2]
    assert not (repo / "audit_bim" / "query").exists(), "la façade locale est de retour"

    offenders: list[str] = []
    for path in sorted((repo / "audit_bim").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        package = ".".join(path.relative_to(repo).parts[:-1])
        offenders += [
            f"{path.relative_to(repo)}:{hit}"
            for hit in _query_offenders(path.read_text(encoding="utf-8"), package)
        ]
    assert not offenders, offenders


@pytest.mark.parametrize(
    "sample",
    [
        "from audit_bim.query.filtering import object_matches\n",
        "import audit_bim.query.views\n",
        "from ..query.views import iter_bim_objects\n",
        "from bim_query.views import _SPATIAL_CLASSES\n",
    ],
    ids=["import-absolu", "import-module", "import-relatif", "nom-privé"],
)
def test_the_query_facade_guard_is_not_vacuous(sample):
    """Le contrôle doit reconnaître les quatre formes qu'il interdit.

    L'import relatif compte autant que l'absolu : ``from ..query import`` est
    précisément la forme qu'un module interne emploierait.
    """
    assert _query_offenders(sample, "audit_bim.mcp"), sample


def test_the_public_api_of_bim_query_is_not_flagged():
    """Les imports légitimes ne doivent pas déclencher le contrôle."""
    sample = (
        "from bim_query.filtering import apply_object_filter\n"
        "from bim_query.views import SPATIAL_CLASSES, iter_bim_objects\n"
    )
    assert not _query_offenders(sample, "audit_bim.mcp")
