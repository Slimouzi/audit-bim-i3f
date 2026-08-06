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

from audit_bim.profiles.active import ACTIVE_PROFILE_ENV

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
    assert profile.tool_modules == (
        "audit_bim.tools_shared.session",
        "audit_bim.profiles.bim_in_motion.tools_session",
        "audit_bim.profiles.bim_in_motion.tools_mrn",
    )
    assert profile.target_tool_name == "set_active_target"
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
        "from audit_bim.profiles.bim_in_motion.tools_session import set_active_target\n"
        "from audit_bim.tools_shared.session import (\n"
        "    verify_active_model, extract_model_snapshot)\n"
        "out = set_active_target(cloud_id='1', project_id='2', model_id='3')\n"
        "outcomes = []\n"
        "for fn, kwargs in ((verify_active_model, {'expected_model_name': 'X'}),\n"
        "                   (extract_model_snapshot, {'use_cache': False})):\n"
        "    try:\n"
        "        res = fn(**kwargs)\n"
        "        outcomes.append(res)\n"
        "    except Exception as exc:\n"
        "        outcomes.append({'error': type(exc).__name__})\n"
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

    # Une lecture qui n'aboutit pas doit se voir dans la réponse. Sans cela, les
    # deux outils renvoient `model_name: null` et des compteurs à zéro —
    # présentés comme un résultat, alors que rien n'a été lu. C'est la panne la
    # plus coûteuse d'un outil de contrôle : elle a l'air d'une mesure.
    for outcome in seen["outcomes"]:
        assert "error" not in outcome, outcome
        assert outcome["snapshot_health"] != "ok", outcome
        assert outcome["snapshot_warning"], outcome
        assert outcome["n_extraction_errors"] >= 1, outcome
        assert len(outcome["extraction_errors"]) == outcome["n_extraction_errors"]

    # Non-vacuité : `ok=False` seul serait indiscernable d'un écart de nom.
    identity = seen["outcomes"][0]
    assert identity["ok"] is False and identity["model_name"] is None
    assert identity["snapshot_health"] in {"empty_model", "partial", "empty_elements"}


@pytest.mark.parametrize(
    ("profile_id", "expected"),
    [("bim_in_motion", "set_active_target"), ("i3f", "set_active_model")],
)
def test_missing_target_names_a_tool_of_the_active_profile(profile_id, expected):
    """Le message d'erreur ne doit pas renvoyer vers un outil d'un autre profil.

    ``_State.ensure_client()`` écrivait ``set_active_model`` en dur. Tant que ce
    texte vivait dans le profil I3F, il ne pouvait viser que le bon outil. Servi
    depuis le socle partagé (E7), il renvoyait les utilisateurs de BIM in Motion
    vers un outil que leur serveur n'expose pas — une instruction qui a l'air
    valide et ne mène nulle part. Le nom vient désormais du profil actif.

    Mesuré en sous-processus : la résolution dépend de l'environnement, et le
    profil de l'interpréteur de test n'est pas celui qu'on veut éprouver.
    """
    probe = (
        "from audit_bim.mcp.session import _Session\n"
        "try:\n"
        "    _Session().ensure_client()\n"
        "except RuntimeError as exc:\n"
        "    print(str(exc))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PATH": "/usr/bin:/bin", "HOME": str(REPO), ACTIVE_PROFILE_ENV: profile_id},
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    message = result.stdout.strip()

    assert expected in message, message
    other = "set_active_model" if expected == "set_active_target" else "set_active_target"
    assert other not in message, message


def _in_profile_process(body: str) -> dict:
    """Exécute ``body`` dans un interpréteur au profil BIM in Motion actif.

    Les appels passent par un sous-processus parce qu'importer le module
    d'outils ici déclencherait ses ``@mcp.tool`` sur l'instance MCP partagée du
    processus de test, faussant la surface mesurée par les fichiers suivants.
    """
    probe = (
        "import json\n"
        "from audit_bim.profiles.bim_in_motion.tools_session import set_active_target\n"
        "def attempt(**kw):\n"
        "    try:\n"
        "        return {'ok': True, 'value': set_active_target(**kw)}\n"
        "    except Exception as exc:\n"
        "        return {'ok': False, 'type': type(exc).__name__, 'message': str(exc)}\n"
        f"{body}\n"
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
            "BIMDATA_API_KEY": "cle-factice-de-test",
            "BIMDATA_BASE_URL": "http://127.0.0.1:9",
        },
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("field", ["cloud_id", "project_id", "model_id"])
def test_a_url_in_any_id_field_is_refused_without_naming_an_absent_tool(field):
    """Le refus doit nommer une action **disponible dans ce profil**.

    ``resolve_bimdata_target`` renvoyait vers ``parse_bimdata_target``, un outil
    d'I3F que ce serveur n'expose pas : une instruction qui a l'air valide et ne
    mène nulle part. Et son contrôle ne portait que sur ``model_id`` — une URL
    passée en ``cloud_id`` produisait une cible invalide annoncée « configured ».
    """
    url = "https://platform.bimdata.io/spaces/1/projects/2/viewer/3"
    out = _in_profile_process(f"print(json.dumps(attempt({field}={url!r})))")

    assert out["ok"] is False, f"{field} a accepté une URL : {out}"
    assert "bimdata_url" in out["message"]
    assert "parse_bimdata_target" not in out["message"]


def test_a_non_numeric_identifier_is_refused():
    """Un identifiant fantaisiste ne doit pas produire une cible « configurée »."""
    out = _in_profile_process("print(json.dumps(attempt(cloud_id='mon-espace')))")
    assert out["ok"] is False
    assert "numérique" in out["message"]


def test_the_viewer_url_is_accepted_by_this_tool():
    """Le profil est autonome : l'URL se traite ici, sans outil supplémentaire."""
    url = "https://platform.bimdata.io/spaces/11/projects/22/viewer/33"
    out = _in_profile_process(f"print(json.dumps(attempt(bimdata_url={url!r})))")

    assert out["ok"] is True, out
    assert (out["value"]["cloud_id"], out["value"]["project_id"], out["value"]["model_id"]) == (
        "11",
        "22",
        "33",
    )


def test_mixing_url_and_explicit_ids_is_refused():
    """Deux cibles possibles dans un seul appel : le refus vaut mieux qu'un choix."""
    url = "https://platform.bimdata.io/spaces/11/projects/22/viewer/33"
    out = _in_profile_process(f"print(json.dumps(attempt(bimdata_url={url!r}, cloud_id='9')))")
    assert out["ok"] is False
    assert "ambiguë" in out["message"]


# ── 5. Aucune description ne cite un outil absent du serveur ──────────

GOLDEN_DIR = REPO / "tests" / "unit" / "golden"


def _tool_universe() -> set[str]:
    """Tous les noms d'outils connus du dépôt, tous profils confondus."""
    names: set[str] = set()
    for path in GOLDEN_DIR.glob("mcp_surface*.json"):
        names |= set(json.loads(path.read_text(encoding="utf-8"))["tools"])
    return names


def test_no_tool_description_names_a_tool_absent_from_the_active_profile():
    """Les descriptions MCP sont des instructions, et sont lues comme telles.

    Le socle partagé nommait ``set_active_model`` dans trois docstrings. Sous
    BIM in Motion, le modèle recevait donc la consigne d'appeler un outil que
    son serveur n'expose pas — plausible, et sans issue. Le contrôle ne vise pas
    trois noms connus : il rejette **tout** nom d'outil du dépôt qui ne serait
    pas dans la surface du profil actif, pour que la prochaine fuite échoue
    aussi.
    """
    probe = (
        "import anyio, json\n"
        "from audit_bim.mcp.app import register_all\n"
        "mcp = register_all()\n"
        "tools = anyio.run(mcp.list_tools)\n"
        "print(json.dumps({t.name: (t.description or '') for t in tools}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PATH": "/usr/bin:/bin", "HOME": str(REPO), ACTIVE_PROFILE_ENV: "bim_in_motion"},
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    descriptions = json.loads(result.stdout.strip().splitlines()[-1])

    universe = _tool_universe()
    assert len(universe) > len(descriptions), "prémisse : d'autres outils existent ailleurs"
    forbidden = universe - set(descriptions)
    assert {"set_active_model", "full_audit", "generate_avp_i3f_pack"} <= forbidden

    offenders = [
        f"{tool} cite {name}"
        for tool, text in descriptions.items()
        for name in forbidden
        if re.search(rf"\b{re.escape(name)}\b", text)
    ]
    assert not offenders, f"descriptions renvoyant vers un outil absent : {offenders}"


def test_the_mismatch_message_names_the_targeting_tool_of_the_active_profile():
    """Le conseil donné après une maquette inattendue doit être applicable.

    Le message disait « set_active_model + verify_active_model ». Sous BIM in
    Motion, la moitié de cette consigne désigne un outil inexistant — et c'est
    le moment où l'auditeur a le plus besoin d'une instruction juste, puisqu'il
    vient d'apprendre qu'il travaillait peut-être sur la mauvaise maquette.
    """
    probe = (
        "from unittest.mock import patch\n"
        "from audit_bim.extraction.model_data import ModelSnapshot\n"
        "from audit_bim.mcp.session import _State\n"
        "from audit_bim.tools_shared import session as shared\n"
        "_State.client = object()\n"
        "snap = ModelSnapshot(model={'name': 'AUTRE MAQUETTE', 'id': 7}, project={})\n"
        "with patch.object(shared, 'extract_snapshot', return_value=snap):\n"
        "    out = shared.verify_active_model('ATTENDU', refresh_snapshot=True, use_cache=False)\n"
        "print(out['message'])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PATH": "/usr/bin:/bin", "HOME": str(REPO), ACTIVE_PROFILE_ENV: "bim_in_motion"},
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2500:]
    message = result.stdout.strip()

    assert "set_active_target" in message, message
    assert "set_active_model" not in message, message
