"""Tests des tools MCP ``query_bim_data`` / ``query_bim_preset`` /
``list_query_presets``."""

from __future__ import annotations

import json

import pytest

from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.session import _Session, current_session
from audit_bim.safe_paths import UnsafePathError


@pytest.fixture
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    sess = _Session()
    token = current_session.set(sess)
    try:
        yield sess, tmp_path
    finally:
        current_session.reset(token)


def _snapshot_doors() -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[
            {
                "uuid": "DR1",
                "type": "IfcDoor",
                "name": "Porte palière",
                "materials": [{"name": "Acier"}],
                "property_sets": [
                    {
                        "name": "Pset_DoorCommon",
                        "properties": [
                            {
                                "definition": {"name": "AcousticRating"},
                                "value": "Rw=42dB",
                            },
                            {
                                "definition": {"name": "FireRating"},
                                "value": "EI30",
                            },
                            {
                                "definition": {"name": "Thickness"},
                                "value": 0.05,
                            },
                        ],
                    },
                    {
                        "name": "BaseQuantities",
                        "properties": [
                            {"definition": {"name": "Height"}, "value": 2.04},
                            {"definition": {"name": "Width"}, "value": 0.93},
                        ],
                    },
                ],
            },
            {
                "uuid": "W1",
                "type": "IfcWallStandardCase",
                "name": "Mur ext 01",
                "materials": [{"name": "Béton"}],
                "property_sets": [
                    {
                        "name": "Pset_WallCommon",
                        "properties": [
                            {
                                "definition": {"name": "IsExternal"},
                                "value": True,
                            },
                            {
                                "definition": {"name": "FireRating"},
                                "value": "EI60",
                            },
                        ],
                    }
                ],
            },
        ],
    ).index()


def _wire(sess):
    sess.snapshot = _snapshot_doors()


# ── Enregistrement ──────────────────────────────────────────────────────


class TestRegistered:
    def test_tools_registered(self):
        import anyio

        tools = anyio.run(mcp_server.mcp.list_tools)
        names = {t.name for t in tools}
        assert "query_bim_data" in names
        assert "query_bim_preset" in names
        assert "list_query_presets" in names


# ── query_bim_data ──────────────────────────────────────────────────────


class TestQueryBimData:
    def test_requires_snapshot(self, _isolated):
        with pytest.raises(RuntimeError, match="snapshot"):
            mcp_server.query_bim_data(filter={"ifc_types": ["IfcDoor"]})

    def test_doors_with_semantic_fields(self, _isolated):
        sess, _ = _isolated
        _wire(sess)
        res = mcp_server.query_bim_data(
            filter={"ifc_types": ["IfcDoor"]},
            fields=[
                "name",
                "materials",
                "acoustic_performance",
                "height",
                "width",
                "thickness",
                "fire_rating",
            ],
        )
        assert res["total"] == 1
        assert "rows" in res and "columns" in res
        row = res["rows"][0]
        assert row["name"] == "Porte palière"
        assert row["materials"] == ["Acier"]
        assert "42" in str(row["acoustic_performance"])
        assert row["height"] == 2.04
        assert row["width"] == 0.93
        assert row["thickness"] == 0.05
        assert row["fire_rating"] == "EI30"
        # __uuid présent pour traçabilité
        assert row["__uuid"] == "DR1"

    def test_default_fields(self, _isolated):
        sess, _ = _isolated
        _wire(sess)
        res = mcp_server.query_bim_data()
        assert res["columns"] == ["uuid", "ifc_type", "name"]
        assert res["total"] >= 1

    def test_include_empty_false(self, _isolated):
        sess, _ = _isolated
        _wire(sess)
        res = mcp_server.query_bim_data(
            filter={"ifc_types": ["IfcWallStandardCase"]},
            fields=["name", "acoustic_performance"],  # absent
            include_empty=False,
        )
        # Aucun mur n'a acoustic_performance → 0 lignes après filtre.
        assert res["total"] == 0

    def test_pagination(self, _isolated):
        sess, _ = _isolated
        _wire(sess)
        res = mcp_server.query_bim_data(limit=1, offset=0)
        assert res["total"] == 2  # DR1 + W1
        assert len(res["rows"]) == 1
        assert res["next_offset"] == 1

    def test_unknown_field_warning(self, _isolated):
        sess, _ = _isolated
        _wire(sess)
        res = mcp_server.query_bim_data(fields=["name", "totally_unknown_field"])
        assert any("totally_unknown_field" in w for w in res["warnings"])

    def test_output_path_dumps_full_to_disk(self, _isolated, tmp_path):
        sess, _ = _isolated
        _wire(sess)
        res = mcp_server.query_bim_data(
            filter={"ifc_types": ["IfcDoor"]},
            fields=["name", "materials", "acoustic_performance"],
            output_path="bim_data.json",
        )
        # Avec output_path, le payload retourné est compact.
        assert res.get("items_truncated") is True
        path = tmp_path / "bim_data.json"
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["total"] == 1
        assert len(payload["rows"]) == 1
        assert payload["rows"][0]["name"] == "Porte palière"

    def test_output_path_rejects_traversal(self, _isolated):
        sess, _ = _isolated
        _wire(sess)
        with pytest.raises(UnsafePathError):
            mcp_server.query_bim_data(
                filter={"ifc_types": ["IfcDoor"]}, output_path="../escape.json"
            )

    def test_include_cells_exposes_source(self, _isolated):
        sess, _ = _isolated
        _wire(sess)
        res = mcp_server.query_bim_data(
            filter={"ifc_types": ["IfcDoor"]},
            fields=["acoustic_performance", "height"],
            include_cells=True,
        )
        row = res["rows"][0]
        assert "__cells" in row
        assert row["__cells"]["acoustic_performance"]["source"] == "property"
        assert row["__cells"]["height"]["source"] == "quantity"


# ── query_bim_preset ────────────────────────────────────────────────────


class TestQueryBimPreset:
    def test_doors_acoustic_dimensions(self, _isolated):
        sess, _ = _isolated
        _wire(sess)
        res = mcp_server.query_bim_preset(preset="doors_acoustic_dimensions")
        assert res["preset"] == "doors_acoustic_dimensions"
        assert res["total"] == 1
        # Le row de DR1 doit avoir tous les champs du preset.
        row = res["rows"][0]
        for f in (
            "name",
            "object_type",
            "materials",
            "acoustic_performance",
            "height",
            "width",
            "thickness",
            "fire_rating",
        ):
            assert f in row, f"manque : {f}"

    def test_walls_fire_acoustic(self, _isolated):
        sess, _ = _isolated
        _wire(sess)
        res = mcp_server.query_bim_preset(preset="walls_fire_acoustic")
        assert res["total"] == 1
        row = res["rows"][0]
        assert row["fire_rating"] == "EI60"
        assert row["is_external"] is True

    def test_unknown_preset_raises(self, _isolated):
        sess, _ = _isolated
        _wire(sess)
        with pytest.raises(ValueError, match="preset inconnu"):
            mcp_server.query_bim_preset(preset="not_a_preset")

    def test_preset_filter_merged_with_user_filter(self, _isolated):
        """Si l'utilisateur passe un filtre, il remplace ou complète celui
        du preset (les listes sont overridées)."""
        sess, _ = _isolated
        _wire(sess)
        # Override : on cherche les murs avec le preset doors → 0 doors,
        # mais le user filter remplace ifc_types par IfcWallStandardCase.
        res = mcp_server.query_bim_preset(
            preset="doors_acoustic_dimensions",
            filter={"ifc_types": ["IfcWallStandardCase"]},
        )
        # Le preset cible les portes ; user filter override → 1 mur trouvé.
        assert res["total"] == 1


# ── list_query_presets ──────────────────────────────────────────────────


class TestListQueryPresets:
    def test_returns_3_default_presets(self):
        res = mcp_server.list_query_presets()
        assert res["total"] >= 3
        names = {p["name"] for p in res["presets"]}
        assert {
            "doors_acoustic_dimensions",
            "walls_fire_acoustic",
            "equipment_maintenance",
        }.issubset(names)

    def test_each_preset_has_description_and_fields(self):
        res = mcp_server.list_query_presets()
        for p in res["presets"]:
            assert p.get("description"), f"preset sans description : {p.get('name')}"
            assert p.get("fields"), f"preset sans fields : {p.get('name')}"
