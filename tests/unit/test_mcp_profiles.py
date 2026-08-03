from __future__ import annotations

import anyio

from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.tools_profiles import list_mcp_profiles


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
