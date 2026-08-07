"""Surface MCP figée — les 46 outils, leurs paramètres, et le prompt.

Un échantillon ne suffit pas. Les contrôles voisins vérifient le nombre
canonique, le prompt et quelques outils clés ; une dérive sur un outil non
échantillonné passerait la CI sans bruit. Ce test compare la **totalité** de la
surface à une référence versionnée.

C'est le garde-fou de merge des lots de déplacement (E2, E3) : il rend
permanent ce qui n'était jusqu'ici qu'une comparaison manuelle contre `master`.

**Mise à jour de la référence.** Elle ne se régénère pas par confort : toute
modification de `mcp_surface.json` est un changement d'API MCP, à annoncer et à
justifier dans la PR qui la porte. Un outil ajouté, renommé, ou dont un
paramètre change, se voit ici en premier.

**La mesure se fait dans un interpréteur neuf**, via `register_all()` seul. Une
version antérieure importait `server` au niveau module : comme `server` importe
les modules d'outils pour ses ré-exports de compat, les 46 décorateurs
s'exécutaient AVANT l'appel. Le test annonçait mesurer `register_all()` et
mesurait en fait un effet de bord d'import — exactement ce que E3-A voulait
éliminer. Un sous-processus est le seul moyen de garantir l'ordre.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

#: Une référence **par profil**. Depuis E5, la surface MCP dépend du profil
#: actif : la figer pour I3F seul laisserait un second profil dériver librement.
GOLDEN_BY_PROFILE = {
    "i3f": Path(__file__).parent / "golden" / "mcp_surface.json",
    "bim_in_motion": Path(__file__).parent / "golden" / "mcp_surface_bim_in_motion.json",
    "domofrance": Path(__file__).parent / "golden" / "mcp_surface_domofrance.json",
}
PROFILES = sorted(GOLDEN_BY_PROFILE)

#: Nom historique conservé : le fichier d'I3F ne doit pas bouger, y compris de
#: chemin — c'est la référence que tous les lots précédents ont vérifiée.
GOLDEN = GOLDEN_BY_PROFILE["i3f"]

#: Aliases LEGACY, opt-in par variable d'environnement. Un autre test de la
#: suite les active sur le registre partagé : la surface canonique s'entend
#: donc hors aliases, sinon ce test dépendrait de l'ordre d'exécution.
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


_DUMP_SCRIPT = textwrap.dedent(
    """
    import anyio, inspect, json, sys
    from audit_bim.mcp.app import register_all

    LEGACY = set(json.loads(sys.argv[1]))
    mcp = register_all()
    tools = anyio.run(mcp.list_tools)
    prompts = anyio.run(mcp.list_prompts)
    print(json.dumps({
        "tools": {
            t.name: sorted(inspect.signature(t.fn).parameters)
            for t in tools if t.name not in LEGACY
        },
        "prompts": sorted(p.name for p in prompts),
    }, sort_keys=True))
    """
)


def _current_surface(profile: str = "i3f") -> dict:
    """Surface produite par ``register_all()``, dans un interpréteur NEUF.

    C'est ce qu'appelle ``main()`` avant de démarrer. Le sous-processus n'est
    pas un excès de prudence : dans le processus de test, d'autres modules ont
    déjà importé ``server`` — donc déclenché les 46 décorateurs — et la mesure
    ne dirait rien de ce que ``register_all()`` produit réellement.
    """
    repo = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-c", _DUMP_SCRIPT, json.dumps(sorted(LEGACY_ALIASES))],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo), "AUDIT_BIM_PROFILE": profile},
    )
    assert proc.returncode == 0, f"dump de surface échoué :\n{proc.stderr}"
    return json.loads(proc.stdout)


def _golden_surface(profile: str = "i3f") -> dict:
    return json.loads(GOLDEN_BY_PROFILE[profile].read_text(encoding="utf-8"))


def test_golden_file_exists_and_is_populated():
    surface = _golden_surface("i3f")
    assert len(surface["tools"]) == 46
    assert surface["prompts"] == ["amo_bim_i3f"]


def test_the_third_party_profile_surface_is_explicit():
    """La surface de BIM in Motion est petite : elle doit être énumérée, pas comptée.

    Un simple cardinal laisserait un outil se faire remplacer par un autre sans
    bruit. À cette taille, l'inventaire exact est lisible — et c'est justement
    quand une surface est petite qu'une dérive y passe inaperçue.
    """
    surface = _golden_surface("bim_in_motion")
    assert sorted(surface["tools"]) == [
        "analyze_mrn_model_coverage",
        "check_bimdata_access",
        "download_model_ifc",
        "extract_model_snapshot",
        "list_mcp_profiles",
        "parse_bimdata_target",
        "set_active_target",
        "verify_active_model",
    ]
    assert surface["prompts"] == ["amo_bim_in_motion"]


def test_the_domofrance_profile_surface_is_explicit():
    """Même exigence pour le troisième profil, et pour la même raison.

    Les sept premiers outils sont ceux du socle et le transverse : seul
    `analyze_domofrance_model_coverage` distingue cette surface de celle du
    profil frère. Compter huit ne le verrait pas.
    """
    surface = _golden_surface("domofrance")
    assert sorted(surface["tools"]) == [
        "analyze_domofrance_model_coverage",
        "check_bimdata_access",
        "download_model_ifc",
        "extract_model_snapshot",
        "list_mcp_profiles",
        "parse_bimdata_target",
        "set_active_target",
        "verify_active_model",
    ]
    assert surface["prompts"] == ["amo_bim_domofrance"]


def test_the_three_profiles_share_only_the_common_base():
    """Ce que chaque profil ajoute lui est propre — vérifié, pas supposé.

    Sans ce contrôle, deux profils pourraient converger outil par outil jusqu'à
    devenir indiscernables, chacun restant conforme à son propre golden.
    """
    surfaces = {p: set(_golden_surface(p)["tools"]) for p in PROFILES}
    commun = set.intersection(*surfaces.values())
    assert commun == {
        "check_bimdata_access",
        "download_model_ifc",
        "extract_model_snapshot",
        "list_mcp_profiles",
        "parse_bimdata_target",
        "verify_active_model",
    }, "le socle commun aux trois profils a changé"

    propre = {p: surfaces[p] - commun for p in PROFILES}
    assert propre["bim_in_motion"] & propre["domofrance"] == {"set_active_target"}, (
        "hors socle, les deux profils tiers ne doivent partager que leur outil de cible"
    )
    assert "analyze_mrn_model_coverage" not in surfaces["domofrance"]
    assert "analyze_domofrance_model_coverage" not in surfaces["bim_in_motion"]
    assert "analyze_domofrance_model_coverage" not in surfaces["i3f"]


def test_the_two_profiles_do_not_expose_the_same_surface():
    """Sentinelle : deux références identiques rendraient la comparaison vaine."""
    i3f, other = _golden_surface("i3f"), _golden_surface("bim_in_motion")
    assert i3f != other
    assert not (set(i3f["prompts"]) & set(other["prompts"]))


@pytest.mark.parametrize("profile", PROFILES)
def test_tool_names_match_the_reference(profile):
    current, golden = _current_surface(profile), _golden_surface(profile)
    added = sorted(set(current["tools"]) - set(golden["tools"]))
    removed = sorted(set(golden["tools"]) - set(current["tools"]))
    assert not added, f"outils AJOUTÉS sans mise à jour de la référence : {added}"
    assert not removed, f"outils DISPARUS : {removed}"


@pytest.mark.parametrize("profile", PROFILES)
def test_every_tool_signature_matches_the_reference(profile):
    """Chaque outil, pas un échantillon."""
    current, golden = _current_surface(profile), _golden_surface(profile)
    drifted = {
        name: {"référence": golden["tools"][name], "actuel": params}
        for name, params in current["tools"].items()
        if name in golden["tools"] and params != golden["tools"][name]
    }
    assert not drifted, f"signatures modifiées : {drifted}"


@pytest.mark.parametrize("profile", PROFILES)
def test_prompts_match_the_reference(profile):
    assert _current_surface(profile)["prompts"] == _golden_surface(profile)["prompts"]


@pytest.mark.parametrize("profile", PROFILES)
def test_whole_surface_is_byte_identical(profile):
    """Comparaison globale — la même que celle menée à la main contre master."""
    assert _current_surface(profile) == _golden_surface(profile)


def test_the_comparison_is_not_vacuous():
    """Une dérive sur un outil non échantillonné doit être détectée.

    C'est la raison d'être de ce fichier : les contrôles voisins ne regardaient
    que quelques outils, donc une signature modifiée ailleurs serait passée.
    """
    golden = _golden_surface()
    tampered = json.loads(json.dumps(golden))
    victim = sorted(tampered["tools"])[20]  # ni le premier, ni un outil clé
    tampered["tools"][victim] = [*tampered["tools"][victim], "parametre_surnumeraire"]
    assert tampered != golden
    assert tampered["tools"][victim] != golden["tools"][victim]


@pytest.mark.parametrize("name", ["set_active_model", "generate_avp_i3f_pack"])
def test_key_tools_are_covered_by_the_reference(name):
    assert name in _golden_surface()["tools"]
