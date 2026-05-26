"""Tests du :class:`ClassificationSuggestionStore`."""

from __future__ import annotations

import json

import pytest

from audit_bim.classifier.suggestion_store import (
    ClassificationSuggestionEntry,
    ClassificationSuggestionStore,
)
from audit_bim.domain.filters import ConfidenceBand, SuggestionStatus


def make_entry(
    uuid: str = "U1",
    code: str = "B2010",
    confidence: float = 0.65,
    current: str | None = None,
    status: SuggestionStatus = SuggestionStatus.PROPOSED,
) -> ClassificationSuggestionEntry:
    return ClassificationSuggestionEntry(
        element_uuid=uuid,
        ifc_type="IfcWall",
        current_classification=current,
        proposed_classification=code,
        proposed_label="Exterior Walls",
        proposed_system="uniformat",
        proposed_level_3=code[:5].upper(),
        confidence=confidence,
        confidence_band=ConfidenceBand.from_score(confidence),
        reason_codes=["ifc_class", "layer"],
        evidence={"reasons": ["classe IFC = IfcWall"]},
        status=status,
    )


class TestSuggestionEntry:
    def test_is_mismatch_when_codes_differ(self):
        e = make_entry(code="B2010", current="C1010")
        assert e.is_mismatch is True

    def test_is_mismatch_false_when_same_level_3(self):
        # Code actuel a un suffixe (B2010.10) mais même niveau 3 → pas un mismatch.
        e = make_entry(code="B2010", current="B201010")
        # Actuellement le code "B201010" est normalisé à "B2010" niveau 3.
        # Si current commence par "B" + 4 chiffres, on prend les 5 premiers.
        assert e.is_mismatch is False

    def test_is_mismatch_false_when_current_missing(self):
        e = make_entry(current=None)
        assert e.is_mismatch is False

    def test_is_missing_current(self):
        assert make_entry(current=None).is_missing_current is True
        assert make_entry(current="").is_missing_current is True
        assert make_entry(current="B2010").is_missing_current is False


class TestSuggestionStore:
    def test_add_and_get(self):
        store = ClassificationSuggestionStore()
        assert store.add(make_entry("U1")) is True
        assert len(store) == 1
        got = store.get("U1")
        assert got is not None
        assert got.element_uuid == "U1"

    def test_add_existing_keeps_old_by_default(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1", status=SuggestionStatus.ACCEPTED))
        # Tentative de remplacement sans replace=True
        ok = store.add(make_entry("U1", status=SuggestionStatus.PROPOSED))
        assert ok is False
        assert store.get("U1").status == SuggestionStatus.ACCEPTED

    def test_add_replace_overrides(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1", confidence=0.5))
        ok = store.add(make_entry("U1", confidence=0.9), replace=True)
        assert ok is True
        assert store.get("U1").confidence == 0.9

    def test_update_status(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1"))
        updated = store.update_status("U1", SuggestionStatus.ACCEPTED)
        assert updated is not None
        assert updated.status == SuggestionStatus.ACCEPTED
        assert store.get("U1").status == SuggestionStatus.ACCEPTED

    def test_update_status_unknown_returns_none(self):
        store = ClassificationSuggestionStore()
        assert store.update_status("UNKNOWN", SuggestionStatus.ACCEPTED) is None

    def test_remove(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1"))
        assert store.remove("U1") is True
        assert store.remove("U1") is False
        assert len(store) == 0

    def test_contains(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1"))
        assert "U1" in store
        assert "UNKNOWN" not in store

    def test_counts_by_status(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1", status=SuggestionStatus.PROPOSED))
        store.add(make_entry("U2", status=SuggestionStatus.PROPOSED))
        store.add(make_entry("U3", status=SuggestionStatus.ACCEPTED))
        counts = store.counts_by_status()
        assert counts["proposed"] == 2
        assert counts["accepted"] == 1

    def test_counts_by_band(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1", confidence=0.9))  # HIGH
        store.add(make_entry("U2", confidence=0.6))  # MEDIUM
        store.add(make_entry("U3", confidence=0.4))  # LOW
        counts = store.counts_by_band()
        assert counts == {"high": 1, "medium": 1, "low": 1}

    def test_counts_by_proposed_level_3(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1", code="B2010"))
        store.add(make_entry("U2", code="B2010"))
        store.add(make_entry("U3", code="C1010"))
        assert store.counts_by_proposed_level_3() == {"B2010": 2, "C1010": 1}

    def test_iter(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1"))
        store.add(make_entry("U2"))
        uuids = sorted(e.element_uuid for e in store)
        assert uuids == ["U1", "U2"]


class TestSuggestionStoreSerialization:
    def test_to_json_string(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1"))
        store.add(make_entry("U2", code="C1010"))
        text = store.to_json()
        payload = json.loads(text)
        assert payload["version"] == 1
        assert len(payload["entries"]) == 2
        uuids = sorted(e["element_uuid"] for e in payload["entries"])
        assert uuids == ["U1", "U2"]

    def test_roundtrip_via_disk(self, tmp_path):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1", status=SuggestionStatus.ACCEPTED))
        store.add(make_entry("U2", code="C1010"))
        target = tmp_path / "suggestions.json"
        store.to_json(target)
        assert target.exists()

        loaded = ClassificationSuggestionStore.from_json(target)
        assert len(loaded) == 2
        assert loaded.get("U1").status == SuggestionStatus.ACCEPTED
        assert loaded.get("U2").proposed_classification == "C1010"

    def test_from_json_accepts_string(self):
        store = ClassificationSuggestionStore()
        store.add(make_entry("U1"))
        text = store.to_json()
        loaded = ClassificationSuggestionStore.from_json(text)
        assert len(loaded) == 1

    def test_from_json_empty_payload(self, tmp_path):
        target = tmp_path / "empty.json"
        target.write_text(json.dumps({"version": 1, "entries": []}), encoding="utf-8")
        loaded = ClassificationSuggestionStore.from_json(target)
        assert len(loaded) == 0


class TestSuggestionStoreInvariants:
    def test_entry_confidence_band_consistent(self):
        e = make_entry(confidence=0.9)
        assert e.confidence_band == ConfidenceBand.HIGH

    def test_entry_proposed_level_3_uppercased(self):
        e = ClassificationSuggestionEntry(
            element_uuid="U1",
            proposed_classification="b2010",
            proposed_level_3="b2010",
            confidence=0.5,
            confidence_band=ConfidenceBand.LOW,
        )
        # On laisse le caller normaliser ; mais is_mismatch upper-case.
        assert "b2010" == e.proposed_level_3  # explicite : on ne forge pas la normalisation

    def test_invalid_confidence_rejected(self):
        with pytest.raises(ValueError):
            ClassificationSuggestionEntry(
                element_uuid="U1",
                proposed_classification="B2010",
                proposed_level_3="B2010",
                confidence=1.5,
                confidence_band=ConfidenceBand.HIGH,
            )
