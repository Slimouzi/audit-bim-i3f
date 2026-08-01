"""Aliases métier = **compat LEGACY opt-in** (``AUDIT_BIM_ENABLE_LEGACY_ALIASES``).

Par défaut, ``register_all`` **n'importe pas** ``audit_bim/mcp/aliases.py`` → les 8
aliases sont absents du registre (moins de bruit côté Claude/harness). Le flag env
les réactive à l'identique, sans toucher aux tools **canoniques**.

L'inventaire est mesuré en **sous-processus** : l'instance ``mcp`` est un singleton
module dont l'enregistrement est cumulatif sur tout le run pytest (d'autres tests
importent ``aliases`` à la collecte). Un process neuf lit l'env au démarrage —
exactement comme le vrai serveur MCP.
"""

from __future__ import annotations

import json
import subprocess
import sys

# Les 8 aliases métier (``audit_bim.mcp.aliases``).
LEGACY_ALIASES = {
    "prepare_bcf_from_findings",
    "apply_bcf_plan",
    "prepare_smartviews_from_findings",
    "apply_smartviews_plan",
    "prepare_classification_corrections",
    "apply_classification_corrections",
    "prepare_doe_enrichment_from_file",
    "apply_doe_enrichment",
}

# Échantillon de tools canoniques qui doivent rester exposés dans les deux modes.
CANONICAL_SAMPLE = {
    "prepare_bcf_topics",
    "apply_bcf_topics",
    "prepare_smart_views_plan",
    "apply_smart_views_plan",
    "prepare_classification_update_plan",
    "apply_classification_update_plan",
    "full_audit",
    "generate_avp_i3f_pack",
}

_CHILD = (
    "import json, anyio;"
    "from audit_bim.mcp.app import register_all;"
    "print(json.dumps(sorted(t.name for t in anyio.run(register_all().list_tools))))"
)


def _inventory(flag: str | None) -> set[str]:
    """Noms de tools enregistrés dans un process neuf, avec/sans le flag env."""
    env = {"PATH": _os_environ_path()}
    # On repart d'un env minimal contrôlé pour éviter qu'un flag hérité du shell
    # ne pollue le cas « défaut ».
    if flag is not None:
        env["AUDIT_BIM_ENABLE_LEGACY_ALIASES"] = flag
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, f"child a échoué : {proc.stderr}"
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


def _os_environ_path() -> str:
    import os

    return os.environ.get("PATH", "")


def test_aliases_absent_by_default():
    tools = _inventory(flag=None)
    present = LEGACY_ALIASES & tools
    assert not present, f"aliases LEGACY exposés par défaut : {sorted(present)}"
    assert CANONICAL_SAMPLE <= tools, f"canoniques manquants : {sorted(CANONICAL_SAMPLE - tools)}"


def test_aliases_absent_when_flag_false():
    tools = _inventory(flag="false")
    assert not (LEGACY_ALIASES & tools)
    assert CANONICAL_SAMPLE <= tools


def test_aliases_present_with_legacy_flag():
    tools = _inventory(flag="true")
    missing = LEGACY_ALIASES - tools
    assert not missing, f"aliases LEGACY manquants sous le flag : {sorted(missing)}"
    assert CANONICAL_SAMPLE <= tools


def test_canonical_tools_unchanged_by_flag():
    """Basculer le flag n'ajoute/retire **que** les aliases : les canoniques sont
    identiques dans les deux modes."""
    without = _inventory(flag=None)
    with_ = _inventory(flag="true")
    assert with_ - without == LEGACY_ALIASES
    assert without <= with_  # le flag n'ajoute rien d'autre, ne retire rien
