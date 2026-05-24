"""Tests du module ``audit_bim.doe.models``."""

from __future__ import annotations

from audit_bim.doe.models import DoeRecord, Match


class TestDoeRecord:
    def test_minimal_record(self):
        rec = DoeRecord(source="/tmp/doe.xlsx", row_index=2)
        assert rec.source == "/tmp/doe.xlsx"
        assert rec.row_index == 2
        assert rec.uuid_hint is None
        assert rec.properties == {}

    def test_with_properties(self):
        rec = DoeRecord(
            source="/tmp/doe.xlsx",
            row_index=3,
            tag_hint="P-01",
            properties={"Pset_3F": {"Fabricant": "BOSCH"}},
        )
        assert rec.tag_hint == "P-01"
        assert rec.properties["Pset_3F"]["Fabricant"] == "BOSCH"

    def test_json_roundtrip(self):
        rec = DoeRecord(
            source="/tmp/doe.xlsx",
            row_index=4,
            uuid_hint="ABC-123",
            name_hint="Porte coupe-feu",
            properties={"Pset_DoorCommon": {"FireRating": "60"}},
        )
        d = rec.model_dump(mode="json")
        rec2 = DoeRecord.model_validate(d)
        assert rec2 == rec


class TestMatch:
    def test_unmatched_when_no_uuid(self):
        rec = DoeRecord(source="/tmp/doe.xlsx", row_index=1, name_hint="X")
        m = Match(record=rec, reason="aucun indice")
        assert m.is_matched() is False
        assert m.confidence == 0.0
        assert m.strategy is None

    def test_matched_with_uuid(self):
        rec = DoeRecord(source="/tmp/doe.xlsx", row_index=1, uuid_hint="GUID-1")
        m = Match(
            record=rec,
            ifc_uuid="GUID-1",
            ifc_type="IfcDoor",
            ifc_name="Porte 01",
            confidence=1.0,
            strategy="guid",
        )
        assert m.is_matched() is True
        assert m.strategy == "guid"

    def test_candidates_for_ambiguous(self):
        rec = DoeRecord(source="/tmp/doe.xlsx", row_index=1, tag_hint="P-01")
        m = Match(
            record=rec,
            candidates=[
                {"uuid": "A", "type": "IfcDoor", "name": "Door 1", "score": 0.9},
                {"uuid": "B", "type": "IfcDoor", "name": "Door 2", "score": 0.9},
            ],
            reason="Tag « P-01 » correspond à 2 éléments — ambiguïté.",
        )
        assert m.is_matched() is False
        assert len(m.candidates) == 2
