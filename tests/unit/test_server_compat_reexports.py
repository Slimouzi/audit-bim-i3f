"""Ré-exports ``server.<tool>`` — compatibilité, pas API principale.

Depuis E3-B, **aucun appelant du dépôt ne les utilise** : tests et scripts
passent par ``audit_bim.profiles.i3f.tools_*``. Ils ne subsistent que pour un
consommateur externe éventuel.

Ces tests les traitent comme tels : on vérifie qu'ils fonctionnent encore et
qu'ils désignent les mêmes objets que le profil, **et** qu'aucun code du dépôt
n'en dépend — sans quoi « déprécié » resterait une intention, pas un état.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from audit_bim.mcp import server
from audit_bim.profiles.i3f import (
    tools_actions,
    tools_audit,
    tools_query,
    tools_reporting,
    tools_session,
)

REPO = Path(server.__file__).resolve().parents[2]

#: Les modules du profil, par ordre de recherche du propriétaire d'un outil.
PROFILE_MODULES = (tools_session, tools_audit, tools_reporting, tools_actions, tools_query)

#: Aliases LEGACY : ré-exportés **paresseusement** (PEP 562), pour ne pas
#: enregistrer les 8 outils opt-in au simple import de ``server``.
LAZY_ALIASES = (
    "prepare_bcf_from_findings",
    "apply_bcf_plan",
    "prepare_smartviews_from_findings",
    "apply_smartviews_plan",
    "prepare_classification_corrections",
    "apply_classification_corrections",
    "prepare_doe_enrichment_from_file",
    "apply_doe_enrichment",
)


def _reexported_names() -> list[str]:
    """Noms importés par ``server.py`` depuis le profil."""
    tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    return [
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module and "profiles.i3f" in node.module
        for alias in node.names
    ]


# ── 1. La compat fonctionne toujours ──────────────────────────────────


def test_reexports_are_the_same_objects_as_the_profile():
    """Un ré-export doit désigner l'objet du profil, pas une copie."""
    mismatched = []
    for name in _reexported_names():
        exported = getattr(server, name)
        source = next(
            (getattr(m, name) for m in PROFILE_MODULES if getattr(m, name, None) is not None),
            None,
        )
        if source is not None and exported is not source:
            mismatched.append(name)
    assert not mismatched, f"ré-exports divergents : {mismatched}"


@pytest.mark.parametrize("name", LAZY_ALIASES)
def test_legacy_aliases_stay_lazily_reachable(name):
    """Accessibles à la demande, sans enregistrer les outils opt-in."""
    assert callable(getattr(server, name))


def test_unknown_attribute_still_raises():
    """Le ``__getattr__`` lazy ne doit pas avaler les noms inconnus."""
    missing = "un_outil_qui_nexiste_pas"  # variable : ruff refuse getattr littéral
    with pytest.raises(AttributeError):
        getattr(server, missing)


# ── 2. Plus personne dans le dépôt n'en dépend ────────────────────────

_SERVER_MODULE = "audit_bim.mcp.server"

#: Liste d'alias devinés d'une version antérieure du contrôle. Conservée pour
#: prouver, en test, ce qu'elle laissait passer (cf. la non-vacuité plus bas).
_GUESSED_ALIASES = ("server", "mcp_server", "ms")


def _server_aliases(tree: ast.Module, path: Path) -> set[str]:
    """Toutes les expressions qui, **dans ce fichier**, désignent ``server``.

    Le nom d'un alias est un choix local : ``as srv``, ``as s``, n'importe quoi.
    On ne peut donc pas l'énumérer d'avance — il faut lire les imports.
    """
    found = {_SERVER_MODULE}
    try:
        package = ".".join(path.relative_to(REPO).parts[:-1])
    except ValueError:  # source hors dépôt (extrait de test)
        package = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _SERVER_MODULE:
                    found.add(alias.asname or alias.name)
                elif alias.name == "audit_bim.mcp" and alias.asname:
                    found.add(f"{alias.asname}.server")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:  # import relatif : résolu depuis le paquet du fichier
                parts = package.split(".")
                base = parts[: len(parts) - node.level + 1]
                module = ".".join([*base, module] if module else base)
            for alias in node.names:
                if module == "audit_bim.mcp" and alias.name == "server":
                    found.add(alias.asname or "server")
                elif module == "audit_bim" and alias.name == "mcp":
                    found.add(f"{alias.asname or 'mcp'}.server")
    return found


def _dotted(node: ast.AST) -> str | None:
    """``a.b.c`` sous forme de chaîne, ou ``None`` si la base n'est pas un nom."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _reexport_accesses(source: str, path: Path, names: set[str]) -> list[str]:
    """Accès à un ré-export depuis ``source``, quel que soit l'alias employé.

    Couvre l'accès direct (``srv.full_audit``) **et** l'accès par chaîne
    (``getattr(srv, "full_audit")``), qui contournerait sinon le contrôle.
    """
    tree = ast.parse(source)
    aliases = _server_aliases(tree, path)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted and dotted.rsplit(".", 1)[0] in aliases and node.attr in names:
                hits.append(f"{node.lineno} -> {dotted}")
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


def test_no_repository_code_uses_a_reexported_tool():
    """« Déprécié » doit être un état, pas une intention.

    Tant qu'un test passe par ``server.<tool>``, le ré-export reste sur le
    chemin critique : le retirer casserait la suite, donc personne ne le
    retire. Ce contrôle fige la migration faite en E3-B.
    """
    names = set(_reexported_names()) | set(LAZY_ALIASES)
    offenders: list[str] = []
    for path in sorted(REPO.rglob("*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name == Path(__file__).name:
            continue  # ce fichier exerce délibérément la compat
        source = path.read_text(encoding="utf-8")
        offenders += [
            f"{path.relative_to(REPO)}:{hit}" for hit in _reexport_accesses(source, path, names)
        ]
    assert not offenders, f"usages des ré-exports dépréciés : {offenders}"


def test_the_dependency_guard_sees_through_an_arbitrary_alias(tmp_path):
    """Non-vacuité — et raison d'être de l'analyse AST.

    La version regex de ce contrôle énumérait trois alias plausibles. Un
    ``as srv`` lui échappait : elle affirmait « zéro appel » alors qu'elle
    vérifiait « zéro appel sous trois noms devinés ». On le prouve ici plutôt
    que de le documenter.
    """
    names = set(_reexported_names()) | set(LAZY_ALIASES)
    sample = (
        "from audit_bim.mcp import server as srv\n"
        "srv.full_audit(cloud_id='c')\n"
        "value = getattr(srv, 'set_active_model')\n"
    )
    probe = tmp_path / "probe.py"

    hits = _reexport_accesses(sample, probe, names)
    assert len(hits) == 2, hits

    guessed = re.compile(rf"\b(?:{'|'.join(_GUESSED_ALIASES)})\.([a-z_][a-z0-9_]*)\b")
    assert not [h for h in guessed.findall(sample) if h in names], (
        "l'ancien contrôle par liste d'alias aurait manqué ce cas — c'est ce qui est corrigé"
    )


def test_the_dependency_guard_resolves_a_relative_import(tmp_path):
    """Un import relatif interne (``from . import server``) est couvert aussi."""
    names = set(_reexported_names()) | set(LAZY_ALIASES)
    probe = REPO / "audit_bim" / "mcp" / "probe.py"  # chemin non écrit sur disque
    sample = "from . import server as s\ns.full_audit()\n"
    assert _reexport_accesses(sample, probe, names)


# ── 3. Les ré-exports ne portent plus l'enregistrement ────────────────


def test_registration_never_imports_the_compat_module():
    """``register_all()`` n'a plus besoin de ``server`` du tout.

    Le contrôle portait d'abord sur la présence d'une ligne d'import littérale
    dans ``app.py``. E4 a rendu ces imports dynamiques (pilotés par le profil),
    et la formulation textuelle est devenue fausse alors que la propriété, elle,
    est plus vraie qu'avant. On mesure donc le fait plutôt que sa graphie : dans
    un interpréteur neuf, ``audit_bim.mcp.server`` reste **absent** de
    ``sys.modules`` après enregistrement complet.

    C'est aussi ce qui rendra la suppression des ré-exports sûre : rien du
    chemin de démarrage ne les traverse.
    """
    repo = REPO
    probe = (
        "import sys, json\n"
        "from audit_bim.mcp.app import register_all\n"
        "register_all()\n"
        "print(json.dumps({\n"
        "    'server': 'audit_bim.mcp.server' in sys.modules,\n"
        "    'tools': 'audit_bim.profiles.i3f.tools_audit' in sys.modules,\n"
        "}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=repo,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo)},
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    seen = json.loads(result.stdout.strip().splitlines()[-1])

    # Non-vacuité : la sonde doit voir les modules réellement chargés.
    assert seen["tools"], "la sonde ne mesure pas sys.modules — le reste ne prouve rien"
    assert not seen["server"], "le démarrage traverse encore le module de compat"
