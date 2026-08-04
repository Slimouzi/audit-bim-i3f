"""Serveur MCP « Audit BIM I3F » — **compat + point d'entrée**.

Les tools vivent dans le **profil** (``audit_bim.profiles.i3f``, E2), répartis
par nature : ``tools_session`` (cible/contexte/config), ``tools_audit`` (audit +
findings), ``tools_reporting`` (livrables), ``tools_actions`` (écritures),
``tools_query`` (lecture). Les ``aliases`` (re-dispatch) sont désormais **opt-in LEGACY** (cf.
``app._legacy_aliases_enabled`` / ``AUDIT_BIM_ENABLE_LEGACY_ALIASES``). L'instance
``mcp``, les middlewares et l'enregistrement **explicite** (``register_all``)
vivent dans ``app.py``.

Ce module ne conserve plus que des **ré-exports de compat** (DÉPRÉCIÉS) pour que
``from audit_bim.mcp import server; server.<tool>(...)`` reste valide.

**Plus aucun appelant du dépôt ne les utilise** depuis E3-B : tests et scripts
appellent les modules du profil directement. Ils ne subsistent que pour un
consommateur externe éventuel, et ne sont **pas** l'API principale — celle-ci
est le registre MCP, ou ``audit_bim.profiles.i3f.tools_*`` côté Python.

Ils ne sont plus non plus nécessaires à l'enregistrement : ``register_all()``
importe elle-même les modules du profil actif. Les retirer serait sans effet sur
la surface MCP — c'est un choix de compatibilité, pas une contrainte technique.

**Tous** les ré-exports sont **lazy** (PEP 562, cf. ``__getattr__``) et
**conditionnés au profil actif** (E4). Ce n'est pas une optimisation : ces
imports déclenchent les ``@mcp.tool`` du profil I3F. Tant qu'ils s'exécutaient
au chargement du module, un simple ``import audit_bim.mcp.server`` — que
l'``__init__`` du paquet provoquait lui-même pour exposer ``main`` — enregistrait
les 45 outils I3F **avant** que ``register_all()`` n'ait choisi le profil. La
sélection de profil devenait alors un paramètre sans effet, silencieusement.

``main()`` a rejoint ``app`` pour la même raison, et n'est plus ici qu'un
ré-export. Le paquet n'a donc plus aucune raison de charger ce module.

Le **prompt** n'est plus déclaré ici depuis E3-A : sa déclaration vit dans
``audit_bim.profiles.i3f.prompts.register_prompts()``, appelée par
``app.register_all()``. Ce module ignore jusqu'au nom de la constante — c'est ce
qui permet à un autre profil d'enregistrer les siens sans le modifier.
"""

from __future__ import annotations

from importlib import import_module

from ..profiles.active import UnknownProfileError, resolve_active_profile
from .app import main, mcp  # noqa: F401  (``main`` : ré-export historique)
from .tools_profiles import list_mcp_profiles  # noqa: F401  (ré-export compat)

# ── Ré-exports de compat — TOUS lazy ─────────────────────────────────────────
# Importés à l'accès, jamais au chargement du module. C'est une contrainte de
# correction, pas une optimisation : ces imports déclenchent les ``@mcp.tool``
# du profil I3F. Tant qu'ils étaient au niveau module, un simple
# ``import audit_bim.mcp.server`` enregistrait les 45 outils I3F **avant** que
# ``register_all()`` n'ait choisi le profil actif — le profil sélectionné
# devenait alors sans effet, sans qu'aucune erreur ne le signale.

_REEXPORTS: dict[str, str] = {
    "apply_bcf_topics": "audit_bim.profiles.i3f.tools_actions",
    "apply_classification_update_plan": "audit_bim.profiles.i3f.tools_actions",
    "apply_classifications_from_xlsx": "audit_bim.profiles.i3f.tools_actions",
    "apply_doe_enrichment_plan": "audit_bim.profiles.i3f.tools_actions",
    "apply_smart_views_plan": "audit_bim.profiles.i3f.tools_actions",
    "audit_trail": "audit_bim.profiles.i3f.tools_actions",
    "extract_doe_records": "audit_bim.profiles.i3f.tools_actions",
    "list_write_plans": "audit_bim.profiles.i3f.tools_actions",
    "match_doe_to_ifc": "audit_bim.profiles.i3f.tools_actions",
    "prepare_bcf_topics": "audit_bim.profiles.i3f.tools_actions",
    "prepare_classification_update_plan": "audit_bim.profiles.i3f.tools_actions",
    "prepare_doe_enrichment_plan": "audit_bim.profiles.i3f.tools_actions",
    "prepare_smart_view_from_filter_plan": "audit_bim.profiles.i3f.tools_actions",
    "prepare_smart_views_plan": "audit_bim.profiles.i3f.tools_actions",
    "update_suggestion_status": "audit_bim.profiles.i3f.tools_actions",
    "compare_with_previous_audit": "audit_bim.profiles.i3f.tools_audit",
    "doe_match_only": "audit_bim.profiles.i3f.tools_audit",
    "enrich_with_public_data": "audit_bim.profiles.i3f.tools_audit",
    "full_audit": "audit_bim.profiles.i3f.tools_audit",
    "import_preliminary_findings": "audit_bim.profiles.i3f.tools_audit",
    "query_findings": "audit_bim.profiles.i3f.tools_audit",
    "run_audit_tool": "audit_bim.profiles.i3f.tools_audit",
    "filter_bim_objects": "audit_bim.profiles.i3f.tools_query",
    "get_object_detail": "audit_bim.profiles.i3f.tools_query",
    "list_audit_findings": "audit_bim.profiles.i3f.tools_query",
    "list_classification_suggestions": "audit_bim.profiles.i3f.tools_query",
    "list_query_presets": "audit_bim.profiles.i3f.tools_query",
    "query_bim_data": "audit_bim.profiles.i3f.tools_query",
    "query_bim_preset": "audit_bim.profiles.i3f.tools_query",
    "show_filtered_objects_in_viewer": "audit_bim.profiles.i3f.tools_query",
    "generate_avp_i3f_pack": "audit_bim.profiles.i3f.tools_reporting",
    "generate_word_report": "audit_bim.profiles.i3f.tools_reporting",
    "generate_xlsx_annex": "audit_bim.profiles.i3f.tools_reporting",
    "list_avp_i3f_xls_reports": "audit_bim.profiles.i3f.tools_reporting",
    "download_model_ifc": "audit_bim.profiles.i3f.tools_session",
    "extract_model_snapshot": "audit_bim.profiles.i3f.tools_session",
    "get_catalog_properties": "audit_bim.profiles.i3f.tools_session",
    "list_classification_systems": "audit_bim.profiles.i3f.tools_session",
    "parse_owner_requirements": "audit_bim.profiles.i3f.tools_session",
    "project_context_questions": "audit_bim.profiles.i3f.tools_session",
    "set_active_model": "audit_bim.profiles.i3f.tools_session",
    "set_owner_documents": "audit_bim.profiles.i3f.tools_session",
    "verify_active_model": "audit_bim.profiles.i3f.tools_session",
}

#: Aliases métier LEGACY (opt-in) — même traitement, même module.
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

_I3F_ALIAS_MODULE = "audit_bim.profiles.i3f.aliases"


def _i3f_is_active() -> bool:
    """Vrai si le profil actif est I3F. Un identifiant illisible vaut « non »."""
    try:
        return resolve_active_profile().id == "i3f"
    except UnknownProfileError:
        return False


def __getattr__(name: str):
    """Ré-export compat **lazy** et **conditionné au profil actif** (PEP 562).

    Sous un autre profil, ces noms n'existent pas : les servir importerait le
    profil I3F dans le processus d'un autre AMO, et y enregistrerait ses outils.
    L'``AttributeError`` est donc le comportement correct, pas une limitation.
    """
    if name in _LEGACY_ALIAS_REEXPORTS:
        module_path = _I3F_ALIAS_MODULE
    elif name in _REEXPORTS:
        module_path = _REEXPORTS[name]
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    if not _i3f_is_active():
        raise AttributeError(
            f"{name!r} est un ré-export du profil I3F, qui n'est pas le profil "
            f"actif. Passer par audit_bim.profiles.i3f.* si c'est délibéré."
        )
    return getattr(import_module(module_path), name)
