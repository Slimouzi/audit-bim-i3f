"""Frontière E2 : `audit_bim/mcp` ne porte plus que bootstrap et câblage.

Le profil I3F — prompts, outils, aliases — vit sous `audit_bim/profiles/i3f/`.
C'est ce qui permettra à un second AMO de déclarer les siens à côté, sans
toucher au serveur.

E2 est un **déplacement**, pas une réorganisation : aucun nom d'outil, de
prompt, d'alias ni de paramètre ne change. Le contrôle de référence est le dump
MCP strict, comparé octet pour octet contre `master`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from audit_bim import mcp as mcp_pkg
from audit_bim.profiles import i3f as i3f_pkg

MCP_DIR = Path(mcp_pkg.__file__).parent
I3F_DIR = Path(i3f_pkg.__file__).parent

#: Modules déplacés en E2. Leur présence dans `mcp/` serait une régression.
MOVED_MODULES = (
    "prompts",
    "tools_audit",
    "tools_reporting",
    "tools_actions",
    "tools_query",
    "tools_session",
    "aliases",
)

#: Le seul outil qui reste côté serveur : il liste les profils, il n'appartient
#: donc à aucun d'eux.
SERVER_OWNED_TOOLS = {"tools_profiles"}


def _registrations(path: Path) -> int:
    """Nombre de ``@mcp.tool`` / ``@mcp.prompt`` déclarés dans un fichier."""
    return sum(
        1
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"tool", "prompt"}
    )


# ── 1. Le profil a bien déménagé ──────────────────────────────────────


@pytest.mark.parametrize("name", MOVED_MODULES)
def test_module_lives_in_the_profile_package(name):
    assert (I3F_DIR / f"{name}.py").is_file()
    assert not (MCP_DIR / f"{name}.py").exists(), f"{name}.py subsiste dans mcp/"


def test_mcp_declares_no_profile_tool():
    """Seuls le prompt du serveur et `list_mcp_profiles` restent côté mcp/.

    Le prompt I3F est ré-exporté par `server.py` — c'est du câblage, pas une
    déclaration : le texte vit dans le profil.
    """
    declaring = {
        path.stem: _registrations(path)
        for path in sorted(MCP_DIR.glob("*.py"))
        if _registrations(path)
    }
    assert set(declaring) <= SERVER_OWNED_TOOLS | {"server"}, (
        f"des outils sont encore déclarés côté serveur : {declaring}"
    )


def test_profile_carries_the_tool_surface():
    total = sum(_registrations(p) for p in sorted(I3F_DIR.glob("*.py")))
    assert total >= 45, f"seulement {total} enregistrements dans le profil"


# ── 2. Le déplacement n'a rien renommé ────────────────────────────────


def test_public_names_are_still_reachable_from_server():
    """Les ré-exports de compat continuent de fonctionner."""
    from audit_bim.mcp import server

    for name in ("set_active_model", "generate_avp_i3f_pack", "run_audit_tool"):
        assert callable(getattr(server, name))


def test_legacy_aliases_are_still_lazily_reachable():
    """Les aliases restent opt-in : accessibles, mais non enregistrés par défaut."""
    from audit_bim.mcp import server

    assert callable(server.prepare_bcf_from_findings)


def test_prompt_text_moved_without_being_touched():
    from audit_bim.mcp import server
    from audit_bim.profiles.i3f.prompts import AMO_BIM_I3F_PROMPT

    assert server.AMO_BIM_I3F_PROMPT is AMO_BIM_I3F_PROMPT
    assert AMO_BIM_I3F_PROMPT.strip()


# ── 3. Le registre de profils dit vrai ────────────────────────────────


def test_registry_points_at_the_new_location():
    """`test_ready_specializations_point_to_existing_paths` a attrapé ce cas.

    Le registre déclarait `audit_bim/mcp/prompts.py` ; le garde-fou de véracité
    a rougi au déplacement, ce pour quoi il avait été écrit.
    """
    from audit_bim.profiles import get_profile

    locations = {
        spec.key: spec.current_location
        for spec in get_profile("i3f").specializations
        if spec.current_location
    }
    assert locations["prompt_i3f"] == "audit_bim/profiles/i3f/prompts.py"
    for location in locations.values():
        assert Path(location).exists() or (Path.cwd() / location).exists()
