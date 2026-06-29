"""Tests du moteur de filtrage (``audit_bim.query.filtering``).

Couvre les 3 entrées : :func:`apply_object_filter`,
:func:`apply_finding_filter`, :func:`apply_suggestion_filter`.
"""

from __future__ import annotations

import pytest

from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.classifier.suggestion_store import (
    ClassificationSuggestionEntry,
    ClassificationSuggestionStore,
)
from audit_bim.domain.filters import (
    ConfidenceBand,
    FindingFilter,
    ObjectFilter,
    SuggestionFilter,
    SuggestionStatus,
)
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.query.filtering import (
    apply_finding_filter,
    apply_object_filter,
    apply_suggestion_filter,
)
from audit_bim.query.views import iter_bim_objects

# ── Fixtures locales ─────────────────────────────────────────────────────


@pytest.fixture
def snapshot_mixed() -> ModelSnapshot:
    """Snapshot avec 3 murs (1 ext, 2 int) + 1 dalle + 1 porte, sur 2 étages."""
    snap = ModelSnapshot(
        project={"name": "Mixed"},
        model={"name": "MIX.ifc"},
        sites=[{"uuid": "S1", "name": "S", "type": "IfcSite"}],
        buildings=[{"uuid": "B1", "name": "B", "type": "IfcBuilding"}],
        storeys=[
            {"uuid": "F1", "name": "RDC", "type": "IfcBuildingStorey"},
            {"uuid": "F2", "name": "R+1", "type": "IfcBuildingStorey"},
        ],
        spaces=[],
        zones=[],
        elements=[
            {
                "uuid": "W1",
                "type": "IfcWallStandardCase",
                "name": "Mur extérieur 01",
                "layers": ["S-MUR-EXT"],
                "classifications": [{"identifier": "B2010", "source": "UniFormat"}],
                "property_sets": [
                    {
                        "name": "Pset_WallCommon",
                        "properties": [
                            {
                                "definition": {"name": "IsExternal"},
                                "value": True,
                            }
                        ],
                    }
                ],
            },
            {
                "uuid": "W2",
                "type": "IfcWallStandardCase",
                "name": "Cloison 01",
                "classifications": [],
                "property_sets": [
                    {
                        "name": "Pset_WallCommon",
                        "properties": [
                            {
                                "definition": {"name": "IsExternal"},
                                "value": False,
                            }
                        ],
                    }
                ],
            },
            {
                "uuid": "W3",
                "type": "IfcWall",
                "name": "Mur 02",
                "classifications": [],
                "property_sets": [],
            },
            {
                "uuid": "SL1",
                "type": "IfcSlab",
                "name": "Dalle haute",
                "classifications": [{"identifier": "B1010", "source": "UniFormat"}],
                "property_sets": [],
            },
            {
                "uuid": "DR1",
                "type": "IfcDoor",
                "name": "Porte 01",
                "classifications": [],
                "property_sets": [],
            },
        ],
        structure_tree=[
            {
                "uuid": "S1",
                "type": "IfcSite",
                "name": "S",
                "children": [
                    {
                        "uuid": "B1",
                        "type": "IfcBuilding",
                        "name": "B",
                        "children": [
                            {
                                "uuid": "F1",
                                "type": "IfcBuildingStorey",
                                "name": "RDC",
                                "children": [
                                    {"uuid": "W1", "type": "IfcWallStandardCase"},
                                    {"uuid": "W2", "type": "IfcWallStandardCase"},
                                    {"uuid": "SL1", "type": "IfcSlab"},
                                ],
                            },
                            {
                                "uuid": "F2",
                                "type": "IfcBuildingStorey",
                                "name": "R+1",
                                "children": [
                                    {"uuid": "W3", "type": "IfcWall"},
                                    {"uuid": "DR1", "type": "IfcDoor"},
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    )
    return snap.index()


def _findings_sample() -> list[Finding]:
    return [
        Finding(
            theme=Theme.CLASSIFICATION,
            severity=Severity.MEDIUM,
            error_type=ErrorType.CLASSIFICATION_MISSING,
            element_uuid="W2",
            ifc_type="IfcWallStandardCase",
            name="Cloison 01",
        ),
        Finding(
            theme=Theme.CLASSIFICATION,
            severity=Severity.MEDIUM,
            error_type=ErrorType.CLASSIFICATION_MISSING,
            element_uuid="DR1",
            ifc_type="IfcDoor",
            name="Porte 01",
        ),
        Finding(
            theme=Theme.PROPERTY_MISSING,
            severity=Severity.HIGH,
            error_type=ErrorType.PROPERTY_MISSING,
            element_uuid="W2",
            ifc_type="IfcWallStandardCase",
            name="Cloison 01",
        ),
        Finding(
            theme=Theme.SPATIAL_HIERARCHY,
            severity=Severity.CRITICAL,
            error_type=ErrorType.SPATIAL_ORPHAN,
            element_uuid=None,  # anomalie projet
            ifc_type="IfcSite",
        ),
    ]


def _store_sample() -> ClassificationSuggestionStore:
    store = ClassificationSuggestionStore()
    store.add(
        ClassificationSuggestionEntry(
            element_uuid="W2",
            ifc_type="IfcWallStandardCase",
            current_classification=None,
            proposed_classification="C1010",
            proposed_level_3="C1010",
            confidence=0.65,
            confidence_band=ConfidenceBand.MEDIUM,
            status=SuggestionStatus.PROPOSED,
        )
    )
    store.add(
        ClassificationSuggestionEntry(
            element_uuid="DR1",
            ifc_type="IfcDoor",
            current_classification=None,
            proposed_classification="C1020",
            proposed_level_3="C1020",
            confidence=0.5,
            confidence_band=ConfidenceBand.LOW,
            status=SuggestionStatus.PROPOSED,
        )
    )
    store.add(
        ClassificationSuggestionEntry(
            element_uuid="W3",
            ifc_type="IfcWall",
            current_classification="B2010",
            proposed_classification="C1010",
            proposed_level_3="C1010",
            confidence=0.9,
            confidence_band=ConfidenceBand.HIGH,
            status=SuggestionStatus.ACCEPTED,
        )
    )
    return store


# ── ObjectFilter ─────────────────────────────────────────────────────────


class TestApplyObjectFilter:
    def test_no_filter_returns_all_components(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, next_offset = apply_object_filter(objects, ObjectFilter())
        # 3 murs + 1 dalle + 1 porte = 5 composants (spatiaux exclus par défaut).
        assert total == 5
        assert len(items) == 5
        assert next_offset is None

    def test_filter_by_ifc_type(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, _ = apply_object_filter(
            objects, ObjectFilter(ifc_types=["IfcWall", "IfcWallStandardCase"])
        )
        assert total == 3
        assert {o.uuid for o in items} == {"W1", "W2", "W3"}

    def test_filter_has_any_classification_false(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, _ = apply_object_filter(objects, ObjectFilter(has_any_classification=False))
        # W2, W3, DR1 sans classification.
        assert total == 3
        assert {o.uuid for o in items} == {"W2", "W3", "DR1"}

    def test_filter_has_any_classification_true(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, _ = apply_object_filter(objects, ObjectFilter(has_any_classification=True))
        # W1 + SL1 ont une classification UniFormat.
        assert total == 2
        assert {o.uuid for o in items} == {"W1", "SL1"}

    def test_filter_by_current_level_3(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, _ = apply_object_filter(objects, ObjectFilter(current_level_3=["B2010"]))
        assert total == 1
        assert items[0].uuid == "W1"

    def test_filter_by_storey(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, _ = apply_object_filter(objects, ObjectFilter(storey_names=["RDC"]))
        # W1, W2, SL1 sont au RDC.
        assert total == 3
        assert {o.uuid for o in items} == {"W1", "W2", "SL1"}

    def test_filter_by_storey_uses_case_insensitive(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, _ = apply_object_filter(objects, ObjectFilter(storey_names=["rdc"]))
        assert total == 3

    def test_filter_is_external(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, _ = apply_object_filter(objects, ObjectFilter(is_external=True))
        assert total == 1
        assert items[0].uuid == "W1"

    def test_filter_missing_property(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, _ = apply_object_filter(
            objects,
            ObjectFilter(
                ifc_types=["IfcWallStandardCase"],
                missing_property="Pset_WallCommon.FireRating",
            ),
        )
        # Aucun mur n'a FireRating → les 2 IfcWallStandardCase matchent.
        assert total == 2

    def test_filter_has_property(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, _ = apply_object_filter(
            objects, ObjectFilter(has_property="Pset_WallCommon.IsExternal")
        )
        # W1 et W2 ont la prop, W3 ne l'a pas.
        assert total == 2
        assert {o.uuid for o in items} == {"W1", "W2"}

    def test_filter_layer_contains(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, _ = apply_object_filter(objects, ObjectFilter(layer_contains="ext"))
        assert total == 1
        assert items[0].uuid == "W1"

    def test_pagination(self, snapshot_mixed):
        objects = list(iter_bim_objects(snapshot_mixed))
        items, total, next_offset = apply_object_filter(objects, ObjectFilter(limit=2, offset=0))
        assert total == 5
        assert len(items) == 2
        assert next_offset == 2
        # Deuxième page
        items2, _, next_offset2 = apply_object_filter(objects, ObjectFilter(limit=2, offset=2))
        assert len(items2) == 2
        assert next_offset2 == 4
        # Troisième page → reste 1 item.
        items3, _, next_offset3 = apply_object_filter(objects, ObjectFilter(limit=2, offset=4))
        assert len(items3) == 1
        assert next_offset3 is None


# ── FindingFilter ────────────────────────────────────────────────────────


class TestApplyFindingFilter:
    def test_no_filter_returns_all(self):
        findings = _findings_sample()
        items, total, _ = apply_finding_filter(findings, FindingFilter())
        assert total == 4

    def test_filter_severity_min_high(self):
        findings = _findings_sample()
        items, total, _ = apply_finding_filter(findings, FindingFilter(severity_min="HIGH"))
        # CRITICAL + HIGH = 2 findings (MEDIUM exclus).
        assert total == 2
        sevs = {f.severity.value for f in items}
        assert sevs == {"CRITICAL", "HIGH"}

    def test_filter_themes(self):
        findings = _findings_sample()
        items, total, _ = apply_finding_filter(
            findings, FindingFilter(themes=["Classification IFC"])
        )
        assert total == 2

    def test_filter_error_types(self):
        findings = _findings_sample()
        items, total, _ = apply_finding_filter(
            findings, FindingFilter(error_types=["classification_missing"])
        )
        assert total == 2

    def test_filter_require_element_uuid(self):
        findings = _findings_sample()
        items, total, _ = apply_finding_filter(findings, FindingFilter(require_element_uuid=True))
        # 3 findings ont un UUID, 1 est anomalie projet.
        assert total == 3

    def test_filter_only_project_anomalies(self):
        findings = _findings_sample()
        items, total, _ = apply_finding_filter(findings, FindingFilter(require_element_uuid=False))
        assert total == 1
        assert items[0].element_uuid is None

    def test_filter_element_uuids(self):
        findings = _findings_sample()
        items, total, _ = apply_finding_filter(findings, FindingFilter(element_uuids=["W2"]))
        assert total == 2  # W2 a 2 findings (classification + property).

    def test_severity_min_invalid_raises(self):
        with pytest.raises(ValueError, match="severity_min"):
            apply_finding_filter(_findings_sample(), FindingFilter(severity_min="ULTRA"))


# ── SuggestionFilter ─────────────────────────────────────────────────────


class TestApplySuggestionFilter:
    def test_no_filter_returns_all(self):
        items, total, _ = apply_suggestion_filter(_store_sample(), SuggestionFilter())
        assert total == 3

    def test_sorted_by_confidence_desc(self):
        items, _, _ = apply_suggestion_filter(_store_sample(), SuggestionFilter())
        confidences = [i.confidence for i in items]
        assert confidences == sorted(confidences, reverse=True)

    def test_filter_min_confidence(self):
        items, total, _ = apply_suggestion_filter(
            _store_sample(), SuggestionFilter(min_confidence=0.7)
        )
        assert total == 1
        assert items[0].element_uuid == "W3"

    def test_filter_confidence_bands(self):
        items, total, _ = apply_suggestion_filter(
            _store_sample(),
            SuggestionFilter(confidence_bands=[ConfidenceBand.HIGH, ConfidenceBand.MEDIUM]),
        )
        # HIGH (W3) + MEDIUM (W2)
        assert total == 2

    def test_filter_only_missing_current(self):
        items, total, _ = apply_suggestion_filter(
            _store_sample(), SuggestionFilter(only_missing_current=True)
        )
        # W2 et DR1 sans current.
        assert total == 2
        assert {i.element_uuid for i in items} == {"W2", "DR1"}

    def test_filter_only_mismatches(self):
        items, total, _ = apply_suggestion_filter(
            _store_sample(), SuggestionFilter(only_mismatches=True)
        )
        # W3 a current=B2010, proposed=C1010 → mismatch.
        assert total == 1
        assert items[0].element_uuid == "W3"

    def test_filter_statuses(self):
        items, total, _ = apply_suggestion_filter(
            _store_sample(), SuggestionFilter(statuses=[SuggestionStatus.ACCEPTED])
        )
        assert total == 1

    def test_filter_proposed_level_3(self):
        items, total, _ = apply_suggestion_filter(
            _store_sample(), SuggestionFilter(proposed_level_3=["C1010"])
        )
        # W2 et W3 proposent C1010.
        assert total == 2

    def test_accepts_iterable_instead_of_store(self):
        entries = list(_store_sample())
        items, total, _ = apply_suggestion_filter(entries, SuggestionFilter())
        assert total == 3

    def test_pagination(self):
        items, total, next_offset = apply_suggestion_filter(
            _store_sample(), SuggestionFilter(limit=2, offset=0)
        )
        assert total == 3
        assert len(items) == 2
        assert next_offset == 2


# ── Filtres quantités + nommage (ajouts sélection) ───────────────────────


@pytest.fixture
def snapshot_quantities() -> ModelSnapshot:
    """2 pièces : une AVEC BaseQuantities (SDB), une SANS (CHAMBRE)."""
    snap = ModelSnapshot(
        project={"name": "Q"},
        model={"name": "Q.ifc"},
        sites=[],
        buildings=[],
        storeys=[],  # pas d'entité spatiale parasite : on teste les 2 IfcSpace
        spaces=[],
        zones=[],
        elements=[
            {
                "uuid": "SP1",
                "type": "IfcSpace",
                "name": "SDB 01",
                "property_sets": [
                    {
                        "name": "BaseQuantities",
                        "properties": [
                            {"definition": {"name": "NetFloorArea"}, "value": 4.2},
                            {"definition": {"name": "GrossVolume"}, "value": 10.5},
                        ],
                    }
                ],
            },
            {
                "uuid": "SP2",
                "type": "IfcSpace",
                "name": "CHAMBRE 02",
                "property_sets": [],
            },
        ],
    )
    return snap.index()


def _uuids(snapshot, **filter_kwargs) -> set[str]:
    # include_spatial=True : la fixture porte les quantités sur des IfcSpace.
    items, _total, _next = apply_object_filter(
        iter_bim_objects(snapshot, include_spatial=True), ObjectFilter(**filter_kwargs)
    )
    return {o.uuid for o in items}


class TestObjectFilterQuantitiesAndNaming:
    def test_has_base_quantities_false_selects_missing(self, snapshot_quantities):
        assert _uuids(snapshot_quantities, has_base_quantities=False) == {"SP2"}

    def test_has_base_quantities_true_selects_present(self, snapshot_quantities):
        assert _uuids(snapshot_quantities, has_base_quantities=True) == {"SP1"}

    def test_missing_quantity_by_name(self, snapshot_quantities):
        # SP2 n'a aucune quantité → NetFloorArea manquante.
        assert _uuids(snapshot_quantities, missing_quantity="NetFloorArea") == {"SP2"}

    def test_has_quantity_by_name(self, snapshot_quantities):
        assert _uuids(snapshot_quantities, has_quantity="NetFloorArea") == {"SP1"}

    def test_name_contains_ci(self, snapshot_quantities):
        assert _uuids(snapshot_quantities, name_contains="sdb") == {"SP1"}

    def test_name_regex(self, snapshot_quantities):
        assert _uuids(snapshot_quantities, name_regex=r"^CHAMBRE") == {"SP2"}

    def test_and_combination_with_ifc_type(self, snapshot_quantities):
        # IfcSpace ∩ sans quantités → SP2.
        assert _uuids(snapshot_quantities, ifc_types=["IfcSpace"], has_base_quantities=False) == {
            "SP2"
        }
