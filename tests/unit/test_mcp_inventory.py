"""Inventaire du registre MCP après la rupture v0.5.0.

Atteste que les 5 tools hérités (et leurs chemins ``legacy_execute``) sont
**absents** du registre, que leurs remplaçants ``list → prepare → apply`` sont
**présents**, et que le registre ``DEPRECATIONS`` est vidé.
"""

from __future__ import annotations

import anyio

from audit_bim.mcp import server as mcp_server

REMOVED_LEGACY_TOOLS = {
    "suggest_classifications",
    "create_bcf_topics",
    "create_smart_views",
    "apply_suggested_classifications",
    "doe_enrich_model",
}

REPLACEMENTS = {
    "list_classification_suggestions",
    "update_suggestion_status",
    "prepare_classification_update_plan",
    "apply_classification_update_plan",
    "prepare_bcf_topics",
    "apply_bcf_topics",
    "prepare_smart_views_plan",
    "apply_smart_views_plan",
    "match_doe_to_ifc",
    "prepare_doe_enrichment_plan",
    "apply_doe_enrichment_plan",
}

# Les 8 aliases métier (``audit_bim.mcp.aliases``) sont désormais **opt-in LEGACY**
# (``AUDIT_BIM_ENABLE_LEGACY_ALIASES``) : absents du registre par défaut. Leur
# présence/absence selon le flag est attestée en **sous-processus** dans
# ``test_mcp_aliases_optin.py`` (le registre in-process est pollué à la collecte).


def _registered_tool_names() -> set[str]:
    tools = anyio.run(mcp_server.mcp.list_tools)
    return {t.name for t in tools}


def test_legacy_tools_are_absent_from_registry():
    still_present = REMOVED_LEGACY_TOOLS & _registered_tool_names()
    assert not still_present, f"tools hérités encore enregistrés (v0.5.0) : {still_present}"


def test_replacement_tools_are_present():
    missing = REPLACEMENTS - _registered_tool_names()
    assert not missing, f"remplaçants manquants dans le registre : {missing}"


def test_deprecations_registry_is_empty():
    from audit_bim.mcp.deprecation import DEPRECATIONS

    assert DEPRECATIONS == {}, f"DEPRECATIONS devrait être vide en v0.5.0 : {set(DEPRECATIONS)}"


def test_tools_legacy_module_is_gone():
    import importlib

    try:
        importlib.import_module("audit_bim.mcp.tools_legacy")
    except ModuleNotFoundError:
        return
    raise AssertionError("audit_bim.mcp.tools_legacy devrait être supprimé en v0.5.0")
