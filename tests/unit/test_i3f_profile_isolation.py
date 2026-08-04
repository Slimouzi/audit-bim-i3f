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

import anyio
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


def test_mcp_declares_nothing_but_the_profile_listing_tool():
    """`list_mcp_profiles` est la SEULE déclaration restante sous `audit_bim/mcp`.

    E2 tolérait encore `server` dans cette liste, le temps qu'il porte le
    `@mcp.prompt()` I3F. E3-A l'a déplacé dans le profil : la tolérance tombe.
    La garder aurait laissé passer un futur `@mcp.tool()` ajouté au serveur —
    précisément la dérive que cette frontière existe pour empêcher.

    `list_mcp_profiles` reste : il énumère les profils, il n'appartient donc à
    aucun d'eux.
    """
    declaring = {
        path.stem: _registrations(path)
        for path in sorted(MCP_DIR.glob("*.py"))
        if _registrations(path)
    }
    assert set(declaring) <= SERVER_OWNED_TOOLS, (
        f"des outils ou prompts sont encore déclarés côté serveur : {declaring}"
    )


def test_the_server_tolerance_is_really_gone():
    """Preuve de non-vacuité : `server` n'est plus une exception admise."""
    assert "server" not in SERVER_OWNED_TOOLS
    assert _registrations(MCP_DIR / "server.py") == 0


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


def test_server_no_longer_knows_the_profile_prompt():
    """E3-A : le serveur ignore jusqu'au nom de la constante du profil.

    En E2, `server.py` importait encore `AMO_BIM_I3F_PROMPT` et portait le
    `@mcp.prompt()`. C'était la dernière déclaration client dans le serveur, et
    ce qui empêchait un second AMO d'enregistrer ses prompts sans le modifier.
    """
    from audit_bim.mcp import server

    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "AMO_BIM_I3F_PROMPT" not in source
    assert "@mcp.prompt" not in source


def test_prompt_is_registered_by_the_profile():
    """La déclaration vit dans le profil, et `register_all()` la déclenche."""
    from audit_bim.mcp.app import register_all
    from audit_bim.profiles.i3f.prompts import AMO_BIM_I3F_PROMPT, register_prompts

    assert callable(register_prompts)
    assert AMO_BIM_I3F_PROMPT.strip()

    mcp = register_all()
    names = [p.name for p in anyio.run(mcp.list_prompts)]
    assert names == ["amo_bim_i3f"]


def test_registering_prompts_twice_is_harmless():
    """`register_prompts` est idempotente par instance.

    `register_all()` l'est déjà, mais un appelant direct ne l'est pas — et
    FastMCP refuse un nom de prompt déjà pris.
    """
    from audit_bim.mcp.app import mcp
    from audit_bim.profiles.i3f.prompts import register_prompts

    register_prompts(mcp)
    register_prompts(mcp)
    names = [p.name for p in anyio.run(mcp.list_prompts)]
    assert names.count("amo_bim_i3f") == 1


def test_a_third_party_profile_can_register_its_own_prompt():
    """Un profil tiers enregistre son prompt SANS toucher à `server.py`.

    C'est le test qui prouve que la frontière tient : il n'importe rien du
    profil I3F, et n'a besoin d'aucune ligne côté serveur.
    """

    class _FakeApp:
        def __init__(self):
            self.registered: list[str] = []

        def prompt(self):
            def decorate(fn):
                self.registered.append(fn.__name__)
                return fn

            return decorate

    def register_prompts(app) -> None:
        @app.prompt()
        def amo_tiers() -> str:
            return "Persona AMO tiers."

    app = _FakeApp()
    register_prompts(app)
    assert app.registered == ["amo_tiers"]


def test_no_client_prompt_is_declared_in_mcp_package():
    """Contrôle statique : aucun `@mcp.prompt()` sous `audit_bim/mcp/`."""
    offenders = [
        f"{path.name}:{node.lineno}"
        for path in sorted(MCP_DIR.glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for deco in node.decorator_list
        if getattr(getattr(deco, "func", deco), "attr", None) == "prompt"
    ]
    assert not offenders, f"prompts déclarés côté serveur : {offenders}"


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


# ── 4. Aucun cycle d'import, quel que soit l'ordre ────────────────────

#: Chaque module du profil, importé **en premier** dans un interpréteur neuf.
#: C'est la condition qui révèle le cycle : en suite complète, un autre test a
#: déjà chargé ``audit_bim.mcp`` et le masque.
IMPORT_ORDERS = [
    "from audit_bim.profiles.i3f.tools_actions import apply_bcf_topics",
    "from audit_bim.profiles.i3f.tools_session import set_active_model",
    "from audit_bim.profiles.i3f.tools_reporting import generate_avp_i3f_pack",
    "from audit_bim.profiles.i3f.prompts import AMO_BIM_I3F_PROMPT",
    "from audit_bim.profiles.i3f import aliases",
    "from audit_bim.mcp import main, mcp, register_all",
    "import audit_bim.mcp.server",
]


@pytest.mark.parametrize("statement", IMPORT_ORDERS)
def test_no_circular_import_whatever_the_entry_point(statement):
    """Importer le profil en premier ne doit pas casser.

    E2 a introduit ce cycle : importer un module du profil initialise
    ``audit_bim.mcp``, dont l'``__init__`` importait ``server``, qui
    réimportait le module en cours. La suite locale ne le voyait pas — un
    autre test chargeait ``audit_bim.mcp`` avant. La CI, elle, a rougi.

    Un interpréteur neuf par cas : c'est le seul moyen de contrôler l'ordre.
    """
    import subprocess
    import sys

    repo = Path(mcp_pkg.__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-c", statement],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    assert proc.returncode == 0, f"{statement}\n{proc.stderr}"


# ── 5. Aucun chemin d'import mort dans le dépôt ───────────────────────

#: Modules qui ne vivent plus sous ``audit_bim.mcp``. Une référence résiduelle
#: est un import mort : il ne casse qu'à l'exécution du chemin concerné, donc
#: potentiellement jamais en test.
DEAD_MODULE_PATHS = tuple(f"audit_bim.mcp.{name}" for name in MOVED_MODULES)

#: Reste légitimement sous ``audit_bim.mcp`` : il liste les profils.
STILL_IN_MCP = "audit_bim.mcp.tools_profiles"

#: Module supprimé en v0.5.0 ; un test vérifie précisément son absence.
REMOVED_MODULE = "audit_bim.mcp.tools_legacy"


def test_no_dead_import_path_anywhere_in_the_repository():
    """Aucun fichier ne référence encore l'ancien emplacement.

    Ce contrôle est né d'un vrai manqué : `scripts/a1_replay/run_replay.py`
    importait `audit_bim.mcp.tools_actions` **dans le corps d'une fonction**.
    Aucun test ne parcourait ce chemin, la CI était verte, et le script était
    cassé — un `ModuleNotFoundError` à l'exécution.

    Un import différé n'est vérifié par rien tant qu'on ne l'exécute pas :
    seul un contrôle statique le voit.
    """
    root = Path(mcp_pkg.__file__).resolve().parents[2]
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name == Path(__file__).name:
            continue  # ce fichier cite les chemins morts pour les interdire
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if STILL_IN_MCP in line or REMOVED_MODULE in line:
                continue
            for dead in DEAD_MODULE_PATHS:
                if dead in line:
                    rel = path.relative_to(root)
                    offenders.append(f"{rel}:{lineno} -> {dead}")
    assert not offenders, f"chemins d'import morts : {offenders}"


def test_the_dead_path_guard_is_not_vacuous(tmp_path):
    """Le contrôle doit reconnaître une référence morte."""
    sample = "from audit_bim.mcp.tools_actions import apply_bcf_topics\n"
    assert any(dead in sample for dead in DEAD_MODULE_PATHS)
    # Et laisser passer ce qui reste légitimement sous mcp/.
    ok = "from audit_bim.mcp.tools_profiles import list_mcp_profiles\n"
    assert STILL_IN_MCP in ok


def test_the_a1_replay_runner_imports_resolve():
    """Le script qui a révélé le manqué doit importer sans erreur.

    Contrôle statique du module, sans l'exécuter : ses imports différés sont
    résolus en compilant puis en important les cibles citées.
    """
    root = Path(mcp_pkg.__file__).resolve().parents[2]
    runner = root / "scripts" / "a1_replay" / "run_replay.py"
    assert runner.is_file()
    source = runner.read_text(encoding="utf-8")
    compile(source, str(runner), "exec")
    for dead in DEAD_MODULE_PATHS:
        assert dead not in source, f"{runner.name} référence encore {dead}"
