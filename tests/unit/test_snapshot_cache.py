"""Tests de ``audit_bim.extraction.snapshot_cache``."""

from __future__ import annotations

import gzip
import json

import pytest

from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.extraction.snapshot_cache import (
    _cache_key,
    _cache_path,
    cached_extract_snapshot,
    load_snapshot_from_cache,
    save_snapshot_to_cache,
)


@pytest.fixture
def sample_snapshot() -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "Test"},
        model={"name": "T.ifc", "modified_date": "2026-05-24T15:00:00Z"},
        sites=[{"uuid": "S1", "name": "1802L", "type": "IfcSite"}],
        buildings=[{"uuid": "B1", "name": "1802L-A", "type": "IfcBuilding"}],
        storeys=[{"uuid": "F1", "name": "RDC", "type": "IfcBuildingStorey"}],
        spaces=[{"uuid": "SP1", "longname": "CHAMBRE 01", "type": "IfcSpace"}],
        zones=[],
        elements=[{"uuid": "W1", "type": "IfcWallStandardCase", "name": "M01"}],
        structure_tree=[{"uuid": "P1", "type": "IfcProject", "children": []}],
    ).index()


class TestCacheKey:
    def test_stable_for_same_inputs(self):
        a = _cache_key(1, 2, 3, "2026-05-24")
        b = _cache_key(1, 2, 3, "2026-05-24")
        assert a == b

    def test_different_when_modified_date_changes(self):
        a = _cache_key(1, 2, 3, "2026-05-24")
        b = _cache_key(1, 2, 3, "2026-05-25")
        assert a != b

    def test_different_when_model_id_changes(self):
        assert _cache_key(1, 2, 3, "x") != _cache_key(1, 2, 4, "x")

    def test_handles_none_modified_date(self):
        # Doit pas crasher
        key = _cache_key(1, 2, 3, None)
        assert isinstance(key, str)
        assert len(key) == 16


class TestSaveLoadRoundtrip:
    def test_save_then_load(self, sample_snapshot, tmp_path):
        path = save_snapshot_to_cache(
            sample_snapshot,
            cloud_id=1,
            project_id=2,
            model_id=3,
            model_modified_date="2026-05-24T15:00:00Z",
            cache_dir=tmp_path,
        )
        assert path.exists()
        loaded = load_snapshot_from_cache(
            cloud_id=1,
            project_id=2,
            model_id=3,
            model_modified_date="2026-05-24T15:00:00Z",
            cache_dir=tmp_path,
        )
        assert loaded is not None
        # Mêmes données
        assert loaded.project == sample_snapshot.project
        assert len(loaded.buildings) == len(sample_snapshot.buildings)
        assert len(loaded.elements) == len(sample_snapshot.elements)
        # Index reconstruit
        assert "W1" in loaded.element_by_uuid

    def test_load_miss_when_modified_date_differs(self, sample_snapshot, tmp_path):
        save_snapshot_to_cache(
            sample_snapshot,
            cloud_id=1,
            project_id=2,
            model_id=3,
            model_modified_date="2026-05-24T15:00:00Z",
            cache_dir=tmp_path,
        )
        loaded = load_snapshot_from_cache(
            cloud_id=1,
            project_id=2,
            model_id=3,
            model_modified_date="2026-05-25T00:00:00Z",  # différente
            cache_dir=tmp_path,
        )
        assert loaded is None

    def test_load_miss_when_no_cache(self, tmp_path):
        loaded = load_snapshot_from_cache(
            cloud_id=1,
            project_id=2,
            model_id=3,
            model_modified_date="x",
            cache_dir=tmp_path,
        )
        assert loaded is None

    def test_corrupted_cache_returns_none(self, tmp_path):
        # Écrit un fichier au bon nom mais corrompu
        key = _cache_key(1, 2, 3, "x")
        path = _cache_path(tmp_path, key)
        tmp_path.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not valid gzip")
        loaded = load_snapshot_from_cache(
            cloud_id=1,
            project_id=2,
            model_id=3,
            model_modified_date="x",
            cache_dir=tmp_path,
        )
        assert loaded is None


class TestSchemaVersionInvalidates:
    def test_old_schema_version_ignored(self, sample_snapshot, tmp_path):
        save_snapshot_to_cache(
            sample_snapshot,
            cloud_id=1,
            project_id=2,
            model_id=3,
            model_modified_date="x",
            cache_dir=tmp_path,
        )
        # Simule un cache écrit par une ancienne version : on patch le
        # _schema_version dans le fichier.
        key = _cache_key(1, 2, 3, "x")
        path = _cache_path(tmp_path, key)
        data = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        data["_schema_version"] = -999
        path.write_bytes(gzip.compress(json.dumps(data).encode("utf-8")))
        loaded = load_snapshot_from_cache(
            cloud_id=1,
            project_id=2,
            model_id=3,
            model_modified_date="x",
            cache_dir=tmp_path,
        )
        assert loaded is None


# ── cached_extract_snapshot (intégration avec un FakeClient) ─────────────


class FakeClient:
    """Stub minimal : retourne un model fixe et un snapshot fixe."""

    def __init__(self, snapshot, modified_date="2026-05-24T15:00:00Z"):
        self.cloud_id = 99
        self.project_id = 100
        self.model_id = 101
        self._snapshot = snapshot
        self._model = {"name": "Fake.ifc", "modified_date": modified_date}
        self.extract_calls = 0
        self.get_model_calls = 0

    def get_model(self):
        self.get_model_calls += 1
        return self._model


def _patched_extract(monkeypatch, fake_snap, counter):
    """Patch extract_snapshot pour retourner notre snapshot factice."""
    from audit_bim.extraction import snapshot_cache

    def fake_extract(client):
        counter["n"] += 1
        return fake_snap

    monkeypatch.setattr(snapshot_cache, "extract_snapshot", fake_extract)


class TestCachedExtractSnapshot:
    def test_first_call_is_miss_then_subsequent_is_hit(
        self, sample_snapshot, tmp_path, monkeypatch
    ):
        counter = {"n": 0}
        _patched_extract(monkeypatch, sample_snapshot, counter)
        client = FakeClient(sample_snapshot)

        snap1, hit1 = cached_extract_snapshot(client, cache_dir=tmp_path)
        assert hit1 is False
        assert counter["n"] == 1

        snap2, hit2 = cached_extract_snapshot(client, cache_dir=tmp_path)
        assert hit2 is True
        assert counter["n"] == 1  # pas d'extraction supplémentaire
        assert len(snap2.elements) == len(snap1.elements)

    def test_use_cache_false_forces_extraction(self, sample_snapshot, tmp_path, monkeypatch):
        counter = {"n": 0}
        _patched_extract(monkeypatch, sample_snapshot, counter)
        client = FakeClient(sample_snapshot)
        cached_extract_snapshot(client, cache_dir=tmp_path)  # warm

        _, hit = cached_extract_snapshot(client, cache_dir=tmp_path, use_cache=False)
        assert hit is False
        assert counter["n"] == 2

    def test_model_change_invalidates(self, sample_snapshot, tmp_path, monkeypatch):
        counter = {"n": 0}
        _patched_extract(monkeypatch, sample_snapshot, counter)
        client = FakeClient(sample_snapshot, modified_date="2026-05-24")
        cached_extract_snapshot(client, cache_dir=tmp_path)

        # Le modèle est ré-uploadé → modified_date change
        client._model["modified_date"] = "2026-05-25"
        _, hit = cached_extract_snapshot(client, cache_dir=tmp_path)
        assert hit is False
        assert counter["n"] == 2
