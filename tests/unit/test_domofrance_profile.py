"""Profil Domofrance — troisième profil, isolé des DEUX autres.

Avec deux profils, l'isolation se disait « ne pas importer I3F ». Avec trois,
elle devient **croisée** : chaque profil doit ignorer les deux autres, et le
contrôle doit être symétrique. Un garde-fou écrit une seule fois, dans le sens
Domofrance → frères, laisserait un frère importer Domofrance sans bruit.

Trois propriétés, testées séparément parce qu'elles échouent séparément :

1. aucun import d'un profil frère, dans les deux sens ;
2. aucun outil d'un frère nommé dans ce qui part chez l'utilisateur — un
   modèle qui lit « appelle `full_audit` » tentera de l'appeler, et l'outil
   n'existe pas dans cette surface ;
3. après un enregistrement **réel**, ``sys.modules`` ne porte aucun module de
   profil frère. Un import statique se voit ; un import déclenché à l'appel,
   non.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROFILES_DIR = REPO / "audit_bim" / "profiles"
DOMOFRANCE_DIR = PROFILES_DIR / "domofrance"
SOURCES = sorted(DOMOFRANCE_DIR.rglob("*.py"))

#: Les deux profils frères, par leur segment de module.
SIBLINGS = ("profiles.i3f", "profiles.bim_in_motion")

#: Vocabulaire propre aux référentiels des frères. Cherché dans tout ce qui part
#: chez l'utilisateur : un persona hérité prêterait à Domofrance un référentiel
#: qui n'est pas le sien, et cela ne se verrait dans aucun import.
SIBLING_VOCABULARY = ("i3f", "cch", "avp", "uniformat", "omniclass", "mrn")


def test_the_profile_has_sources():
    """Sentinelle : sans elle, tous les contrôles ci-dessous seraient vacants."""
    assert len(SOURCES) >= 4, SOURCES


# ── 1. Aucun import croisé ────────────────────────────────────────────


def _imported_modules(tree: ast.Module, path: Path) -> list[str]:
    """Modules importés, imports relatifs résolus depuis le paquet du fichier."""
    package = ".".join(path.relative_to(REPO).parts[:-1])
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:  # `from ...mcp.app import mcp` → audit_bim.mcp.app
                parts = package.split(".")
                base = parts[: len(parts) - node.level + 1]
                module = ".".join([*base, module] if module else base)
            found += [module, *(f"{module}.{a.name}" for a in node.names)]
    return found


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_domofrance_imports_no_sibling_profile(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [m for m in _imported_modules(tree, path) if any(s in m for s in SIBLINGS)]
    assert not offenders, f"{path.name} importe un profil frère : {offenders}"


@pytest.mark.parametrize("sibling", ["i3f", "bim_in_motion"])
def test_no_sibling_profile_imports_domofrance(sibling):
    """La réciproque. Sans elle, l'isolation ne serait affirmée que d'un côté."""
    offenders: list[str] = []
    for path in sorted((PROFILES_DIR / sibling).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [
            f"{path.name} -> {m}"
            for m in _imported_modules(tree, path)
            if "profiles.domofrance" in m
        ]
    assert not offenders, f"le profil {sibling} importe Domofrance : {offenders}"


def test_the_import_guard_is_not_vacuous():
    """Le contrôle doit reconnaître les deux formes d'import, dont la relative."""
    probe = DOMOFRANCE_DIR / "probe.py"  # chemin non écrit sur disque

    absolue = ast.parse("from audit_bim.profiles.i3f.tools_audit import full_audit\n")
    assert [m for m in _imported_modules(absolue, probe) if "profiles.i3f" in m]

    relative = ast.parse("from ..bim_in_motion import tools_mrn\n")
    assert [m for m in _imported_modules(relative, probe) if "profiles.bim_in_motion" in m], (
        "l'import relatif doit être résolu, sinon le garde-fou est contournable"
    )


# ── 2. Rien d'un frère ne part chez l'utilisateur ─────────────────────


def _shipped_texts(tree: ast.Module) -> list[tuple[int, str]]:
    """Textes qui **partent chez l'utilisateur**, docstrings d'outils comprises.

    La docstring de module explique la frontière : la lui interdire reviendrait
    à interdire de l'écrire. En revanche la docstring d'un ``@mcp.tool`` est
    envoyée au modèle comme description, et une constante de texte finit dans
    une réponse — celles-là doivent être propres.
    """
    shipped: list[tuple[int, str]] = []
    a_ignorer: set[int] = set()

    module_doc = ast.get_docstring(tree, clean=False)
    if module_doc and tree.body and isinstance(tree.body[0], ast.Expr):
        a_ignorer.add(id(tree.body[0].value))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            first = node.body[0] if node.body else None
            is_tool = any(
                getattr(getattr(d, "func", d), "attr", None) in {"tool", "prompt"}
                for d in getattr(node, "decorator_list", [])
            )
            if doc and isinstance(first, ast.Expr):
                if is_tool:
                    shipped.append((first.lineno, doc))
                a_ignorer.add(id(first.value))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in a_ignorer
        ):
            shipped.append((node.lineno, node.value))
    return shipped


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_sibling_vocabulary_reaches_the_user(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [
        f"{path.name}:{lineno} -> {term!r}"
        for lineno, text in _shipped_texts(tree)
        for term in SIBLING_VOCABULARY
        if re.search(rf"\b{re.escape(term)}\b", text, re.I)
    ]
    assert not offenders, f"vocabulaire d'un profil frère servi à l'utilisateur : {offenders}"


def _golden(profile: str) -> dict:
    path = (
        Path(__file__).parent
        / "golden"
        / ("mcp_surface.json" if profile == "i3f" else f"mcp_surface_{profile}.json")
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_no_text_names_a_tool_absent_from_the_surface():
    """Un nom d'outil dans une description est une **instruction** au modèle.

    Nommer `full_audit` dans un texte Domofrance conduirait un agent à tenter un
    appel qui n'existe pas dans cette surface. Le contrôle porte sur les noms
    d'outils des frères qui ne sont pas dans celle de Domofrance — les outils du
    socle, eux, sont légitimement communs.
    """
    a_nous = set(_golden("domofrance")["tools"])
    interdits = (set(_golden("i3f")["tools"]) | set(_golden("bim_in_motion")["tools"])) - a_nous
    assert interdits, "sentinelle : sans nom interdit, le test ne prouverait rien"

    offenders: list[str] = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [
            f"{path.name}:{lineno} -> {nom}"
            for lineno, text in _shipped_texts(tree)
            for nom in interdits
            if re.search(rf"\b{re.escape(nom)}\b", text)
        ]
    assert not offenders, (
        f"outil absent de la surface Domofrance, nommé chez l'utilisateur : {offenders}"
    )


def test_the_prompt_shares_no_sentence_with_a_sibling():
    """Deux personas ne doivent pas partager de phrases.

    Le contrôle de vocabulaire ne suffirait pas : un paragraphe de posture
    entier peut être repris sans contenir un seul terme d'un frère.
    """
    from audit_bim.profiles.bim_in_motion.prompts import AMO_BIM_IN_MOTION_PROMPT
    from audit_bim.profiles.domofrance.prompts import AMO_BIM_DOMOFRANCE_PROMPT
    from audit_bim.profiles.i3f.prompts import AMO_BIM_I3F_PROMPT

    def phrases(text: str) -> set[str]:
        parts = re.split(r"[.\n]", text)
        return {" ".join(p.split()) for p in parts if len(p.split()) >= 6}

    a_nous = phrases(AMO_BIM_DOMOFRANCE_PROMPT)
    assert len(a_nous) >= 5, "non-vacuité : la découpe doit produire des phrases"
    for nom, autre in (("i3f", AMO_BIM_I3F_PROMPT), ("bim_in_motion", AMO_BIM_IN_MOTION_PROMPT)):
        partagees = a_nous & phrases(autre)
        assert not partagees, f"phrases communes avec le prompt {nom} : {partagees}"


# ── 3. Isolation à l'exécution, pas seulement à la lecture ────────────


_PROBE = textwrap.dedent(
    """
    import json, sys
    from audit_bim.mcp.app import register_all, registered_profile_id
    import anyio

    mcp = register_all()
    tools = anyio.run(mcp.list_tools)
    prompts = anyio.run(mcp.list_prompts)
    print(json.dumps({
        "profile": registered_profile_id(),
        "tools": sorted(t.name for t in tools),
        "prompts": sorted(p.name for p in prompts),
        "i3f_modules": sorted(m for m in sys.modules if "profiles.i3f" in m),
        "bim_in_motion_modules": sorted(m for m in sys.modules if "profiles.bim_in_motion" in m),
    }))
    """
)


def _register_in_subprocess(profile: str) -> dict:
    """Enregistrement réel dans un interpréteur neuf.

    Dans le processus de test, d'autres modules ont déjà importé les profils
    frères : y mesurer ``sys.modules`` ne dirait rien de ce que ce profil charge.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env={"PATH": "/usr/bin:/bin", "HOME": str(REPO), "AUDIT_BIM_PROFILE": profile},
    )
    assert proc.returncode == 0, f"enregistrement échoué :\n{proc.stderr}"
    return json.loads(proc.stdout)


def test_registering_domofrance_loads_no_sibling_module():
    """Le contrôle qu'aucune lecture statique ne remplace."""
    mesure = _register_in_subprocess("domofrance")
    assert mesure["profile"] == "domofrance"
    assert mesure["i3f_modules"] == [], mesure["i3f_modules"]
    assert mesure["bim_in_motion_modules"] == [], mesure["bim_in_motion_modules"]
    assert mesure["prompts"] == ["amo_bim_domofrance"]
    assert len(mesure["tools"]) == 8


def test_the_runtime_guard_is_not_vacuous():
    """Sentinelle : la sonde doit VOIR les modules quand ils sont chargés.

    Sans elle, une sonde qui ne mesurerait rien ferait passer les trois profils
    pour isolés.
    """
    mesure = _register_in_subprocess("bim_in_motion")
    assert mesure["bim_in_motion_modules"], (
        "la sonde doit voir les modules du profil actif, sinon elle ne mesure rien"
    )
    assert mesure["i3f_modules"] == []


def test_the_sibling_surfaces_are_unchanged():
    """Ajouter un profil ne doit toucher ni I3F ni BIM in Motion."""
    i3f = _register_in_subprocess("i3f")
    assert len(i3f["tools"]) == 46
    assert i3f["prompts"] == ["amo_bim_i3f"]

    bim = _register_in_subprocess("bim_in_motion")
    assert len(bim["tools"]) == 8
    assert bim["prompts"] == ["amo_bim_in_motion"]


# ── 4. Ce que le profil ne fait pas ───────────────────────────────────


def test_the_tool_emits_no_conformity_status():
    """Le profil mesure l'évaluabilité ; il ne juge pas."""
    from audit_bim.profiles.domofrance.coverage import STATUSES

    for status in STATUSES:
        assert "conforme" not in status
        assert "compliant" not in status


def test_the_tool_writes_no_spreadsheet():
    """Aucune écriture Excel : la seule sortie facultative est un résumé JSON."""
    source = (DOMOFRANCE_DIR / "tools_coverage.py").read_text(encoding="utf-8")
    for interdit in ("openpyxl", "xlsxwriter", ".xlsx", "save("):
        assert interdit not in source, f"écriture tableur dans l'outil : {interdit!r}"
