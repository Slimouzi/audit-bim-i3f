"""Tests des modèles de filtres déclaratifs (``audit_bim.domain.filters``)."""

from __future__ import annotations

import pytest

from audit_bim.domain.filters import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    ConfidenceBand,
    FindingFilter,
    ObjectFilter,
    SuggestionFilter,
    SuggestionStatus,
)


class TestConfidenceBand:
    def test_high_threshold(self):
        assert ConfidenceBand.from_score(0.85) == ConfidenceBand.HIGH
        assert ConfidenceBand.from_score(0.99) == ConfidenceBand.HIGH

    def test_medium_range(self):
        assert ConfidenceBand.from_score(0.55) == ConfidenceBand.MEDIUM
        assert ConfidenceBand.from_score(0.7) == ConfidenceBand.MEDIUM
        assert ConfidenceBand.from_score(0.849999) == ConfidenceBand.MEDIUM

    def test_low_band(self):
        assert ConfidenceBand.from_score(0.0) == ConfidenceBand.LOW
        assert ConfidenceBand.from_score(0.5) == ConfidenceBand.LOW
        assert ConfidenceBand.from_score(0.54999) == ConfidenceBand.LOW


class TestObjectFilter:
    def test_defaults(self):
        f = ObjectFilter()
        assert f.limit == DEFAULT_LIMIT
        assert f.offset == 0
        assert f.uuids is None
        assert f.has_any_classification is None

    def test_pagination_bounds(self):
        with pytest.raises(ValueError):
            ObjectFilter(limit=0)
        with pytest.raises(ValueError):
            ObjectFilter(limit=MAX_LIMIT + 1)
        with pytest.raises(ValueError):
            ObjectFilter(offset=-1)

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValueError, match="extra"):
            ObjectFilter(unknown_field="x")

    def test_has_and_missing_property_same_key_rejected(self):
        with pytest.raises(ValueError, match="même clé"):
            ObjectFilter(
                has_property="Pset_WallCommon.IsExternal",
                missing_property="pset_wallcommon.isexternal",
            )

    def test_has_and_missing_property_different_keys_ok(self):
        f = ObjectFilter(
            has_property="Pset_WallCommon.IsExternal",
            missing_property="Pset_WallCommon.FireRating",
        )
        assert f.has_property and f.missing_property

    # ── Quantités + nommage (ajouts sélection) ──────────────────────────

    def test_quantity_and_naming_fields_accepted(self):
        f = ObjectFilter(
            has_base_quantities=False,
            has_quantity="NetFloorArea",
            name_contains="SDB",
            name_regex=r"^SDB\s\d+",
        )
        assert f.has_base_quantities is False
        assert f.has_quantity == "NetFloorArea"
        assert f.name_contains == "SDB"

    def test_has_and_missing_quantity_same_key_rejected(self):
        with pytest.raises(ValueError, match="même quantité"):
            ObjectFilter(has_quantity="NetFloorArea", missing_quantity="netfloorarea")

    def test_has_and_missing_quantity_different_keys_ok(self):
        f = ObjectFilter(has_quantity="NetFloorArea", missing_quantity="GrossVolume")
        assert f.has_quantity and f.missing_quantity

    def test_invalid_name_regex_rejected(self):
        with pytest.raises(ValueError, match="name_regex invalide"):
            ObjectFilter(name_regex="[")

    def test_valid_name_regex_ok(self):
        assert ObjectFilter(name_regex=r"^(SDB|WC)\b").name_regex


class TestFindingFilter:
    def test_defaults(self):
        f = FindingFilter()
        assert f.limit == DEFAULT_LIMIT
        assert f.offset == 0
        assert f.themes is None
        assert f.require_element_uuid is None

    def test_severity_min_accepts_known_values(self):
        f = FindingFilter(severity_min="HIGH")
        assert f.severity_min == "HIGH"

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValueError, match="extra"):
            FindingFilter(unknown="x")


class TestSuggestionFilter:
    def test_confidence_range_validated(self):
        with pytest.raises(ValueError, match="min_confidence > max_confidence"):
            SuggestionFilter(min_confidence=0.9, max_confidence=0.5)

    def test_confidence_range_ok(self):
        f = SuggestionFilter(min_confidence=0.5, max_confidence=0.9)
        assert f.min_confidence == 0.5
        assert f.max_confidence == 0.9

    def test_only_mismatches_default_none(self):
        f = SuggestionFilter()
        assert f.only_mismatches is None
        assert f.only_missing_current is None

    def test_statuses_typed(self):
        f = SuggestionFilter(statuses=[SuggestionStatus.ACCEPTED, SuggestionStatus.APPLIED])
        assert SuggestionStatus.ACCEPTED in f.statuses
        assert SuggestionStatus.PROPOSED not in f.statuses

    def test_confidence_bands_typed(self):
        f = SuggestionFilter(confidence_bands=[ConfidenceBand.HIGH])
        assert ConfidenceBand.HIGH in f.confidence_bands
