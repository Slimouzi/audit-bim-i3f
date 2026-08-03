from __future__ import annotations

import anyio

from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.tools_profiles import list_mcp_profiles
from audit_bim.profiles import list_profiles


def test_list_mcp_profiles_tool_payload():
    out = list_mcp_profiles()
    assert out["status"] == "ok"
    assert out["default_profile_id"] == "i3f"
    assert {p["id"] for p in out["profiles"]} == {"i3f", "bim_in_motion"}
    assert any(m["key"] == "reporting" for m in out["generic_modules"])


def test_list_mcp_profiles_can_filter_one_profile():
    out = list_mcp_profiles("bim-in-motion")
    assert out["status"] == "ok"
    assert [p["id"] for p in out["profiles"]] == ["bim_in_motion"]


def test_list_mcp_profiles_unknown_profile_is_structured_error():
    out = list_mcp_profiles("nope")
    assert out["status"] == "error"
    assert out["error"] == "unknown_profile"
    assert out["available_profile_ids"] == ["i3f", "bim_in_motion"]


def test_list_mcp_profiles_is_registered():
    tools = anyio.run(mcp_server.mcp.list_tools)
    names = {t.name for t in tools}
    assert "list_mcp_profiles" in names


def test_operational_profile_prompt_keys_are_registered():
    """Un profil dont le prompt est `ready` doit pointer un prompt réellement servi.

    Piloté par le registre, pas par une liste en dur : `bim_in_motion` est
    ignoré tant que sa spécialisation prompt est `planned`, et sera couvert
    automatiquement le jour où elle passera `ready`.
    """
    registered = {p.name for p in anyio.run(mcp_server.mcp.list_prompts)}
    checked, missing = [], []
    for profile in list_profiles():
        prompt_spec = next(
            (s for s in profile.specializations if s.key.startswith("prompt_")), None
        )
        if prompt_spec is None or prompt_spec.status != "ready":
            continue
        checked.append(profile.id)
        if profile.prompt_key not in registered:
            missing.append(f"{profile.id} -> {profile.prompt_key}")

    assert "i3f" in checked, "le profil I3F doit être couvert par ce garde-fou"
    assert "bim_in_motion" not in checked, "bim_in_motion est `planned` : pas de prompt attendu"
    assert not missing, (
        f"prompt_key déclaré mais non enregistré : {missing} (servis : {registered})"
    )
