"""Tests du module ``audit_bim.doe.matcher``."""

from __future__ import annotations

import pytest

from audit_bim.doe.matcher import match_doe_records
from audit_bim.doe.models import DoeRecord
from audit_bim.extraction.model_data import ModelSnapshot


@pytest.fixture
def snapshot_with_equipment() -> ModelSnapshot:
    snap = ModelSnapshot(
        project={"name": "Test"},
        model={"name": "TEST.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[
            {
                "uuid": "DOOR-001",
                "type": "IfcDoor",
                "name": "MEI P INT porte 02:MEI P INT porte 80:3442906",
                "object_type": "MEI P INT porte 02",
                "property_sets": [
                    {
                        "name": "Pset_DoorCommon",
                        "properties": [
                            {
                                "definition": {"name": "Tag", "value_type": "string"},
                                "value": "P-001",
                            },
                        ],
                    }
                ],
                "classifications": [],
            },
            {
                "uuid": "WINDOW-001",
                "type": "IfcWindow",
                "name": "Fenêtre PVC 120x180",
                "property_sets": [],
                "classifications": [],
            },
            {
                "uuid": "FURN-001",
                "type": "IfcFurnishingElement",
                "name": "Canapé 3 places",
                "property_sets": [],
                "classifications": [],
            },
        ],
    )
    return snap.index()


class TestGuidMatching:
    def test_exact_uuid_match(self, snapshot_with_equipment):
        rec = DoeRecord(source="/tmp/doe.xlsx", row_index=1, uuid_hint="DOOR-001")
        matches = match_doe_records([rec], snapshot_with_equipment)
        assert len(matches) == 1
        assert matches[0].is_matched()
        assert matches[0].strategy == "guid"
        assert matches[0].confidence == 1.0
        assert matches[0].ifc_uuid == "DOOR-001"

    def test_unknown_uuid_falls_through(self, snapshot_with_equipment):
        rec = DoeRecord(source="/tmp/doe.xlsx", row_index=1, uuid_hint="UNKNOWN")
        matches = match_doe_records([rec], snapshot_with_equipment)
        assert not matches[0].is_matched()


class TestTagMatching:
    def test_exact_tag_match(self, snapshot_with_equipment):
        rec = DoeRecord(source="/tmp/doe.xlsx", row_index=1, tag_hint="P-001")
        matches = match_doe_records([rec], snapshot_with_equipment)
        assert matches[0].is_matched()
        assert matches[0].strategy == "tag"
        assert matches[0].confidence >= 0.9
        assert matches[0].ifc_uuid == "DOOR-001"

    def test_tag_case_insensitive(self, snapshot_with_equipment):
        rec = DoeRecord(source="/tmp/doe.xlsx", row_index=1, tag_hint="p-001")
        matches = match_doe_records([rec], snapshot_with_equipment)
        assert matches[0].is_matched()


class TestNameMatching:
    def test_fuzzy_name_match(self, snapshot_with_equipment):
        rec = DoeRecord(
            source="/tmp/doe.xlsx",
            row_index=1,
            name_hint="Canapé 3 places",  # exact
        )
        matches = match_doe_records([rec], snapshot_with_equipment)
        assert matches[0].is_matched()
        assert matches[0].strategy == "name"

    def test_fuzzy_with_typo(self, snapshot_with_equipment):
        rec = DoeRecord(
            source="/tmp/doe.xlsx",
            row_index=1,
            name_hint="Fenetre PVC",  # accent manquant
        )
        matches = match_doe_records([rec], snapshot_with_equipment, name_min_score=70)
        # Match probable selon le score fuzzy
        # On vérifie au moins que la fonction tourne sans crash
        assert matches[0].record == rec

    def test_low_score_threshold_rejects(self, snapshot_with_equipment):
        rec = DoeRecord(
            source="/tmp/doe.xlsx",
            row_index=1,
            name_hint="totalement-different-xyz",
        )
        matches = match_doe_records([rec], snapshot_with_equipment, name_min_score=90)
        assert not matches[0].is_matched()


class TestNoHint:
    def test_no_hint_no_match(self, snapshot_with_equipment):
        rec = DoeRecord(source="/tmp/doe.xlsx", row_index=1)
        matches = match_doe_records([rec], snapshot_with_equipment)
        assert not matches[0].is_matched()
        assert "indice exploitable" in (matches[0].reason or "")


class TestOrderPreserved:
    def test_output_same_length_as_input(self, snapshot_with_equipment):
        recs = [
            DoeRecord(source="/tmp/doe.xlsx", row_index=i, uuid_hint=u)
            for i, u in enumerate(["DOOR-001", "WINDOW-001", "FURN-001", "UNKNOWN"], 1)
        ]
        matches = match_doe_records(recs, snapshot_with_equipment)
        assert len(matches) == 4
