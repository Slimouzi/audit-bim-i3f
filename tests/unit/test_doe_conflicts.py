"""Tests des modules ``audit_bim.doe.conflicts`` + ``enricher`` (intégration)."""

from __future__ import annotations

import pytest

from audit_bim.doe.conflicts import (
    ConflictType,
    classify_conflict,
    detect_conflicts,
    summarize_conflicts,
)
from audit_bim.doe.enricher import apply_matches_to_model
from audit_bim.doe.models import DoeRecord, Match
from audit_bim.extraction.model_data import ModelSnapshot

# ── classify_conflict ────────────────────────────────────────────────────


class TestClassifyConflict:
    def test_new_when_existing_is_none(self):
        assert classify_conflict(None, "BOSCH") == ConflictType.NEW

    def test_upgrade_when_existing_is_empty_string(self):
        assert classify_conflict("", "BOSCH") == ConflictType.UPGRADE
        assert classify_conflict("   ", "BOSCH") == ConflictType.UPGRADE

    def test_match_strings_case_insensitive(self):
        assert classify_conflict("bosch", "BOSCH") == ConflictType.MATCH
        assert classify_conflict("BOSCH ", " bosch") == ConflictType.MATCH

    def test_match_numeric_equivalence(self):
        assert classify_conflict(4, 4.0) == ConflictType.MATCH
        assert classify_conflict("4", 4) == ConflictType.MATCH

    def test_match_bool_equivalence(self):
        assert classify_conflict(True, "V") == ConflictType.MATCH
        assert classify_conflict(True, "OUI") == ConflictType.MATCH
        assert classify_conflict(False, "Non") == ConflictType.MATCH
        assert classify_conflict(True, 1) == ConflictType.MATCH

    def test_conflict_different_strings(self):
        assert classify_conflict("BOSCH", "PHILIPS") == ConflictType.CONFLICT

    def test_conflict_different_numbers(self):
        assert classify_conflict(10, 20) == ConflictType.CONFLICT

    def test_conflict_bool_vs_different_string(self):
        # True != "Faux"
        assert classify_conflict(True, "Faux") == ConflictType.CONFLICT


# ── detect_conflicts + enricher ──────────────────────────────────────────


@pytest.fixture
def snapshot_with_existing_pset() -> ModelSnapshot:
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
                "name": "Porte 01",
                "property_sets": [
                    {
                        "name": "Pset_3F",
                        "properties": [
                            {
                                "definition": {"name": "Fabricant", "value_type": "string"},
                                "value": "PHILIPS",
                            },
                            {
                                "definition": {"name": "Reference", "value_type": "string"},
                                "value": "",  # vide → UPGRADE
                            },
                        ],
                    }
                ],
                "classifications": [],
            },
        ],
    )
    return snap.index()


def _make_match(uuid: str, ifc_type: str, properties: dict) -> Match:
    rec = DoeRecord(source="/tmp/doe.xlsx", row_index=1, uuid_hint=uuid, properties=properties)
    return Match(
        record=rec,
        ifc_uuid=uuid,
        ifc_type=ifc_type,
        ifc_name="Porte 01",
        confidence=1.0,
        strategy="guid",
    )


class TestDetectConflicts:
    def test_match_when_doe_equals_existing(self, snapshot_with_existing_pset):
        m = _make_match("DOOR-001", "IfcDoor", {"Pset_3F": {"Fabricant": "PHILIPS"}})
        reports = detect_conflicts([m], snapshot_with_existing_pset)
        assert len(reports) == 1
        assert reports[0].type == ConflictType.MATCH

    def test_conflict_when_doe_different(self, snapshot_with_existing_pset):
        m = _make_match("DOOR-001", "IfcDoor", {"Pset_3F": {"Fabricant": "BOSCH"}})
        reports = detect_conflicts([m], snapshot_with_existing_pset)
        assert len(reports) == 1
        assert reports[0].type == ConflictType.CONFLICT
        assert reports[0].existing_value == "PHILIPS"
        assert reports[0].doe_value == "BOSCH"

    def test_upgrade_when_existing_empty(self, snapshot_with_existing_pset):
        m = _make_match("DOOR-001", "IfcDoor", {"Pset_3F": {"Reference": "B-001"}})
        reports = detect_conflicts([m], snapshot_with_existing_pset)
        assert len(reports) == 1
        assert reports[0].type == ConflictType.UPGRADE

    def test_new_when_property_absent(self, snapshot_with_existing_pset):
        m = _make_match(
            "DOOR-001",
            "IfcDoor",
            {"Pset_3F": {"Indicateur Bas Carbone": True}},
        )
        reports = detect_conflicts([m], snapshot_with_existing_pset)
        assert len(reports) == 1
        assert reports[0].type == ConflictType.NEW

    def test_mixed_properties(self, snapshot_with_existing_pset):
        m = _make_match(
            "DOOR-001",
            "IfcDoor",
            {
                "Pset_3F": {
                    "Fabricant": "PHILIPS",  # MATCH
                    "Reference": "X-42",  # UPGRADE
                    "Indicateur Bas Carbone": True,  # NEW
                    "MarqueModele": "M-X",  # NEW
                }
            },
        )
        reports = detect_conflicts([m], snapshot_with_existing_pset)
        types = {r.property: r.type for r in reports}
        assert types["Fabricant"] == ConflictType.MATCH
        assert types["Reference"] == ConflictType.UPGRADE
        assert types["Indicateur Bas Carbone"] == ConflictType.NEW
        assert types["MarqueModele"] == ConflictType.NEW


class TestSummarizeConflicts:
    def test_counts(self, snapshot_with_existing_pset):
        m = _make_match(
            "DOOR-001",
            "IfcDoor",
            {
                "Pset_3F": {
                    "Fabricant": "PHILIPS",
                    "Reference": "X-42",
                    "Indicateur Bas Carbone": True,
                }
            },
        )
        reports = detect_conflicts([m], snapshot_with_existing_pset)
        s = summarize_conflicts(reports)
        assert s["n_total"] == 3
        assert s["by_type"]["match"] == 1
        assert s["by_type"]["upgrade"] == 1
        assert s["by_type"]["new"] == 1
        assert s["by_type"]["conflict"] == 0


# ── apply_matches_to_model — intégration ─────────────────────────────────


class FakeClient:
    """Stub minimal de BIMDataClient pour vérifier les POSTs en dry_run."""

    def __init__(self):
        self.cloud_id = 1
        self.project_id = 2
        self.model_id = 3


class TestEnricherOnConflictReport:
    def test_dry_run_skips_match_and_conflict(self, snapshot_with_existing_pset):
        m = _make_match(
            "DOOR-001",
            "IfcDoor",
            {
                "Pset_3F": {
                    "Fabricant": "PHILIPS",  # MATCH → skip
                    "Reference": "X-42",  # UPGRADE → écrit
                    "Brand": "ZARA",  # NEW → écrit
                }
            },
        )
        # Et un second match avec un CONFLICT
        m2 = Match(
            record=DoeRecord(
                source="/tmp/doe.xlsx",
                row_index=2,
                uuid_hint="DOOR-001",
                properties={"Pset_3F": {"Fabricant": "BOSCH"}},  # CONFLICT
            ),
            ifc_uuid="DOOR-001",
            ifc_type="IfcDoor",
            confidence=1.0,
            strategy="guid",
        )
        result = apply_matches_to_model(
            FakeClient(),
            [m, m2],
            dry_run=True,
            snapshot=snapshot_with_existing_pset,
            on_conflict="report",
        )
        # Le Pset à écrire ne contient que UPGRADE + NEW (pas MATCH, pas CONFLICT)
        # Pour m1 : on garde Reference + Brand → 2 props
        # Pour m2 : tout est conflict → 0 props → pas de Pset
        # → n_psets_planned = 1, n_properties_planned = 2
        assert result["n_psets_planned"] == 1
        assert result["n_properties_planned"] == 2
        assert result["n_properties_skipped"] >= 2  # MATCH + CONFLICT
        # Le rapport doit contenir le CONFLICT
        assert any(c["type"] == "conflict" for c in result["conflicts"])
        assert result["conflicts_summary"]["by_type"]["match"] == 1
        assert result["conflicts_summary"]["by_type"]["conflict"] == 1


class TestEnricherOverwrite:
    def test_overwrite_writes_conflicts(self, snapshot_with_existing_pset):
        m = _make_match(
            "DOOR-001",
            "IfcDoor",
            {"Pset_3F": {"Fabricant": "BOSCH"}},  # CONFLICT
        )
        result = apply_matches_to_model(
            FakeClient(),
            [m],
            dry_run=True,
            snapshot=snapshot_with_existing_pset,
            on_conflict="overwrite",
        )
        # En overwrite, le CONFLICT est écrit
        assert result["n_psets_planned"] == 1
        assert result["n_properties_planned"] == 1
        assert result["n_properties_skipped"] == 0


class TestEnricherWithoutSnapshot:
    def test_legacy_mode_writes_everything(self, snapshot_with_existing_pset):
        # snapshot=None → pas de détection de conflit, on écrit tout
        m = _make_match(
            "DOOR-001",
            "IfcDoor",
            {"Pset_3F": {"Fabricant": "PHILIPS", "Brand": "ZARA"}},
        )
        result = apply_matches_to_model(
            FakeClient(),
            [m],
            dry_run=True,
            snapshot=None,  # mode V1 legacy
        )
        assert result["n_properties_planned"] == 2
        assert result["n_properties_skipped"] == 0
        assert result["conflicts_summary"]["n_total"] == 0
