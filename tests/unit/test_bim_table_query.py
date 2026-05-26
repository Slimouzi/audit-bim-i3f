"""Tests du moteur de requête tabulaire (``audit_bim.query.table_query``)."""

from __future__ import annotations

import pytest

from audit_bim.domain.filters import ObjectFilter
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.query.table_query import (
    KNOWN_FIELDS,
    BimQuery,
    BimQueryResult,
    query_bim_table,
)

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def snapshot_doors_walls() -> ModelSnapshot:
    """Snapshot synthétique : 2 portes (1 acoustique, 1 sans), 2 murs."""
    snap = ModelSnapshot(
        project={"name": "P"},
        model={"name": "M.ifc"},
        sites=[],
        buildings=[],
        storeys=[{"uuid": "F1", "name": "R+1", "type": "IfcBuildingStorey"}],
        spaces=[],
        zones=[],
        elements=[
            {
                "uuid": "DR1",
                "type": "IfcDoor",
                "name": "Porte palière",
                "object_type": "Porte CF 30",
                "materials": [
                    {"name": "Acier"},
                    {"name": "Verre feuilleté"},
                ],
                "layers": ["A-DOOR"],
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
                "uuid": "DR2",
                "type": "IfcDoor",
                "name": "Porte 02",
                "materials": [{"name": "Bois massif"}],
                "property_sets": [
                    {
                        "name": "BaseQuantities",
                        "properties": [
                            {"definition": {"name": "Height"}, "value": 2.10},
                            {"definition": {"name": "Width"}, "value": 0.83},
                        ],
                    }
                ],
                # Pas d'acoustique, pas de feu — pour tester include_empty
            },
            {
                "uuid": "W1",
                "type": "IfcWallStandardCase",
                "name": "Mur ext 01",
                "materials": [{"name": "Béton 20cm"}],
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
            {
                "uuid": "W2",
                "type": "IfcWallStandardCase",
                "name": "Cloison 01",
                "materials": [{"name": "Placo BA13"}],
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
        ],
    ).index()
    return snap


# ── BimQuery validation ────────────────────────────────────────────────


class TestBimQueryModel:
    def test_defaults(self):
        q = BimQuery()
        assert q.fields == ["uuid", "ifc_type", "name"]
        assert q.include_empty is True
        assert q.flatten_lists is False
        assert q.limit == 50
        assert q.offset == 0
        assert q.object_filter is None

    def test_rejects_unknown_field_in_pydantic(self):
        with pytest.raises(ValueError, match="extra"):
            BimQuery(unknown="x")  # type: ignore[arg-type]


# ── query_bim_table — cas de base ──────────────────────────────────────


class TestQueryBimTable:
    def test_default_returns_all_components_with_3_columns(self, snapshot_doors_walls):
        result = query_bim_table(snapshot_doors_walls, BimQuery())
        assert isinstance(result, BimQueryResult)
        assert result.columns == ["uuid", "ifc_type", "name"]
        # 4 composants attendus.
        assert result.total == 4
        assert len(result.rows) == 4

    def test_filter_ifc_type_doors(self, snapshot_doors_walls):
        q = BimQuery(object_filter=ObjectFilter(ifc_types=["IfcDoor"]))
        result = query_bim_table(snapshot_doors_walls, q)
        assert result.total == 2
        uuids = {r.uuid for r in result.rows}
        assert uuids == {"DR1", "DR2"}


# ── Cas métier principal : portes + matériaux + acoustique + dims ──────


class TestDoorsAcousticDimensions:
    def test_full_door_row(self, snapshot_doors_walls):
        q = BimQuery(
            object_filter=ObjectFilter(ifc_types=["IfcDoor"]),
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
        result = query_bim_table(snapshot_doors_walls, q)
        assert result.columns == [
            "name",
            "materials",
            "acoustic_performance",
            "height",
            "width",
            "thickness",
            "fire_rating",
        ]
        # Porte DR1 a tous les champs.
        dr1 = next(r for r in result.rows if r.uuid == "DR1")
        assert dr1.values["name"] == "Porte palière"
        assert dr1.values["materials"] == ["Acier", "Verre feuilleté"]
        assert "42" in str(dr1.values["acoustic_performance"])
        assert dr1.values["height"] == 2.04
        assert dr1.values["width"] == 0.93
        assert dr1.values["thickness"] == 0.05
        assert dr1.values["fire_rating"] == "EI30"
        # Cellule porte la source
        assert dr1.cells["acoustic_performance"]["source"] == "property"
        assert dr1.cells["height"]["source"] == "quantity"
        assert dr1.cells["thickness"]["source"] == "property"  # via Pset

    def test_door_without_acoustic_returns_missing_source(self, snapshot_doors_walls):
        q = BimQuery(
            object_filter=ObjectFilter(ifc_types=["IfcDoor"]),
            fields=["name", "acoustic_performance", "fire_rating"],
        )
        result = query_bim_table(snapshot_doors_walls, q)
        dr2 = next(r for r in result.rows if r.uuid == "DR2")
        assert dr2.values["acoustic_performance"] is None
        assert dr2.cells["acoustic_performance"]["source"] == "missing"
        assert dr2.values["fire_rating"] is None
        assert dr2.cells["fire_rating"]["source"] == "missing"


# ── include_empty / flatten_lists ──────────────────────────────────────


class TestIncludeEmpty:
    def test_include_empty_false_excludes_rows_without_semantic_values(self, snapshot_doors_walls):
        # On filtre les portes et demande seulement acoustic_performance.
        # DR1 a la valeur, DR2 non → seul DR1 doit rester.
        q = BimQuery(
            object_filter=ObjectFilter(ifc_types=["IfcDoor"]),
            fields=["name", "acoustic_performance"],
            include_empty=False,
        )
        result = query_bim_table(snapshot_doors_walls, q)
        assert result.total == 1
        assert result.rows[0].uuid == "DR1"

    def test_include_empty_true_includes_all(self, snapshot_doors_walls):
        q = BimQuery(
            object_filter=ObjectFilter(ifc_types=["IfcDoor"]),
            fields=["name", "acoustic_performance"],
            include_empty=True,
        )
        result = query_bim_table(snapshot_doors_walls, q)
        assert result.total == 2


class TestFlattenLists:
    def test_flatten_materials(self, snapshot_doors_walls):
        q = BimQuery(
            object_filter=ObjectFilter(ifc_types=["IfcDoor"]),
            fields=["materials"],
            flatten_lists=True,
        )
        result = query_bim_table(snapshot_doors_walls, q)
        dr1 = next(r for r in result.rows if r.uuid == "DR1")
        assert dr1.values["materials"] == "Acier, Verre feuilleté"

    def test_no_flatten_keeps_list(self, snapshot_doors_walls):
        q = BimQuery(
            object_filter=ObjectFilter(ifc_types=["IfcDoor"]),
            fields=["materials"],
            flatten_lists=False,
        )
        result = query_bim_table(snapshot_doors_walls, q)
        dr1 = next(r for r in result.rows if r.uuid == "DR1")
        assert isinstance(dr1.values["materials"], list)


# ── Pagination ──────────────────────────────────────────────────────────


class TestPagination:
    def test_limit_offset(self, snapshot_doors_walls):
        q = BimQuery(limit=2, offset=0)
        result = query_bim_table(snapshot_doors_walls, q)
        assert result.total == 4
        assert len(result.rows) == 2
        assert result.next_offset == 2

    def test_last_page_next_offset_none(self, snapshot_doors_walls):
        q = BimQuery(limit=2, offset=2)
        result = query_bim_table(snapshot_doors_walls, q)
        assert len(result.rows) == 2
        assert result.next_offset is None


# ── Warnings ────────────────────────────────────────────────────────────


class TestWarnings:
    def test_unknown_field_warning(self, snapshot_doors_walls):
        q = BimQuery(fields=["name", "totally_unknown_field"])
        result = query_bim_table(snapshot_doors_walls, q)
        assert any("totally_unknown_field" in w and "non standard" in w for w in result.warnings)

    def test_field_pset_dotted_no_warning(self, snapshot_doors_walls):
        """Un nom qui ressemble à ``Pset_3F.Lot`` ne doit PAS générer le
        warning 'non standard' (c'est un Pset projet valide)."""
        q = BimQuery(fields=["Pset_3F.Lot"])
        result = query_bim_table(snapshot_doors_walls, q)
        for w in result.warnings:
            assert "non standard" not in w or "Pset_3F.Lot" not in w

    def test_mostly_missing_field_warning(self, snapshot_doors_walls):
        """Si > 80 % des lignes n'ont pas la valeur, on doit logger un
        warning explicatif."""
        # acoustic_performance présent sur 1/4 → > 80 % missing.
        q = BimQuery(fields=["name", "acoustic_performance"])
        result = query_bim_table(snapshot_doors_walls, q)
        assert any("acoustic_performance" in w for w in result.warnings)


# ── KNOWN_FIELDS sanity check ──────────────────────────────────────────


class TestKnownFields:
    def test_contains_business_fields(self):
        for field in (
            "acoustic_performance",
            "fire_rating",
            "manufacturer",
            "height",
            "materials",
        ):
            assert field in KNOWN_FIELDS, f"manque : {field}"

    def test_contains_attributes(self):
        for field in ("uuid", "ifc_type", "name", "object_type", "predefined_type"):
            assert field in KNOWN_FIELDS, f"manque : {field}"
