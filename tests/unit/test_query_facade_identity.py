"""Parité de façade : ``audit_bim.query.*`` ré-exporte **les mêmes objets** que
``bim-query``.

Après extraction, ``audit_bim/query/*`` est une façade mince au-dessus du package
``bim-query``. Ces tests garantissent que les call-sites historiques
(``mcp/selection.py``, ``mcp/tools_query.py``, ``actions/*_planner.py``)
référencent exactement les symboles du package — ``X is bim_query.X`` — donc
aucun risque de double implémentation ni de divergence.
"""

from __future__ import annotations

import bim_query.filtering as bq_filtering
import bim_query.presets as bq_presets
import bim_query.property_aliases as bq_aliases
import bim_query.table_query as bq_table
import bim_query.views as bq_views

from audit_bim.mcp import tools_query
from audit_bim.query import filtering, property_aliases, table_query, views


class TestFilteringFacade:
    def test_public_functions_are_the_package_objects(self):
        assert filtering.apply_object_filter is bq_filtering.apply_object_filter
        assert filtering.apply_finding_filter is bq_filtering.apply_finding_filter
        assert filtering.apply_suggestion_filter is bq_filtering.apply_suggestion_filter
        assert filtering.object_matches is bq_filtering.object_matches
        assert filtering.finding_matches is bq_filtering.finding_matches
        assert filtering.suggestion_matches is bq_filtering.suggestion_matches

    def test_reexported_enums_are_identical(self):
        assert filtering.ConfidenceBand is bq_filtering.ConfidenceBand
        assert filtering.SuggestionStatus is bq_filtering.SuggestionStatus


class TestViewsFacade:
    def test_public_and_spatial_classes_reexported(self):
        assert views.iter_bim_objects is bq_views.iter_bim_objects
        assert views.bim_object_from_element is bq_views.bim_object_from_element
        # Symbole privé consommé par mcp/selection.py — doit rester identique.
        assert views._SPATIAL_CLASSES is bq_views._SPATIAL_CLASSES


class TestTableQueryFacade:
    def test_models_and_entrypoint_reexported(self):
        assert table_query.BimQuery is bq_table.BimQuery
        assert table_query.BimQueryRow is bq_table.BimQueryRow
        assert table_query.BimQueryResult is bq_table.BimQueryResult
        assert table_query.query_bim_table is bq_table.query_bim_table
        assert table_query.KNOWN_FIELDS is bq_table.KNOWN_FIELDS


class TestPropertyAliasesFacade:
    def test_resolver_and_tables_reexported(self):
        assert property_aliases.resolve_requested_field is bq_aliases.resolve_requested_field
        assert property_aliases.normalize_key is bq_aliases.normalize_key
        assert property_aliases.MatchedValue is bq_aliases.MatchedValue
        assert property_aliases.ACOUSTIC_ALIASES is bq_aliases.ACOUSTIC_ALIASES
        assert property_aliases.DIMENSION_ALIASES is bq_aliases.DIMENSION_ALIASES


class TestPresetsFacade:
    def test_tools_query_uses_package_presets(self):
        # tools_query.py (MCP) consomme désormais le registre du package.
        assert tools_query.QUERY_PRESETS is bq_presets.QUERY_PRESETS

    def test_business_presets_present(self):
        assert set(tools_query.QUERY_PRESETS) == {
            "doors_acoustic_dimensions",
            "walls_fire_acoustic",
            "equipment_maintenance",
        }
