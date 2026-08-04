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
from importlib import import_module
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


def _probe(profile_id: str | None = None) -> dict:
    """Lance ``register_all()`` dans un interpréteur **frais**.

    Indispensable : l'enregistrement est idempotent par processus, et
    ``sys.modules`` garde la trace de tout import antérieur. Mesurer dans
    l'interpréteur de test renverrait l'état laissé par un autre fichier.
    """
    env = {"PATH": "/usr/bin:/bin", "HOME": str(REPO)}
    if profile_id is not None:
        env[ACTIVE_PROFILE_ENV] = profile_id
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
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
    assert other["prompts"] == []
    assert other["i3f_modules"] == [], f"le profil I3F a été importé : {other['i3f_modules']}"
    assert not (set(other["tools"]) & (set(i3f["tools"]) - {"list_mcp_profiles"})), (
        "des outils I3F sont exposés au profil tiers"
    )


def test_the_server_keeps_its_own_transverse_tools():
    """Ce qui reste sous un profil vide appartient au serveur, pas à un client."""
    assert _probe("bim_in_motion")["tools"] == ["list_mcp_profiles"]


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
    """
    for profile in list_profiles():
        for path in profile.tool_modules:
            module = import_module(path)
            source = Path(module.__file__).read_text(encoding="utf-8")
            assert "@mcp.tool" in source, f"{path} ne déclare aucun outil"
        if profile.prompt_module:
            assert callable(import_module(profile.prompt_module).register_prompts)


def test_a_third_party_profile_declares_no_i3f_module():
    """Le profil tiers ne doit hériter d'aucun module client par mégarde."""
    profile = get_profile("bim_in_motion")
    declared = (*profile.tool_modules, profile.prompt_module, profile.legacy_alias_module)
    assert not [p for p in declared if p and "i3f" in p]


def test_the_module_guard_is_not_vacuous():
    """Le contrôle ci-dessus doit savoir reconnaître un chemin faux."""
    with pytest.raises(ModuleNotFoundError):
        import_module("audit_bim.profiles.i3f.tools_qui_nexistent_pas")
