"""Adoption du moteur `bim-mcp-runtime` — invisible côté MCP.

E1-B est une adoption **mécanique** : la mécanique de session vient du moteur,
la surface MCP ne bouge pas d'un nom. Ces tests verrouillent l'invisibilité,
puisque c'est le seul critère qui compte pour un client déjà branché.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import anyio
import pytest
from bim_mcp_runtime import SessionBinding, SessionStore

from audit_bim.mcp import server as mcp_server
from audit_bim.mcp import session as session_mod

#: Surface MCP figée AVANT l'adoption. Toute divergence est une régression.
EXPECTED_TOOL_COUNT = 46
EXPECTED_PROMPT_COUNT = 1

#: Aliases métier LEGACY, opt-in par variable d'environnement. Un autre test de
#: la suite les active sur le registre partagé : le comptage brut dépend donc de
#: l'ordre d'exécution. On raisonne sur les noms canoniques, pas sur un total.
LEGACY_ALIASES = frozenset(
    {
        "prepare_bcf_from_findings",
        "apply_bcf_plan",
        "prepare_smartviews_from_findings",
        "apply_smartviews_plan",
        "prepare_classification_corrections",
        "apply_classification_corrections",
        "prepare_doe_enrichment_from_file",
        "apply_doe_enrichment",
    }
)

#: Outils dont la présence est explicitement exigée par la revue.
REQUIRED_TOOLS = ("set_active_model", "generate_avp_i3f_pack", "parse_bimdata_target")

#: Paramètres RELEVÉS sur la surface réelle, pas devinés. Une première version
#: de ce test présupposait un ``bimdata_url`` sur ``set_active_model`` : il
#: n'existe pas, et le test échouait donc sur du code sain. Retaper une
#: signature de mémoire est le même piège que retaper une table de constantes.
SET_ACTIVE_MODEL_PARAMS = {
    "cloud_id",
    "project_id",
    "model_id",
    "phase",
    "classification_system",
    "access_token",
}


def _tools() -> list[str]:
    return sorted(t.name for t in anyio.run(mcp_server.mcp.list_tools))


def _prompts() -> list[str]:
    return sorted(p.name for p in anyio.run(mcp_server.mcp.list_prompts))


# ── 1. La surface MCP ne bouge pas ────────────────────────────────────


def test_canonical_tool_and_prompt_counts_are_unchanged():
    """Comptage des outils CANONIQUES, aliases legacy exclus.

    Compter tout le registre rendrait ce test dépendant de l'ordre de la suite :
    un autre test active les aliases opt-in sur l'instance partagée. Le nombre
    aurait alors varié entre exécution isolée et exécution complète — un test
    intermittent, pire qu'un test absent.
    """
    canonical = [name for name in _tools() if name not in LEGACY_ALIASES]
    assert len(canonical) == EXPECTED_TOOL_COUNT
    assert len(_prompts()) == EXPECTED_PROMPT_COUNT


def test_no_unexpected_tool_appeared():
    """Tout outil hors des 46 canoniques doit être un alias legacy connu."""
    unexpected = {n for n in _tools() if n not in LEGACY_ALIASES}
    assert len(unexpected) == EXPECTED_TOOL_COUNT, (
        f"{len(unexpected)} outils canoniques au lieu de {EXPECTED_TOOL_COUNT}"
    )


@pytest.mark.parametrize("name", REQUIRED_TOOLS)
def test_required_tools_are_still_exposed(name):
    assert name in _tools()


def test_prompt_is_still_exposed():
    assert _prompts() == ["amo_bim_i3f"]


def _tool_params(name: str) -> set[str]:
    """Paramètres réels d'un outil, lus depuis le registre du serveur."""
    tool = next(t for t in anyio.run(mcp_server.mcp.list_tools) if t.name == name)
    return set(inspect.signature(tool.fn).parameters)


def test_set_active_model_signature_is_unchanged():
    """Une adoption qui renommerait un paramètre casserait les clients."""
    assert _tool_params("set_active_model") == SET_ACTIVE_MODEL_PARAMS


def test_avp_pack_keeps_its_key_parameters():
    params = _tool_params("generate_avp_i3f_pack")
    for expected in ("output_dir", "envelope_json", "confirm_context", "export_pdf"):
        assert expected in params, f"generate_avp_i3f_pack a perdu {expected!r}"


def test_every_tool_still_exposes_a_callable():
    """Aucun outil n'a été enveloppé au passage : `fn` reste inspectable."""
    for tool in anyio.run(mcp_server.mcp.list_tools):
        assert callable(tool.fn)
        inspect.signature(tool.fn)


# ── 2. La mécanique vient bien du moteur ──────────────────────────────


def test_store_and_binding_come_from_the_runtime():
    assert isinstance(session_mod._store, SessionStore)
    assert isinstance(session_mod._binding, SessionBinding)


def test_session_fields_stay_in_this_repo():
    """Le moteur ne connaît pas l'état : ses champs restent métier, ici."""
    state = session_mod._Session()
    for field in ("catalog", "client", "snapshot", "result", "classification_system"):
        assert hasattr(state, field), f"{field} a disparu de la session"


def test_no_local_store_implementation_remains():
    """Plus de magasin local : sinon deux implémentations divergeraient."""
    source = Path(session_mod.__file__).read_text(encoding="utf-8")
    classes = {node.name for node in ast.parse(source).body if isinstance(node, ast.ClassDef)}
    assert "_SessionStore" not in classes
    assert "_StateProxy" not in classes
    assert "_Session" in classes


def test_environment_prefix_is_the_server_one():
    """Aucune migration de déploiement : les variables historiques sont lues."""
    config = session_mod._runtime_config
    assert config.env_name("SESSION_TTL_S") == "AUDIT_BIM_SESSION_TTL_S"
    assert config.env_name("MAX_SESSIONS") == "AUDIT_BIM_MAX_SESSIONS"


def test_state_proxy_still_routes_to_the_current_session():
    """Les tools écrits contre `_State` ne doivent rien changer."""
    other = session_mod._Session()
    other.model_id = "abc"
    token = session_mod.current_session.set(other)
    try:
        assert session_mod._State.model_id == "abc"
        session_mod._State.model_id = "def"
        assert other.model_id == "def"
    finally:
        session_mod.current_session.reset(token)


# ── 3. Le moteur reste pur, vu d'ici ──────────────────────────────────

RUNTIME_PURITY_SCRIPT = textwrap.dedent(
    """
    import ast, re, sys
    from pathlib import Path
    import bim_mcp_runtime

    package = Path(bim_mcp_runtime.__file__).parent
    sources = sorted(package.rglob("*.py"))

    offenders = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        if "AUDIT_BIM" in text or "audit_bim" in text:
            offenders.append(f"{path.name}: vocabulaire serveur")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    target = deco.func if isinstance(deco, ast.Call) else deco
                    if getattr(target, "attr", None) in {"tool", "prompt", "resource"}:
                        offenders.append(f"{path.name}:{node.name}: outil declare")

    if offenders:
        raise SystemExit("MOTEUR IMPUR : " + " | ".join(offenders))

    leaked = [m for m in sys.modules if m.startswith("audit_bim")]
    if leaked:
        raise SystemExit("MOTEUR IMPORTE LE SERVEUR : " + ", ".join(sorted(leaked)))
    print("OK")
    """
)


def test_runtime_stays_pure_when_installed(tmp_path):
    """Le paquet installé ne contient ni `AUDIT_BIM`, ni outil déclaré.

    Exécuté dans un interpréteur **séparé** : dans le processus de test,
    `audit_bim` est déjà importé par les autres cas, donc la vérification
    d'absence y serait vide de sens.
    """
    script = tmp_path / "purity.py"
    script.write_text(RUNTIME_PURITY_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=tempfile.gettempdir(),
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "OK" in proc.stdout


def test_that_purity_script_can_fail(tmp_path):
    """Preuve de non-vacuité du script ci-dessus."""
    script = tmp_path / "leak.py"
    script.write_text(
        "import audit_bim.mcp.session  # noqa: F401\n" + RUNTIME_PURITY_SCRIPT,
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(Path(session_mod.__file__).resolve().parents[3]),
    )
    assert proc.returncode != 0
    assert "MOTEUR IMPORTE LE SERVEUR" in (proc.stdout + proc.stderr)
