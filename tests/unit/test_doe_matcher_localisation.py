"""Tests de la stratégie 4 (localisation) du matcher DOE."""

from __future__ import annotations

import pytest

from audit_bim.doe.matcher import (
    LOCALISATION_CONFIDENCE,
    _filter_by_localisation,
    build_localization_index,
    match_doe_records,
)
from audit_bim.doe.models import DoeRecord
from audit_bim.extraction.model_data import ModelSnapshot


@pytest.fixture
def snapshot_with_storey_zone() -> ModelSnapshot:
    """Snapshot avec structure spatiale Site → Building → Storey → Zone → CTA."""
    snap = ModelSnapshot(
        project={"name": "Test"},
        model={"name": "TEST.ifc"},
        sites=[],
        buildings=[],
        storeys=[
            {"uuid": "F-RDC", "name": "REZ-DE-CHAUSSEE", "type": "IfcBuildingStorey"},
            {"uuid": "F-2", "name": "2EME ETAGE", "type": "IfcBuildingStorey"},
        ],
        spaces=[],
        zones=[
            {
                "uuid": "Z-T2",
                "name": "1802L-1101",
                "object_type": "Zone Logement T2",
                "type": "IfcZone",
            },
        ],
        elements=[
            {
                "uuid": "CTA-1",
                "type": "IfcUnitaryEquipmentType",
                "name": "CTA double flux 5000",
                "property_sets": [],
                "classifications": [],
            },
            {
                "uuid": "CTA-2",
                "type": "IfcUnitaryEquipmentType",
                "name": "CTA simple flux 3000",
                "property_sets": [],
                "classifications": [],
            },
            {
                "uuid": "VALVE-1",
                "type": "IfcValveType",
                "name": "Vanne ø50",
                "property_sets": [],
                "classifications": [],
            },
        ],
        structure_tree=[
            {
                "uuid": "P-1",
                "type": "IfcProject",
                "name": "1802L",
                "children": [
                    {
                        "uuid": "S-1",
                        "type": "IfcSite",
                        "name": "1802L",
                        "children": [
                            {
                                "uuid": "B-1",
                                "type": "IfcBuilding",
                                "name": "1802L-A",
                                "children": [
                                    {
                                        "uuid": "F-RDC",
                                        "type": "IfcBuildingStorey",
                                        "name": "REZ-DE-CHAUSSEE",
                                        "children": [
                                            {
                                                "uuid": "CTA-1",
                                                "type": "IfcUnitaryEquipmentType",
                                                "name": "CTA double flux 5000",
                                                "children": [],
                                            },
                                            {
                                                "uuid": "VALVE-1",
                                                "type": "IfcValveType",
                                                "name": "Vanne ø50",
                                                "children": [],
                                            },
                                        ],
                                    },
                                    {
                                        "uuid": "F-2",
                                        "type": "IfcBuildingStorey",
                                        "name": "2EME ETAGE",
                                        "children": [
                                            {
                                                "uuid": "CTA-2",
                                                "type": "IfcUnitaryEquipmentType",
                                                "name": "CTA simple flux 3000",
                                                "children": [],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            }
        ],
    )
    return snap.index()


class TestBuildLocalizationIndex:
    def test_storey_propagated_to_descendants(self, snapshot_with_storey_zone):
        idx = build_localization_index(snapshot_with_storey_zone)
        assert idx["CTA-1"]["storey"] == "REZ-DE-CHAUSSEE"
        assert idx["VALVE-1"]["storey"] == "REZ-DE-CHAUSSEE"
        assert idx["CTA-2"]["storey"] == "2EME ETAGE"

    def test_storey_itself_indexed(self, snapshot_with_storey_zone):
        idx = build_localization_index(snapshot_with_storey_zone)
        # Le storey est dans son propre contexte storey
        assert idx["F-RDC"]["storey"] == "REZ-DE-CHAUSSEE"

    def test_empty_tree_returns_empty_index(self):
        snap = ModelSnapshot(
            project={},
            model={},
            sites=[],
            buildings=[],
            storeys=[],
            spaces=[],
            zones=[],
            elements=[],
            structure_tree=[],
        ).index()
        assert build_localization_index(snap) == {}


class TestFilterByLocalisation:
    def test_filter_by_storey(self, snapshot_with_storey_zone):
        idx = build_localization_index(snapshot_with_storey_zone)
        elements = list(snapshot_with_storey_zone.element_by_uuid.values())
        rec = DoeRecord(source="/x", row_index=1, storey_hint="REZ-DE-CHAUSSEE")
        found = _filter_by_localisation(elements, rec, idx)
        uuids = {e["uuid"] for e in found if e.get("uuid") in ("CTA-1", "VALVE-1", "CTA-2")}
        assert "CTA-1" in uuids
        assert "VALVE-1" in uuids
        assert "CTA-2" not in uuids

    def test_filter_by_type(self, snapshot_with_storey_zone):
        idx = build_localization_index(snapshot_with_storey_zone)
        elements = list(snapshot_with_storey_zone.element_by_uuid.values())
        rec = DoeRecord(source="/x", row_index=1, type_hint="UnitaryEquipment")
        found = _filter_by_localisation(elements, rec, idx)
        uuids = {e["uuid"] for e in found}
        assert "CTA-1" in uuids
        assert "CTA-2" in uuids
        assert "VALVE-1" not in uuids

    def test_combined_storey_and_type_narrows_to_one(self, snapshot_with_storey_zone):
        idx = build_localization_index(snapshot_with_storey_zone)
        elements = list(snapshot_with_storey_zone.element_by_uuid.values())
        rec = DoeRecord(
            source="/x",
            row_index=1,
            storey_hint="REZ-DE-CHAUSSEE",
            type_hint="UnitaryEquipment",
        )
        found = _filter_by_localisation(elements, rec, idx)
        # Une seule CTA au RDC → CTA-1
        eligible = [e for e in found if "CTA" in e.get("uuid", "")]
        assert len(eligible) == 1
        assert eligible[0]["uuid"] == "CTA-1"

    def test_storey_case_insensitive(self, snapshot_with_storey_zone):
        idx = build_localization_index(snapshot_with_storey_zone)
        elements = list(snapshot_with_storey_zone.element_by_uuid.values())
        rec = DoeRecord(source="/x", row_index=1, storey_hint="rez-de-chaussee")
        found = _filter_by_localisation(elements, rec, idx)
        assert any(e.get("uuid") == "CTA-1" for e in found)


class TestMatchDoeRecordsStrategy4:
    def test_localisation_match_when_unique(self, snapshot_with_storey_zone):
        rec = DoeRecord(
            source="/x",
            row_index=1,
            storey_hint="REZ-DE-CHAUSSEE",
            type_hint="UnitaryEquipment",
            properties={"Pset_3F": {"Fabricant": "ATLANTIC"}},
        )
        matches = match_doe_records([rec], snapshot_with_storey_zone)
        assert matches[0].is_matched()
        assert matches[0].strategy == "localisation"
        assert matches[0].confidence == LOCALISATION_CONFIDENCE
        assert matches[0].ifc_uuid == "CTA-1"

    def test_ambiguous_localisation_reports_candidates(self, snapshot_with_storey_zone):
        # Deux CTA dans le modèle (au RDC et au 2e) ; sans préciser l'étage,
        # type_hint='UnitaryEquipment' donne 2 candidats → ambiguïté
        rec = DoeRecord(
            source="/x",
            row_index=1,
            type_hint="UnitaryEquipment",
            properties={"Pset_3F": {"Fabricant": "ATLANTIC"}},
        )
        matches = match_doe_records([rec], snapshot_with_storey_zone)
        assert not matches[0].is_matched()
        assert "ambiguïté" in (matches[0].reason or "")
        assert len(matches[0].candidates) == 2

    def test_no_localisation_hints_unchanged(self, snapshot_with_storey_zone):
        # Pas de hints du tout → reason d'origine
        rec = DoeRecord(
            source="/x",
            row_index=1,
            properties={"Pset_3F": {"Fabricant": "ATLANTIC"}},
        )
        matches = match_doe_records([rec], snapshot_with_storey_zone)
        assert not matches[0].is_matched()
        assert "indice exploitable" in (matches[0].reason or "")

    def test_guid_still_priority_over_localisation(self, snapshot_with_storey_zone):
        # Avec uuid_hint matchant, on doit avoir strategy=guid pas localisation
        rec = DoeRecord(
            source="/x",
            row_index=1,
            uuid_hint="CTA-2",
            storey_hint="REZ-DE-CHAUSSEE",  # mauvais étage volontaire
            properties={"Pset_3F": {"Fabricant": "ATLANTIC"}},
        )
        matches = match_doe_records([rec], snapshot_with_storey_zone)
        assert matches[0].strategy == "guid"
        assert matches[0].ifc_uuid == "CTA-2"
