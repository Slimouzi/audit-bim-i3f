"""Profil BIM in Motion — second consommateur, indépendant d'I3F (E5).

Ce profil vaut par ce qu'il n'a **pas** : aucun import d'I3F, aucun outil copié,
aucune phrase reprise. Ces trois propriétés sont testées séparément, parce
qu'elles échouent séparément — un import se voit, une copie non.

Son intérêt dépasse le profil lui-même : il donne un **second appelant réel**
aux briques neutres du dépôt. C'est ce qui rendra l'inventaire du socle partagé
mesurable plutôt que supposé — extraire un socle sur la foi d'un unique
consommateur, c'est encore concevoir sur hypothèse.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO / "audit_bim" / "profiles" / "bim_in_motion"
SOURCES = sorted(PROFILE_DIR.rglob("*.py"))

#: Vocabulaire propre à I3F. Cherché dans **tout** le texte, docstrings et
#: prompt compris : un persona hérité prêterait à BIM in Motion un référentiel
#: qui n'est pas le sien, et cela ne se verrait dans aucun import.
I3F_VOCABULARY = ("i3f", "cch", "avp", "uniformat", "omniclass")


def test_the_profile_has_sources():
    """Sentinelle : sans elle, tous les contrôles ci-dessous seraient vacants."""
    assert len(SOURCES) >= 3, SOURCES


# ── 1. Aucun import d'I3F ─────────────────────────────────────────────


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
def test_no_module_imports_the_i3f_profile(path):
    """Le verrou d'E5, sous sa forme statique.

    Un import relatif (``from ..i3f import …``) échapperait à une recherche de
    la chaîne « audit_bim.profiles.i3f » dans le texte : c'est pourquoi il est
    résolu ici avant d'être comparé.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [m for m in _imported_modules(tree, path) if "profiles.i3f" in m]
    assert not offenders, f"{path.name} importe le profil I3F : {offenders}"


def test_the_import_guard_is_not_vacuous(tmp_path):
    """Le contrôle doit reconnaître les deux formes d'import, dont la relative."""
    probe = PROFILE_DIR / "probe.py"  # chemin non écrit sur disque

    absolute = ast.parse("from audit_bim.profiles.i3f.tools_audit import full_audit\n")
    assert [m for m in _imported_modules(absolute, probe) if "profiles.i3f" in m]

    relative = ast.parse("from ..i3f import tools_audit\n")
    assert [m for m in _imported_modules(relative, probe) if "profiles.i3f" in m], (
        "l'import relatif doit être résolu, sinon le garde-fou est contournable"
    )


# ── 2. Aucun vocabulaire, donc aucune copie de texte ──────────────────


def _shipped_texts(tree: ast.Module) -> list[tuple[int, str]]:
    """Textes qui **partent chez l'utilisateur**, docstrings d'outils comprises.

    La distinction est le fond du contrôle. Un commentaire ou une docstring de
    module qui dit « ce profil n'importe rien d'I3F » décrit la frontière : le
    lui interdire reviendrait à interdire de l'expliquer. En revanche la
    docstring d'un ``@mcp.tool`` est envoyée au modèle comme description de
    l'outil, et une constante de texte finit dans une réponse — celles-là
    doivent être propres, sans quoi le référentiel d'un AMO se retrouve dans
    l'interface d'un autre.
    """
    shipped: list[tuple[int, str]] = []
    docstrings_to_skip: set[int] = set()

    module_doc = ast.get_docstring(tree, clean=False)
    if module_doc and tree.body and isinstance(tree.body[0], ast.Expr):
        docstrings_to_skip.add(id(tree.body[0].value))

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
                docstrings_to_skip.add(id(first.value))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings_to_skip
        ):
            shipped.append((node.lineno, node.value))
    return shipped


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_i3f_vocabulary_reaches_the_user(path):
    """Prompt, descriptions d'outils et textes de réponse : aucun terme I3F."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [
        f"{path.name}:{lineno} -> {term!r}"
        for lineno, text in _shipped_texts(tree)
        for term in I3F_VOCABULARY
        if re.search(rf"\b{re.escape(term)}\b", text, re.I)
    ]
    assert not offenders, f"vocabulaire I3F servi à l'utilisateur : {offenders}"


def test_the_vocabulary_guard_covers_prompt_and_tool_docstrings():
    """Non-vacuité, sur les deux surfaces qui comptent.

    Sans ce contrôle, la sélection de textes pourrait n'en retenir aucun et le
    test passerait sur tous les fichiers.
    """
    probe = ast.parse(
        '"""Docstring de module : parler d\'I3F ici est légitime."""\n'
        'MESSAGE = "Consulter le CCH I3F."\n\n'
        "@mcp.tool()\n"
        "def outil():\n"
        '    """Génère le pack AVP."""\n'
        "    return None\n"
    )
    texts = [t for _, t in _shipped_texts(probe)]
    assert any("CCH" in t for t in texts), "une constante de texte doit être vue"
    assert any("AVP" in t for t in texts), "la docstring d'un outil doit être vue"
    assert not any("légitime" in t for t in texts), (
        "la docstring de module explique la frontière — la bannir l'interdirait"
    )

    # Et le profil réel expose bien des textes à contrôler.
    real = ast.parse((PROFILE_DIR / "tools_session.py").read_text(encoding="utf-8"))
    assert len(_shipped_texts(real)) >= 5


def test_the_prompt_shares_no_sentence_with_the_i3f_one():
    """Contrôle de non-copie : deux personas ne doivent pas partager de phrases.

    Le contrôle de vocabulaire ne suffirait pas — un paragraphe de posture
    entier peut être repris sans contenir un seul terme I3F, et serait alors
    une copie invisible.
    """
    from audit_bim.profiles.bim_in_motion.prompts import AMO_BIM_IN_MOTION_PROMPT
    from audit_bim.profiles.i3f.prompts import AMO_BIM_I3F_PROMPT

    def sentences(text: str) -> set[str]:
        parts = re.split(r"[.\n]", text)
        return {" ".join(p.split()) for p in parts if len(p.split()) >= 6}

    shared = sentences(AMO_BIM_IN_MOTION_PROMPT) & sentences(AMO_BIM_I3F_PROMPT)
    assert not shared, f"phrases communes aux deux prompts : {shared}"

    # Non-vacuité : la découpe doit produire des phrases comparables.
    assert len(sentences(AMO_BIM_IN_MOTION_PROMPT)) >= 5


# ── 3. Le profil fonctionne réellement ────────────────────────────────


def test_the_registry_entry_matches_what_is_on_disk():
    """Le registre décrit le profil : il doit décrire l'état réel."""
    from audit_bim.profiles.registry import get_profile

    profile = get_profile("bim_in_motion")
    assert profile.tool_modules == ("audit_bim.profiles.bim_in_motion.tools_session",)
    assert profile.prompt_module == "audit_bim.profiles.bim_in_motion.prompts"
    assert profile.legacy_alias_module is None, "les aliases LEGACY sont une dette d'I3F"

    locations = [s.current_location for s in profile.specializations if s.current_location]
    assert locations, "aucune spécialisation prête n'est déclarée"
    for location in locations:
        assert (REPO / location).exists(), location


def test_the_tools_answer_without_any_i3f_module_loaded():
    """Preuve d'exécution, pas seulement d'enregistrement.

    Un outil peut être exposé et importer I3F au premier appel — l'import
    paresseux est précisément la manière dont la frontière s'est déjà fissurée
    en E4. On appelle donc, et on regarde ``sys.modules`` **après**.
    """
    probe = (
        "import json, sys\n"
        "from audit_bim.mcp.app import register_all\n"
        "register_all()\n"
        "from audit_bim.profiles.bim_in_motion.tools_session import (\n"
        "    set_active_target, verify_active_target, extract_model_snapshot)\n"
        "out = set_active_target(cloud_id='1', project_id='2', model_id='3')\n"
        "outcomes = []\n"
        "for fn, kwargs in ((verify_active_target, {'expected_model_name': 'X'}),\n"
        "                   (extract_model_snapshot, {'use_cache': False})):\n"
        "    try:\n"
        "        fn(**kwargs)\n"
        "        outcomes.append('returned')\n"
        "    except Exception as exc:\n"
        "        outcomes.append(type(exc).__name__)\n"
        "print(json.dumps({\n"
        "    'target': out,\n"
        "    'outcomes': outcomes,\n"
        "    'i3f': sorted(m for m in sys.modules if m.startswith('audit_bim.profiles.i3f')),\n"
        "}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(REPO),
            "AUDIT_BIM_PROFILE": "bim_in_motion",
            # Identifiants factices, délibérément. Sans eux, la construction du
            # client échoue là où aucune authentification n'est configurée (la
            # CI) et réussit là où il y en a une (un poste de dev) — le test
            # mesurerait alors l'environnement plutôt que le code. Pire : avec
            # de vrais identifiants, les deux lectures ci-dessous atteindraient
            # un compte réel.
            "BIMDATA_API_KEY": "cle-factice-de-test",
            # …et une API injoignable : la sonde ne doit atteindre aucun service
            # externe, et son résultat ne doit pas dépendre du réseau du poste
            # qui l'exécute.
            "BIMDATA_BASE_URL": "http://127.0.0.1:9",
        },
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    seen = json.loads(result.stdout.strip().splitlines()[-1])

    # La cible se configure sans réseau : c'est le contrat de `set_active_target`.
    assert seen["target"]["auth"] == "configured"
    assert seen["target"]["model_id"] == "3"
    # Les deux lectures sont bien tentées. Leur issue dépend de la façon dont
    # l'extraction traite une API injoignable — échec, ou résultat dégradé — et
    # ce n'est pas l'objet de ce test. Ce qui compte est qu'aucune des deux, ni
    # en réussissant ni en échouant, n'a chargé le profil I3F.
    assert len(seen["outcomes"]) == 2, seen["outcomes"]
    assert seen["i3f"] == [], f"un appel a chargé le profil I3F : {seen['i3f']}"


def test_missing_target_names_a_tool_of_this_profile():
    """Le message d'erreur ne doit pas renvoyer vers un outil d'un autre profil.

    ``_State.ensure_client()`` nomme ``set_active_model``, qui n'existe pas ici.
    Envoyer un utilisateur vers un outil absent de son serveur est une impasse
    d'autant plus coûteuse qu'elle a l'air d'une instruction valide.
    """
    # Lu par AST, sans importer le module : l'importer déclencherait ses
    # ``@mcp.tool`` sur l'instance partagée du processus de test, et fausserait
    # la surface mesurée par tous les fichiers exécutés ensuite.
    tree = ast.parse((PROFILE_DIR / "tools_session.py").read_text(encoding="utf-8"))
    message = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and getattr(node.targets[0], "id", None) == "_NO_TARGET"
        and isinstance(node.value, ast.Constant)
    )
    assert "set_active_target" in message
    assert "set_active_model" not in message
