"""``audit_bim.mcp.server`` n'expose aucun outil — et ne doit pas en réexposer.

Les ré-exports ``server.<tool>`` ont été retirés. Ce fichier remplace celui qui
les exerçait : il ne teste plus une compat, il **empêche son retour**.

La distinction compte. Un ré-export est facile à réintroduire — une ligne
d'import « pour dépanner », et le module redevient un point d'entrée parallèle
au registre MCP, avec les effets de bord d'enregistrement que trois lots ont
servi à éliminer. Le contrôle est donc statique et couvre les trois formes sous
lesquelles la dépendance peut réapparaître, y compris celle qui ne laisse aucun
``server.`` au point d'appel.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from audit_bim.mcp import server

REPO = Path(server.__file__).resolve().parents[2]
GOLDEN_DIR = REPO / "tests" / "unit" / "golden"
SERVER_MODULE = "audit_bim.mcp.server"

#: Ce que le module a le droit d'exposer. Trois noms, aucun outil de profil.
ALLOWED = {"main", "mcp", "list_mcp_profiles"}


def _tool_names() -> set[str]:
    """Tous les noms d'outils du dépôt : goldens des profils + aliases LEGACY.

    Les aliases sont exclus des goldens (opt-in par variable d'environnement) ;
    les oublier laisserait justement la moitié la moins visible de la compat
    revenir sans bruit.
    """
    names: set[str] = set()
    for path in GOLDEN_DIR.glob("mcp_surface*.json"):
        names |= set(json.loads(path.read_text(encoding="utf-8"))["tools"])

    aliases = REPO / "audit_bim" / "profiles" / "i3f" / "aliases.py"
    tree = ast.parse(aliases.read_text(encoding="utf-8"))
    names |= {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(getattr(getattr(d, "func", d), "attr", None) == "tool" for d in node.decorator_list)
    }
    return names - ALLOWED


# ── 1. Le module n'expose plus que trois noms ─────────────────────────


def test_the_server_module_exposes_only_three_names():
    source = Path(server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    exported = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module != "__future__"
        for alias in node.names
    }
    assert exported == ALLOWED, exported
    assert getattr(server, "__all__", None) == ["main", "mcp", "list_mcp_profiles"]


def test_no_lazy_reexport_mechanism_remains():
    """Plus de ``__getattr__`` : un nom inconnu doit échouer tout de suite."""
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "__getattr__" not in source
    assert "_REEXPORTS" not in source
    assert "_LEGACY_ALIAS_REEXPORTS" not in source

    absent = "full_audit"  # variable : ruff réécrit un getattr littéral (B009)
    with pytest.raises(AttributeError):
        getattr(server, absent)


def test_the_legacy_flag_is_the_only_remaining_compat_for_aliases():
    """Les aliases restent joignables **par le registre MCP**, pas par Python.

    Deux mécanismes pour une même compat, c'est un de trop : à la suppression,
    c'est toujours le moins visible qui survit. Le drapeau reste seul maître.
    """
    app_source = (Path(server.__file__).parent / "app.py").read_text(encoding="utf-8")
    assert "AUDIT_BIM_ENABLE_LEGACY_ALIASES" in app_source
    assert "legacy_alias_module" in app_source


# ── 2. Aucun code ne peut retrouver un outil par ce module ────────────


def _server_aliases(tree: ast.Module, path: Path) -> set[str]:
    """Expressions qui, dans ce fichier, désignent le module ``server``.

    Le nom d'un alias est un choix local (``as srv``, ``as s``…) : il faut le
    lire dans les imports, pas le deviner. Une version antérieure de ce contrôle
    énumérait trois noms plausibles et affirmait « zéro appel » alors qu'elle
    vérifiait « zéro appel sous trois noms devinés ».
    """
    found = {SERVER_MODULE}
    try:
        package = ".".join(path.relative_to(REPO).parts[:-1])
    except ValueError:
        package = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == SERVER_MODULE:
                    found.add(alias.asname or alias.name)
                elif alias.name == "audit_bim.mcp" and alias.asname:
                    found.add(f"{alias.asname}.server")
        elif isinstance(node, ast.ImportFrom):
            module = _resolved_module(node, package)
            for alias in node.names:
                if module == "audit_bim.mcp" and alias.name == "server":
                    found.add(alias.asname or "server")
                elif module == "audit_bim" and alias.name == "mcp":
                    found.add(f"{alias.asname or 'mcp'}.server")
    return found


def _resolved_module(node: ast.ImportFrom, package: str) -> str:
    module = node.module or ""
    if node.level:
        parts = package.split(".")
        base = parts[: len(parts) - node.level + 1]
        module = ".".join([*base, module] if module else base)
    return module


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _tool_accesses(source: str, path: Path, names: set[str]) -> list[str]:
    """Toute reprise d'un outil via ``server``, sous ses trois formes."""
    tree = ast.parse(source)
    try:
        package = ".".join(path.relative_to(REPO).parts[:-1])
    except ValueError:
        package = ""
    aliases = _server_aliases(tree, path)
    hits: list[str] = []

    for node in ast.walk(tree):
        # 1. `from audit_bim.mcp.server import full_audit` — après quoi plus
        #    aucun `server.` n'apparaît au point d'appel.
        if isinstance(node, ast.ImportFrom) and _resolved_module(node, package) == SERVER_MODULE:
            hits += [
                f"{node.lineno} -> from {SERVER_MODULE} import {a.name}"
                for a in node.names
                if a.name in names
            ]
        # 2. `srv.full_audit`, quel que soit l'alias.
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted and dotted.rsplit(".", 1)[0] in aliases and node.attr in names:
                hits.append(f"{node.lineno} -> {dotted}")
        # 3. `getattr(srv, "full_audit")`, qui contournerait les deux premières.
        elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in {
            "getattr",
            "hasattr",
            "setattr",
        }:
            if len(node.args) < 2:
                continue
            base, attr = _dotted(node.args[0]), node.args[1]
            if base in aliases and isinstance(attr, ast.Constant) and attr.value in names:
                hits.append(f"{node.lineno} -> {node.func.id}({base}, {attr.value!r})")
    return hits


def test_no_repository_code_reaches_a_tool_through_the_server_module():
    names = _tool_names()
    assert len(names) >= 50, "prémisse : l'inventaire des outils doit être peuplé"

    offenders: list[str] = []
    for path in sorted(REPO.rglob("*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name == Path(__file__).name:
            continue  # ce fichier porte les échantillons du contrôle
        source = path.read_text(encoding="utf-8")
        offenders += [
            f"{path.relative_to(REPO)}:{hit}" for hit in _tool_accesses(source, path, names)
        ]
    assert not offenders, f"un outil est repris via `server` : {offenders}"


@pytest.mark.parametrize(
    "sample",
    [
        "from audit_bim.mcp import server as srv\nsrv.full_audit(cloud_id='c')\n",
        "from audit_bim.mcp.server import full_audit\nfull_audit()\n",
        "import audit_bim.mcp.server as s\nvalue = getattr(s, 'set_active_model')\n",
        "from audit_bim.mcp import server\nserver.prepare_bcf_from_findings()\n",
    ],
    ids=["attribut-alias", "import-direct", "getattr", "alias-legacy"],
)
def test_the_guard_recognises_every_form(sample):
    """Non-vacuité, forme par forme.

    Le dernier cas est celui des aliases LEGACY : absents des goldens, ils
    seraient le trou naturel d'un inventaire construit sur eux seuls.
    """
    assert _tool_accesses(sample, REPO / "probe.py", _tool_names()), sample


def test_the_guard_does_not_flag_the_three_allowed_names():
    """`main`, `mcp` et `list_mcp_profiles` restent légitimes."""
    sample = (
        "from audit_bim.mcp import server\n"
        "server.main()\n"
        "srv_mcp = server.mcp\n"
        "server.list_mcp_profiles()\n"
    )
    assert not _tool_accesses(sample, REPO / "probe.py", _tool_names())


# ── 3. Le module reste importable, et n'enregistre rien ───────────────


def test_importing_the_server_module_registers_nothing():
    """Il doit rester importable pour ``main``, ``mcp`` et l'outil transverse.

    Et son import ne doit toujours rien enregistrer : c'est ce qui garantit que
    l'ordre d'import ne peut pas contourner la sélection de profil.
    """
    probe = (
        "import json, sys\n"
        "import audit_bim.mcp.server as s\n"
        "import anyio\n"
        "print(json.dumps({\n"
        "    'names': sorted(n for n in ('main', 'mcp', 'list_mcp_profiles') if hasattr(s, n)),\n"
        "    'tools': sorted(t.name for t in anyio.run(s.mcp.list_tools)),\n"
        "    'i3f': sorted(m for m in sys.modules if m.startswith('audit_bim.profiles.i3f')),\n"
        "}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PATH": "/usr/bin:/bin", "HOME": str(REPO)},
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    seen = json.loads(result.stdout.strip().splitlines()[-1])

    assert seen["names"] == ["list_mcp_profiles", "main", "mcp"]
    assert seen["tools"] == ["list_mcp_profiles"], seen["tools"]
    assert seen["i3f"] == [], f"l'import du module a chargé le profil I3F : {seen['i3f']}"
