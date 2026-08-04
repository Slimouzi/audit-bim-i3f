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
import re
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


def test_no_repository_code_calls_a_reexported_tool():
    """« Déprécié » doit être un état, pas une intention.

    Tant qu'un test appelle ``server.<tool>``, le ré-export reste sur le chemin
    critique : le retirer casserait la suite, donc personne ne le retire. Ce
    contrôle fige la migration faite en E3-B.
    """
    names = set(_reexported_names()) | set(LAZY_ALIASES)
    pattern = re.compile(r"\b(?:server|mcp_server|ms)\.([a-z_][a-z0-9_]*)\b")
    offenders: list[str] = []
    for path in sorted(REPO.rglob("*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name == Path(__file__).name:
            continue  # ce fichier exerce délibérément la compat
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for hit in pattern.findall(line):
                if hit in names:
                    offenders.append(f"{path.relative_to(REPO)}:{lineno} -> server.{hit}")
    assert not offenders, f"appels via les ré-exports dépréciés : {offenders}"


def test_the_dependency_guard_is_not_vacuous():
    """Le contrôle doit reconnaître un appel via ré-export."""
    names = set(_reexported_names()) | set(LAZY_ALIASES)
    sample = "result = mcp_server.generate_avp_i3f_pack(output_dir=out)"
    pattern = re.compile(r"\b(?:server|mcp_server|ms)\.([a-z_][a-z0-9_]*)\b")
    assert any(hit in names for hit in pattern.findall(sample))


# ── 3. Les ré-exports ne portent plus l'enregistrement ────────────────


def test_registration_does_not_depend_on_the_reexports():
    """Depuis E3-A, ``register_all()`` importe elle-même les modules du profil.

    Les ré-exports sont donc un pur choix de compatibilité : les retirer serait
    sans effet sur la surface MCP. C'est ce qui rendra leur suppression sûre
    quand on la décidera.
    """
    source = Path(Path(server.__file__).parent / "app.py").read_text(encoding="utf-8")
    assert "from ..profiles.i3f import" in source
    for module in ("tools_session", "tools_audit", "tools_reporting", "tools_actions"):
        assert module in source, f"register_all() n'importe pas {module}"
