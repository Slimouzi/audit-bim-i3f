"""Tests du :class:`WriteJournal`."""

from __future__ import annotations

import json

import pytest

from audit_bim.security import write_journal as journal_mod
from audit_bim.security.write_journal import (
    WriteJournal,
    WriteJournalEntry,
    get_journal,
)


@pytest.fixture(autouse=True)
def _isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    journal_mod._reset_journal_for_tests()
    yield tmp_path
    journal_mod._reset_journal_for_tests()


class TestWriteJournalEntry:
    def test_defaults(self):
        e = WriteJournalEntry(action="apply_x")
        assert e.action == "apply_x"
        assert e.succeeded == 0
        assert e.failed == 0
        assert e.impacted_uuids_count == 0
        assert e.timestamp  # ISO-like

    def test_extra_passthrough(self):
        e = WriteJournalEntry(action="apply_x", extra={"k": 1})
        assert e.extra == {"k": 1}


class TestWriteJournalRecord:
    def test_record_creates_file_under_export_root(self, tmp_path):
        j = WriteJournal()
        j.record(action="apply_bcf_topics", succeeded=3)
        expected_path = tmp_path / "write_log" / "journal.jsonl"
        assert expected_path.exists()
        lines = expected_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["action"] == "apply_bcf_topics"
        assert payload["succeeded"] == 3

    def test_record_appends(self, tmp_path):
        j = WriteJournal()
        j.record(action="apply_bcf_topics", succeeded=1)
        j.record(action="apply_smart_views", succeeded=2)
        path = tmp_path / "write_log" / "journal.jsonl"
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_impacted_uuids_count_computed(self):
        j = WriteJournal()
        e = j.record(action="x", impacted_uuids=["U1", "U2", "U3"])
        assert e.impacted_uuids_count == 3
        # Par défaut, les UUIDs détaillés ne sont PAS écrits.
        assert "impacted_uuids" not in e.extra

    def test_echo_uuids_writes_full_list(self):
        j = WriteJournal()
        e = j.record(action="x", impacted_uuids=["U1", "U2"], echo_uuids=True)
        assert e.extra["impacted_uuids"] == ["U1", "U2"]

    def test_tail_returns_recent_entries(self, tmp_path):
        j = WriteJournal()
        for i in range(5):
            j.record(action=f"apply_{i}")
        tail = j.tail(n=3)
        assert len(tail) == 3
        # Les 3 dernières dans l'ordre d'écriture.
        actions = [e.action for e in tail]
        assert actions == ["apply_2", "apply_3", "apply_4"]

    def test_tail_handles_missing_file(self, tmp_path):
        j = WriteJournal()
        assert j.tail(n=5) == []

    def test_tail_ignores_corrupted_lines(self, tmp_path):
        path = tmp_path / "write_log" / "journal.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"action": "ok", "timestamp": "2026-01-01T00:00:00+00:00"})
            + "\n"
            + "<<corrupted line>>\n"
            + json.dumps({"action": "ok2", "timestamp": "2026-01-01T00:00:01+00:00"})
            + "\n",
            encoding="utf-8",
        )
        j = WriteJournal()
        tail = j.tail(n=10)
        assert len(tail) == 2
        assert [e.action for e in tail] == ["ok", "ok2"]


class TestGetJournalSingleton:
    def test_same_instance(self):
        j1 = get_journal()
        j2 = get_journal()
        assert j1 is j2

    def test_record_via_singleton(self, tmp_path):
        get_journal().record(action="apply_y", succeeded=1)
        assert (tmp_path / "write_log" / "journal.jsonl").exists()
