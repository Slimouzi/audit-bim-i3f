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
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import anyio
import pytest

from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.app import register_all

GOLDEN = Path(__file__).parent / "golden" / "mcp_surface.json"

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


def _current_surface() -> dict:
    """Surface telle que la produit ``register_all()``.

    C'est ce qu'appelle ``main()`` avant de démarrer : mesurer autre chose
    reviendrait à figer une surface que personne ne sert. Depuis E3-A, le prompt
    du profil y est enregistré explicitement, plus par effet de bord d'import.
    """
    register_all()
    tools = anyio.run(mcp_server.mcp.list_tools)
    prompts = anyio.run(mcp_server.mcp.list_prompts)
    return {
        "tools": {
            t.name: sorted(inspect.signature(t.fn).parameters)
            for t in tools
            if t.name not in LEGACY_ALIASES
        },
        "prompts": sorted(p.name for p in prompts),
    }


def _golden_surface() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_golden_file_exists_and_is_populated():
    surface = _golden_surface()
    assert len(surface["tools"]) == 46
    assert surface["prompts"] == ["amo_bim_i3f"]


def test_tool_names_match_the_reference():
    current, golden = _current_surface(), _golden_surface()
    added = sorted(set(current["tools"]) - set(golden["tools"]))
    removed = sorted(set(golden["tools"]) - set(current["tools"]))
    assert not added, f"outils AJOUTÉS sans mise à jour de la référence : {added}"
    assert not removed, f"outils DISPARUS : {removed}"


def test_every_tool_signature_matches_the_reference():
    """Chaque outil, pas un échantillon."""
    current, golden = _current_surface(), _golden_surface()
    drifted = {
        name: {"référence": golden["tools"][name], "actuel": params}
        for name, params in current["tools"].items()
        if name in golden["tools"] and params != golden["tools"][name]
    }
    assert not drifted, f"signatures modifiées : {drifted}"


def test_prompts_match_the_reference():
    assert _current_surface()["prompts"] == _golden_surface()["prompts"]


def test_whole_surface_is_byte_identical():
    """Comparaison globale — la même que celle menée à la main contre master."""
    assert _current_surface() == _golden_surface()


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
