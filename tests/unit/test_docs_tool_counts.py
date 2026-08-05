"""Les décomptes d'outils cités dans les docs actives doivent être vrais.

Ces documents sont lus par des humains **et recopiés par des agents**. Un
compteur périmé s'y propage sans bruit : rien ne casse, et le mauvais chiffre
circule. Trois d'entre eux annonçaient encore 45/53 après l'ajout de
``list_mcp_profiles``, et un quatrième décrivait un mécanisme de ré-exports
supprimé depuis.

Le contrôle mesure la surface réelle — profil par défaut, puis aliases LEGACY
activés — et refuse tout document actif qui annoncerait autre chose.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"

#: Documents d'usage, par opposition aux notes de cadrage et aux audits
#: historiques : ceux-ci décrivent le produit **tel qu'il est**, et c'est là que
#: le lecteur ira chercher un chiffre.
ACTIVE_DOCS = (
    "mcp_tools.md",
    "workflow_amo_bim.md",
    "migration_prepare_apply.md",
    "claude_desktop_local.md",
)


def _surface(legacy: bool) -> int:
    """Nombre d'outils exposés, mesuré dans un interpréteur neuf."""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(REPO)}
    if legacy:
        env["AUDIT_BIM_ENABLE_LEGACY_ALIASES"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import anyio, json\n"
            "from audit_bim.mcp.app import register_all\n"
            "print(json.dumps(len(anyio.run(register_all().list_tools))))\n",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def counts() -> tuple[int, int]:
    canonical, with_legacy = _surface(False), _surface(True)
    assert with_legacy > canonical, "prémisse : les aliases LEGACY ajoutent des outils"
    return canonical, with_legacy


def test_the_measured_surface_is_the_one_documented(counts):
    """Les deux chiffres de référence, mesurés et non recopiés."""
    assert counts == (46, 54)


@pytest.mark.parametrize("name", ACTIVE_DOCS)
def test_no_active_doc_quotes_a_stale_tool_count(name, counts):
    """Aucun document actif ne doit annoncer un décompte périmé.

    On ne traque pas les nombres isolés — ``"succeeded": 45`` est une sortie
    d'exemple, pas un décompte d'outils, et l'interdire ferait rougir le test
    sur des données de démonstration. Le contrôle vise les formulations qui
    *annoncent une surface*.
    """
    canonical, with_legacy = counts
    text = " ".join((DOCS / name).read_text(encoding="utf-8").split())

    quoted = re.findall(r"(\d+)\s+(?:tools?|outils?)\s+(?:canoniques?\s+)?(?:par défaut|MCP)", text)
    offenders = [n for n in quoted if int(n) != canonical]
    assert not offenders, f"{name} annonce {offenders} outils au lieu de {canonical}"

    legacy_quoted = re.findall(r"(\d+)\s+avec (?:les )?aliases LEGACY", text)
    stale = [n for n in legacy_quoted if int(n) != with_legacy]
    assert not stale, f"{name} annonce {stale} avec aliases au lieu de {with_legacy}"


def test_the_count_guard_is_not_vacuous(counts):
    """Le contrôle doit reconnaître les deux formulations qu'il surveille."""
    canonical, with_legacy = counts
    sample = f"référence complète ({canonical - 1} tools par défaut, {with_legacy - 1} avec les aliases LEGACY)"

    quoted = re.findall(
        r"(\d+)\s+(?:tools?|outils?)\s+(?:canoniques?\s+)?(?:par défaut|MCP)", sample
    )
    assert [n for n in quoted if int(n) != canonical], "le décompte par défaut doit être vu"

    legacy = re.findall(r"(\d+)\s+avec (?:les )?aliases LEGACY", sample)
    assert [n for n in legacy if int(n) != with_legacy], "le décompte avec aliases doit être vu"

    # Contre-épreuve : une sortie d'exemple ne doit PAS être signalée.
    demo = '# "succeeded": 45, "impacted_uuids_count": 45'
    assert not re.findall(
        r"(\d+)\s+(?:tools?|outils?)\s+(?:canoniques?\s+)?(?:par défaut|MCP)", demo
    )


def test_the_reexport_paragraph_describes_the_current_mechanism():
    """``docs/mcp_tools.md`` décrivait des ré-exports supprimés en #171."""
    text = " ".join((DOCS / "mcp_tools.md").read_text(encoding="utf-8").split())

    assert "les ré-exports `server.<tool>` ont été retirés" in text
    assert "résolus paresseusement et refusent de servir" not in text, (
        "le paragraphe décrit encore le mécanisme intermédiaire, supprimé depuis"
    )


def test_the_local_smoke_starts_with_list_mcp_profiles(counts):
    """Le smoke documenté doit commencer par le contrôle qui tranche le plus vite."""
    text = " ".join((DOCS / "claude_desktop_local.md").read_text(encoding="utf-8").split())

    assert "Appelle `list_mcp_profiles`" in text
    assert f"**{counts[0]} outils** annoncés pour I3F" in text
    assert "une vingtaine de tools" not in text
