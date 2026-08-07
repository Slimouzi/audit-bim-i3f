from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import anyio

from audit_bim.mcp import app as mcp_app
from audit_bim.mcp.tools_profiles import list_mcp_profiles
from audit_bim.profiles import list_profiles


def test_list_mcp_profiles_tool_payload():
    out = list_mcp_profiles()
    assert out["status"] == "ok"
    assert out["default_profile_id"] == "i3f"
    assert {p["id"] for p in out["profiles"]} == {"i3f", "bim_in_motion", "domofrance"}
    assert any(m["key"] == "reporting" for m in out["generic_modules"])


def test_list_mcp_profiles_can_filter_one_profile():
    out = list_mcp_profiles("bim-in-motion")
    assert out["status"] == "ok"
    assert [p["id"] for p in out["profiles"]] == ["bim_in_motion"]


def test_list_mcp_profiles_unknown_profile_is_structured_error():
    out = list_mcp_profiles("nope")
    assert out["status"] == "error"
    assert out["error"] == "unknown_profile"
    assert out["available_profile_ids"] == ["i3f", "bim_in_motion", "domofrance"]


def test_list_mcp_profiles_is_registered():
    tools = anyio.run(mcp_app.mcp.list_tools)
    names = {t.name for t in tools}
    assert "list_mcp_profiles" in names


def test_operational_profile_prompt_keys_are_registered():
    """Un profil dont le prompt est `ready` doit servir réellement ce prompt.

    Piloté par le registre, pas par une liste en dur. La mesure se fait **par
    sous-processus, un par profil** : un serveur n'active qu'un profil à la
    fois, donc son registre de prompts ne contient jamais que celui du profil
    courant. Interroger l'instance partagée du processus de test ne pourrait
    valider qu'un seul profil — et ferait passer les autres pour absents.

    Ce contrôle annonçait couvrir `bim_in_motion` le jour où sa spécialisation
    prompt passerait `ready`. C'est arrivé en E5, puis pour `domofrance` : la
    liste n'est pas écrite ici, elle se déduit du registre — un profil ajouté
    est donc couvert sans qu'on y pense.
    """
    ready = [
        profile
        for profile in list_profiles()
        for spec in [
            next((s for s in profile.specializations if s.key.startswith("prompt_")), None)
        ]
        if spec is not None and spec.status == "ready"
    ]
    assert {p.id for p in ready} == {"i3f", "bim_in_motion", "domofrance"}, [p.id for p in ready]

    repo = Path(__file__).resolve().parents[2]
    for profile in ready:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import anyio, json\n"
                "from audit_bim.mcp.app import register_all\n"
                "mcp = register_all()\n"
                "print(json.dumps(sorted(p.name for p in anyio.run(mcp.list_prompts))))\n",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
            env={"PATH": "/usr/bin:/bin", "HOME": str(repo), "AUDIT_BIM_PROFILE": profile.id},
            timeout=180,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        served = json.loads(proc.stdout.strip().splitlines()[-1])
        assert served == [profile.prompt_key], f"{profile.id} sert {served}"
