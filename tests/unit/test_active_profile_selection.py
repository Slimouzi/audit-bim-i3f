"""Profil actif configurable — E4.

Le serveur enregistre les outils du profil déclaré par ``AUDIT_BIM_PROFILE``,
I3F par défaut. Trois propriétés sont vérifiées ici, dans cet ordre
d'importance :

1. le défaut ne change **rien** (c'est le golden qui l'établit, pas ce fichier) ;
2. choisir un autre profil **empêche l'import** des modules d'I3F — pas
   seulement leur enregistrement ;
3. un identifiant inconnu **arrête** le serveur au lieu de se rabattre sur I3F.

La propriété (2) est la seule qui prouve que la sélection sert à quelque chose.
Compter les outils ne suffirait pas : un module importé mais non enregistré
laisserait quand même le référentiel d'un client dans le processus d'un autre.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from audit_bim.profiles.active import (
    ACTIVE_PROFILE_ENV,
    UnknownProfileError,
    active_profile_id,
    resolve_active_profile,
)
from audit_bim.profiles.registry import DEFAULT_PROFILE_ID, get_profile, list_profiles

REPO = Path(__file__).resolve().parents[2]

#: Inventaire renvoyé par un interpréteur neuf : ce qui est enregistré, et ce
#: qui a été importé. Le second point est l'objet du test.
_PROBE = """
import json
from audit_bim.mcp.app import register_all, registered_profile_id
import anyio, sys

mcp = register_all()
print(json.dumps({
    "profile": registered_profile_id(),
    "tools": sorted(t.name for t in anyio.run(mcp.list_tools)),
    "prompts": sorted(p.name for p in anyio.run(mcp.list_prompts)),
    "i3f_modules": sorted(m for m in sys.modules if m.startswith("audit_bim.profiles.i3f")),
}))
"""


def _probe(profile_id: str | None = None, prelude: str = "pass") -> dict:
    """Lance ``register_all()`` dans un interpréteur **frais**.

    Indispensable : l'enregistrement est idempotent par processus, et
    ``sys.modules`` garde la trace de tout import antérieur. Mesurer dans
    l'interpréteur de test renverrait l'état laissé par un autre fichier.
    """
    env = {"PATH": "/usr/bin:/bin", "HOME": str(REPO)}
    if profile_id is not None:
        env[ACTIVE_PROFILE_ENV] = profile_id
    result = subprocess.run(
        [sys.executable, "-c", f"{prelude}\n{_PROBE}"],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


# ── 1. Le défaut ne change rien ───────────────────────────────────────


def test_default_profile_is_i3f_without_any_variable(monkeypatch):
    monkeypatch.delenv(ACTIVE_PROFILE_ENV, raising=False)
    assert active_profile_id() == DEFAULT_PROFILE_ID
    assert resolve_active_profile().id == "i3f"


def test_the_variable_is_read_lazily(monkeypatch):
    """Une valeur posée **après** l'import du module doit être vue.

    ``RuntimeConfig`` puis ``SessionStore`` ont tous deux dû corriger ce défaut
    à leur niveau ; le corriger d'un seul côté ne corrige rien, donc on le
    vérifie ici aussi.
    """
    monkeypatch.delenv(ACTIVE_PROFILE_ENV, raising=False)
    assert active_profile_id() == "i3f"
    monkeypatch.setenv(ACTIVE_PROFILE_ENV, "bim_in_motion")
    assert active_profile_id() == "bim_in_motion"


@pytest.mark.parametrize("written", ["BIM-IN-MOTION", " bim_in_motion ", "Bim_In_Motion"])
def test_the_identifier_is_normalised(monkeypatch, written):
    """Tiret, casse et espaces ne doivent pas provoquer un arrêt de démarrage."""
    monkeypatch.setenv(ACTIVE_PROFILE_ENV, written)
    assert resolve_active_profile().id == "bim_in_motion"


def test_explicit_default_matches_the_implicit_one():
    """``AUDIT_BIM_PROFILE=i3f`` produit exactement le serveur historique."""
    implicit, explicit = _probe(), _probe("i3f")
    assert implicit == explicit
    assert implicit["profile"] == "i3f"
    assert implicit["prompts"] == ["amo_bim_i3f"]
    assert len(implicit["tools"]) == 46


# ── 2. Choisir un autre profil empêche l'import d'I3F ──────────────────


def test_another_profile_neither_registers_nor_imports_i3f():
    """La propriété centrale d'E4.

    Avant ce lot, ``register_all()`` importait ``server``, qui ré-exporte tout
    le profil I3F au niveau module : les 45 outils se seraient enregistrés quel
    que soit le profil demandé. La sélection aurait été un paramètre sans effet.
    """
    other, i3f = _probe("bim_in_motion"), _probe("i3f")

    # Non-vacuité d'abord : sans cette ligne, une sonde qui ne mesurerait rien
    # afficherait une liste vide sous les deux profils et le test passerait.
    assert i3f["i3f_modules"], "la sonde ne mesure pas les imports — le reste ne prouve rien"

    assert other["profile"] == "bim_in_motion"
    assert other["prompts"] == ["amo_bim_in_motion"]
    assert other["i3f_modules"] == [], f"le profil I3F a été importé : {other['i3f_modules']}"
    assert other["tools"] == THIRD_PARTY_TOOLS

    # Recouvrement de noms **assumé** : `extract_model_snapshot` désigne le même
    # concept dans les deux profils, avec deux implémentations indépendantes.
    # C'est un signal pour l'inventaire du socle partagé, pas une fuite — les
    # deux profils ne coexistent jamais dans un processus. Ce qui serait une
    # fuite, ce sont les outils porteurs du référentiel I3F.
    # Depuis E7, le recouvrement n'est plus un doublon mais un **partage** : les
    # cinq outils du socle sont les mêmes objets, déclarés une seule fois. Seul
    # `set_active_target` reste propre au profil tiers, son équivalent I3F
    # portant une phase BIM qui n'appartient pas au socle.
    shared_names = set(other["tools"]) & set(i3f["tools"])
    assert shared_names == {
        "list_mcp_profiles",
        "parse_bimdata_target",
        "check_bimdata_access",
        "verify_active_model",
        "extract_model_snapshot",
        "download_model_ifc",
    }, shared_names
    assert "full_audit" not in other["tools"]
    assert "generate_avp_i3f_pack" not in other["tools"]


#: Ce qu'un appelant peut charger **avant** ``register_all()``. La sélection de
#: profil doit tenir quel que soit l'ordre — sinon elle n'est pas une garantie,
#: seulement l'espoir que personne n'importe le mauvais module en premier.
#: Surface attendue du profil tiers depuis E7 : son outil de cible, les cinq
#: outils du socle partagé, et le transverse du serveur.
THIRD_PARTY_TOOLS = [
    "check_bimdata_access",
    "download_model_ifc",
    "extract_model_snapshot",
    "list_mcp_profiles",
    "parse_bimdata_target",
    "set_active_target",
    "verify_active_model",
]

PRELUDES = [
    "pass",
    "import audit_bim.mcp.server",
    "from audit_bim.mcp import server",
    "from audit_bim.mcp import main",
    "import audit_bim.mcp",
    "from audit_bim.profiles.registry import list_profiles; list_profiles()",
]


@pytest.mark.parametrize("prelude", PRELUDES)
def test_no_import_order_can_smuggle_the_i3f_profile_in(prelude):
    """Le défaut réel corrigé après revue d'E4.

    ``audit_bim/mcp/__init__`` exposait ``main`` depuis ``server``, et
    ``server`` importait les modules I3F au niveau module pour ses ré-exports.
    Un simple ``import audit_bim.mcp.server`` enregistrait donc les 45 outils
    I3F **avant** que ``register_all()`` n'ait lu le profil : le profil actif
    était correctement rapporté, et la surface était quand même celle d'I3F.

    Le chemin nominal était sain, ce qui est exactement pourquoi il fallait
    tester les autres.
    """
    seen = _probe("bim_in_motion", prelude=prelude)
    assert seen["tools"] == THIRD_PARTY_TOOLS, f"prélude {prelude!r} : {seen['tools']}"
    assert seen["i3f_modules"] == [], f"prélude {prelude!r} a importé {seen['i3f_modules']}"


def test_the_prelude_probe_is_not_vacuous():
    """Les mêmes préludes, sous I3F, doivent bien charger le profil."""
    for prelude in PRELUDES:
        seen = _probe("i3f", prelude=prelude)
        assert len(seen["tools"]) == 46, f"prélude {prelude!r} : {len(seen['tools'])} outils"
        assert seen["i3f_modules"], f"prélude {prelude!r} n'a rien chargé"


def test_compat_reexports_refuse_to_serve_another_profile():
    """Sous un autre profil, ``server.<tool>`` n'existe pas.

    Servir le nom importerait le profil I3F dans le processus d'un autre AMO et
    y enregistrerait ses outils. L'``AttributeError`` est le comportement
    correct : le ré-export est une compat pour I3F, pas une API universelle.
    """
    env = {"PATH": "/usr/bin:/bin", "HOME": str(REPO), ACTIVE_PROFILE_ENV: "bim_in_motion"}
    probe = (
        "import sys\n"
        "from audit_bim.mcp import server\n"
        "try:\n"
        "    server.full_audit\n"
        "except AttributeError as exc:\n"
        "    assert 'I3F' in str(exc), str(exc)\n"
        "else:\n"
        "    raise SystemExit('le ré-export a servi un outil I3F sous un autre profil')\n"
        "assert not [m for m in sys.modules if m.startswith('audit_bim.profiles.i3f')]\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr[-2000:]


def test_the_server_keeps_its_own_transverse_tools():
    """La surface tierce = ses propres outils + les transverses du serveur.

    ``list_mcp_profiles`` est le seul outil que le serveur possède en propre ;
    les trois autres appartiennent au profil BIM in Motion (E5).
    """
    tools = _probe("bim_in_motion")["tools"]
    assert tools == THIRD_PARTY_TOOLS
    assert "list_mcp_profiles" in tools


# ── 3. Un identifiant inconnu arrête le serveur ────────────────────────


def test_an_unknown_identifier_raises_instead_of_falling_back(monkeypatch):
    """Le repli silencieux sur I3F est le comportement à ne pas avoir.

    ``AUDIT_BIM_PROFILE=bim-in-moton`` doit échouer bruyamment. Sinon le
    serveur démarre, répond, et imprime « CCH BIM I3F » dans le rapport d'un
    autre AMO — sans qu'aucun test ni aucun log ne le signale.
    """
    monkeypatch.setenv(ACTIVE_PROFILE_ENV, "bim-in-moton")
    with pytest.raises(UnknownProfileError) as excinfo:
        resolve_active_profile()

    message = str(excinfo.value)
    assert "bim-in-moton" in message, "le message doit citer la valeur fautive"
    assert "i3f" in message, "le message doit lister les profils connus"


def test_an_unknown_identifier_stops_the_server_process():
    """Et l'arrêt est effectif au démarrage, pas seulement dans l'unité."""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(REPO), ACTIVE_PROFILE_ENV: "nexiste_pas"}
    result = subprocess.run(
        [sys.executable, "-c", "from audit_bim.mcp.app import register_all; register_all()"],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        timeout=180,
    )
    assert result.returncode != 0
    assert "nexiste_pas" in result.stderr


# ── 4. Une déclaration fausse ne peut pas passer inaperçue ─────────────


def test_every_declared_tool_module_exists_and_declares_tools():
    """Un chemin erroné enregistrerait zéro outil **sans erreur**.

    C'est le mode de défaillance propre aux imports par chaîne : le profil
    paraît complet, le serveur démarre, et la surface est vide. On vérifie donc
    que chaque module déclaré est importable et porte au moins un ``@mcp.tool``.

    L'import se fait en **sous-processus**. Le faire ici chargerait les modules
    d'outils de *tous* les profils dans l'interpréteur de test, donc
    déclencherait leurs décorateurs sur l'instance MCP partagée : les fichiers
    exécutés ensuite mesureraient une surface gonflée par ce contrôle. Un test
    ne doit pas modifier ce qu'il observe.
    """
    declared = [(p.id, path) for p in list_profiles() for path in p.tool_modules]
    assert declared, "aucun profil ne déclare de module d'outils"

    script = (
        "import importlib, json, sys\n"
        "paths = json.loads(sys.argv[1])\n"
        "failed = []\n"
        "for path in paths:\n"
        "    try:\n"
        "        importlib.import_module(path)\n"
        "    except Exception as exc:\n"
        "        failed.append(f'{path}: {type(exc).__name__}')\n"
        "print(json.dumps(failed))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps([path for _, path in declared])],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PATH": "/usr/bin:/bin", "HOME": str(REPO)},
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []

    for profile_id, path in declared:
        source = REPO.joinpath(*path.split(".")).with_suffix(".py")
        assert source.exists(), f"{profile_id} déclare {path}, absent du disque"
        assert "@mcp.tool" in source.read_text(encoding="utf-8"), f"{path} ne déclare aucun outil"

    for profile in list_profiles():
        if profile.prompt_module:
            module = REPO.joinpath(*profile.prompt_module.split(".")).with_suffix(".py")
            assert "def register_prompts" in module.read_text(encoding="utf-8")


def test_a_third_party_profile_declares_no_i3f_module():
    """Le profil tiers ne doit hériter d'aucun module client par mégarde."""
    profile = get_profile("bim_in_motion")
    declared = (*profile.tool_modules, profile.prompt_module, profile.legacy_alias_module)
    assert not [p for p in declared if p and "i3f" in p]


def test_the_module_guard_is_not_vacuous():
    """Le contrôle ci-dessus doit savoir reconnaître un chemin faux."""
    ghost = REPO.joinpath(*"audit_bim.profiles.i3f.tools_qui_nexistent_pas".split(".")).with_suffix(
        ".py"
    )
    assert not ghost.exists()
