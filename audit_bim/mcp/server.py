"""Serveur MCP « Audit BIM I3F » — **compat + prompt + point d'entrée**.

Les tools sont désormais répartis **par nature** (PR2 §2b) :
``tools_session`` (cible/contexte/config), ``tools_audit`` (audit + findings),
``tools_reporting`` (livrables), ``tools_actions`` (écritures), ``tools_query``
(lecture). Les ``aliases`` (re-dispatch) sont désormais **opt-in LEGACY** (cf.
``app._legacy_aliases_enabled`` / ``AUDIT_BIM_ENABLE_LEGACY_ALIASES``). L'instance
``mcp``, les middlewares et l'enregistrement **explicite** (``register_all``)
vivent dans ``app.py``.

Ce module ne conserve que : le **prompt** MCP, le point d'entrée ``main()``, et
des **ré-exports de compat** (DÉPRÉCIÉS) pour que
``from audit_bim.mcp import server; server.<tool>(...)`` reste valide (tests +
quelques scripts) — à retirer une fois les appelants migrés. Les ré-exports des
**aliases** sont **lazy** (PEP 562, cf. ``__getattr__``) : importer ``server`` ne
tire plus ``aliases.py`` (sinon les tools LEGACY seraient enregistrés malgré le
flag). (Imports au niveau module : aucun cycle — tous ces modules importent
``mcp`` depuis ``.app``.)
"""

from __future__ import annotations

from ..profiles.i3f.tools_actions import (  # noqa: F401  (ré-export compat)
    apply_bcf_topics,
    apply_classification_update_plan,
    apply_classifications_from_xlsx,
    apply_doe_enrichment_plan,
    apply_smart_views_plan,
    audit_trail,
    extract_doe_records,
    list_write_plans,
    match_doe_to_ifc,
    prepare_bcf_topics,
    prepare_classification_update_plan,
    prepare_doe_enrichment_plan,
    prepare_smart_view_from_filter_plan,
    prepare_smart_views_plan,
    update_suggestion_status,
)
from ..profiles.i3f.tools_audit import (  # noqa: F401  (ré-export compat)
    compare_with_previous_audit,
    doe_match_only,
    enrich_with_public_data,
    full_audit,
    import_preliminary_findings,
    query_findings,
    run_audit_tool,
)
from ..profiles.i3f.tools_query import (  # noqa: F401  (ré-export compat)
    filter_bim_objects,
    get_object_detail,
    list_audit_findings,
    list_classification_suggestions,
    list_query_presets,
    query_bim_data,
    query_bim_preset,
    show_filtered_objects_in_viewer,
)
from ..profiles.i3f.tools_reporting import (  # noqa: F401  (ré-export compat)
    generate_avp_i3f_pack,
    generate_word_report,
    generate_xlsx_annex,
    list_avp_i3f_xls_reports,
)
from ..profiles.i3f.tools_session import (  # noqa: F401  (ré-export compat)
    download_model_ifc,
    extract_model_snapshot,
    get_catalog_properties,
    list_classification_systems,
    parse_owner_requirements,
    project_context_questions,
    set_active_model,
    set_owner_documents,
    verify_active_model,
)
from .app import mcp
from .tools_profiles import list_mcp_profiles  # noqa: F401  (ré-export compat)

# ── Ré-exports de compat LEGACY (aliases métier) — lazy ──────────────────────
# Les aliases sont désormais **opt-in** (cf. ``app._legacy_aliases_enabled``). Pour
# ne **pas** importer ``aliases.py`` au simple import de ``server`` (sinon les 8
# tools seraient enregistrés malgré le flag), les ré-exports de compat
# ``server.<alias>`` sont **lazy** (PEP 562) : ``aliases`` n'est importé qu'à
# l'accès effectif. DÉPRÉCIÉ — à retirer une fois les appelants migrés.
_LEGACY_ALIAS_REEXPORTS = frozenset(
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


def __getattr__(name: str):
    """Ré-export compat lazy des aliases (PEP 562) — n'importe ``aliases`` qu'à la
    demande, pour ne pas enregistrer les tools LEGACY au simple import de ``server``."""
    if name in _LEGACY_ALIAS_REEXPORTS:
        from ..profiles.i3f import aliases

        return getattr(aliases, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    """Point d'entrée du serveur MCP (lance la boucle stdio) — enregistrement
    explicite de tous les tools avant démarrage."""
    from .app import register_all

    register_all()
    mcp.run()
