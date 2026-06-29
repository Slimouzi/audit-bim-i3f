"""Tests des tools de sélection actionnable (PR « sélection → viewer / Smart View »).

Couvre :
- le helper partagé :func:`resolve_object_selection` (sélection complète vs page,
  intersection structurel ∩ audit, auto-inclusion spatiale) ;
- la non-régression de ``filter_bim_objects`` (structure de sortie inchangée) ;
- ``show_filtered_objects_in_viewer`` (instruction viewer, bons UUID, overflow) ;
- ``prepare_smart_view_from_filter_plan`` (plan scellé, **aucune écriture**).
"""

from __future__ import annotations

import pytest

from audit_bim.audit.engine import AuditResult
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.domain.write_plan import WritePlanKind
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.selection import ObjectSelection, resolve_object_selection
from audit_bim.mcp.session import _Session, current_session
from audit_bim.requirements.models import BIMPhase, RequirementsCatalog

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def _isolated_session(tmp_path, monkeypatch):
    """Session isolée + AUDIT_OUTPUT_DIR pointé sur tmp_path."""
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    sess = _Session()
    token = current_session.set(sess)
    try:
        yield sess
    finally:
        current_session.reset(token)


def _empty_catalog() -> RequirementsCatalog:
    return RequirementsCatalog(
        cch_version="3.6",
        cch_source_pdf="test://cch.pdf",
        data_spec_source="test://data.xlsx",
        naming_spec_source="test://naming.xlsx",
        properties=[],
        naming_rules=[],
        storey_names=[],
        zone_specs=[],
        room_specs=[],
    )


def _snapshot_two_walls() -> ModelSnapshot:
    snap = ModelSnapshot(
        project={"name": "T"},
        model={"name": "T.ifc"},
        sites=[],
        buildings=[],
        storeys=[{"uuid": "F1", "name": "RDC", "type": "IfcBuildingStorey"}],
        spaces=[],
        zones=[],
        elements=[
            {
                "uuid": "W1",
                "type": "IfcWallStandardCase",
                "name": "Mur ext",
                "classifications": [{"identifier": "B2010", "source": "UniFormat"}],
                "property_sets": [],
            },
            {
                "uuid": "W2",
                "type": "IfcWallStandardCase",
                "name": "Cloison",
                "classifications": [],
                "property_sets": [],
            },
        ],
    )
    return snap.index()


def _result_with_two_walls() -> AuditResult:
    snap = _snapshot_two_walls()
    findings = [
        Finding(
            theme=Theme.CLASSIFICATION,
            severity=Severity.MEDIUM,
            error_type=ErrorType.CLASSIFICATION_MISSING,
            element_uuid="W2",
            ifc_type="IfcWallStandardCase",
            name="Cloison",
        ),
        Finding(
            theme=Theme.PROPERTY_MISSING,
            severity=Severity.HIGH,
            error_type=ErrorType.PROPERTY_MISSING,
            element_uuid="W1",
            ifc_type="IfcWallStandardCase",
            name="Mur ext",
        ),
    ]
    return AuditResult(
        phase=BIMPhase.PRO,
        catalog=_empty_catalog(),
        snapshot=snap,
        findings=findings,
    )


def _snapshot_space_and_wall() -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "T"},
        model={"name": "T.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[
            {"uuid": "SP1", "type": "IfcSpace", "name": "SDB 01", "property_sets": []},
            {"uuid": "W1", "type": "IfcWall", "name": "Mur", "property_sets": []},
        ],
    ).index()


def _result_space_missing_quantity(snap: ModelSnapshot) -> AuditResult:
    return AuditResult(
        phase=BIMPhase.DOE,
        catalog=_empty_catalog(),
        snapshot=snap,
        findings=[
            Finding(
                theme=Theme.QUANTITY,
                severity=Severity.MEDIUM,
                error_type=ErrorType.SPATIAL_MISSING_QUANTITY,
                element_uuid="SP1",
                ifc_type="IfcSpace",
                name="SDB 01",
            )
        ],
    )


# ── resolve_object_selection (helper partagé) ────────────────────────────


class TestResolveObjectSelection:
    def test_requires_snapshot(self, _isolated_session):
        with pytest.raises(RuntimeError, match="snapshot"):
            resolve_object_selection({})

    def test_returns_object_selection_dataclass(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        sel = resolve_object_selection({})
        assert isinstance(sel, ObjectSelection)
        assert sel.total == 2
        assert {o.uuid for o in sel.objects} == {"W1", "W2"}
        assert sel.uuids == [o.uuid for o in sel.objects]
        assert sel.next_offset is None

    def test_full_selection_vs_page(self, _isolated_session):
        # uuids = sélection complète ; page = fenêtre paginée.
        _isolated_session.snapshot = _snapshot_two_walls()
        sel = resolve_object_selection({"limit": 1, "offset": 0})
        assert set(sel.uuids) == {"W1", "W2"}
        assert sel.total == 2
        assert len(sel.page) == 1
        assert sel.next_offset == 1

    def test_structural_intersect_audit(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        _isolated_session.result = _result_with_two_walls()
        sel = resolve_object_selection(
            {"has_any_classification": False},
            with_finding_error_types=["classification_missing"],
        )
        assert set(sel.uuids) == {"W2"}

    def test_combined_spatial_and_audit_selection(self, _isolated_session):
        # Scénario clé CTO : quantités manquantes (audit) ∩ IfcSpace (structurel)
        # doit retourner la pièce SANS include_spatial explicite.
        snap = _snapshot_space_and_wall()
        _isolated_session.snapshot = snap
        _isolated_session.result = _result_space_missing_quantity(snap)
        sel = resolve_object_selection(
            {"ifc_types": ["IfcSpace"]},
            with_finding_error_types=["spatial_missing_quantity"],
        )
        assert set(sel.uuids) == {"SP1"}
        assert sel.total == 1

    def test_invalid_finding_value_raises(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        _isolated_session.result = _result_with_two_walls()
        with pytest.raises(ValueError, match="with_finding_error_types invalide"):
            resolve_object_selection({}, with_finding_error_types=["nope"])


# ── filter_bim_objects : non-régression structurelle ─────────────────────


class TestFilterBimObjectsUnchanged:
    def test_output_structure_unchanged(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        res = mcp_server.filter_bim_objects(filter={"limit": 1, "offset": 0})
        # Mêmes clés, même sémantique qu'avant le refactor.
        assert set(res) >= {"items", "uuids", "total", "next_offset", "limit", "offset"}
        assert res["total"] == 2
        assert len(res["items"]) == 1
        assert set(res["uuids"]) == {"W1", "W2"}
        assert res["next_offset"] == 1
        assert res["limit"] == 1
        assert res["offset"] == 0


# ── show_filtered_objects_in_viewer ──────────────────────────────────────


class TestShowFilteredObjectsInViewer:
    def test_requires_snapshot(self, _isolated_session):
        with pytest.raises(RuntimeError, match="snapshot"):
            mcp_server.show_filtered_objects_in_viewer(filter={})

    def test_default_mode_is_isolate(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        res = mcp_server.show_filtered_objects_in_viewer(filter={})
        assert res["ok"] is True
        assert res["mode"] == "isolate"
        assert res["viewer_instruction"]["action"] == "isolate"

    def test_returns_viewer_instruction_with_right_uuids(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        res = mcp_server.show_filtered_objects_in_viewer(
            filter={"has_any_classification": False}, mode="select"
        )
        assert res["mode"] == "select"
        assert res["count"] == 1
        assert res["viewer_instruction"] == {"action": "select", "element_uuids": ["W2"]}
        assert res["uuids_preview"] == ["W2"]

    def test_combined_spatial_audit_viewer(self, _isolated_session):
        snap = _snapshot_space_and_wall()
        _isolated_session.snapshot = snap
        _isolated_session.result = _result_space_missing_quantity(snap)
        res = mcp_server.show_filtered_objects_in_viewer(
            filter={"ifc_types": ["IfcSpace"]},
            with_finding_error_types=["spatial_missing_quantity"],
            mode="color",
        )
        assert res["viewer_instruction"]["element_uuids"] == ["SP1"]

    def test_overflow_truncates_uuids_to_disk(self, _isolated_session):
        elements = [
            {"uuid": f"W{i}", "type": "IfcWall", "name": f"Mur {i}", "property_sets": []}
            for i in range(60)
        ]
        snap = ModelSnapshot(
            project={"name": "T"},
            model={"name": "T.ifc"},
            sites=[],
            buildings=[],
            storeys=[],
            spaces=[],
            zones=[],
            elements=elements,
        ).index()
        _isolated_session.snapshot = snap
        res = mcp_server.show_filtered_objects_in_viewer(filter={}, output_path="viewer.json")
        # Le jeu complet est dérivé sur disque ; aperçu inline borné.
        assert res["uuids_count"] == 60
        assert res["uuids_truncated"] is True
        assert len(res["uuids"]) == 50
        assert "items_path" in res
        # P1 : la copie imbriquée ne doit PAS garder la liste complète, sinon la
        # réponse inline peut encore dépasser la limite MCP malgré items_path.
        vi = res["viewer_instruction"]
        assert len(vi["element_uuids"]) <= 50
        assert vi["element_uuids_truncated"] is True
        assert vi["element_uuids_count"] == 60


# ── prepare_smart_view_from_filter_plan ──────────────────────────────────


class TestPrepareSmartViewFromFilterPlan:
    def test_confirm_false_semantics_creates_nothing_returns_plan(self, _isolated_session):
        # prepare_* ne crée jamais : il scelle un plan. Le client (factice ici)
        # ne doit jamais être appelé — l'écriture n'a lieu qu'à l'apply confirmé.
        class _ExplodingClient:
            cloud_id = "C"
            project_id = "P"
            model_id = "42"

            def create_bcf_full_topic(self, payload):  # pragma: no cover
                raise AssertionError("prepare ne doit jamais écrire dans BIMData")

        _isolated_session.snapshot = _snapshot_two_walls()
        _isolated_session.client = _ExplodingClient()

        res = mcp_server.prepare_smart_view_from_filter_plan(
            name="Murs sans classification",
            filter={"has_any_classification": False},
            description="sélection à corriger",
        )
        assert res["kind"] == WritePlanKind.SMART_VIEWS.value
        assert res["requires_confirm"] is True
        assert res["n_items"] == 1
        assert res["summary"]["name"] == "Murs sans classification"
        assert res["summary"]["n_elements"] == 1
        assert res["summary"]["color"] == "#FF3D1E"
        # Le plan est scellé sur disque, prêt pour apply_smart_views_plan.
        from pathlib import Path

        assert Path(res["plan_path"]).exists()

    def test_plan_payload_colors_selected_uuids(self, _isolated_session):
        from audit_bim.actions import load_plan

        _isolated_session.snapshot = _snapshot_two_walls()

        class _Client:
            cloud_id = "C"
            project_id = "P"
            model_id = "42"

        _isolated_session.client = _Client()
        res = mcp_server.prepare_smart_view_from_filter_plan(name="Tous", filter={})
        plan = load_plan(res["plan_path"])
        assert plan.kind == WritePlanKind.SMART_VIEWS
        assert len(plan.items) == 1
        coloring = plan.items[0]["viewpoints"][0]["components"]["coloring"]
        guids = {c["ifc_guid"] for c in coloring[0]["components"]}
        assert guids == {"W1", "W2"}
        assert coloring[0]["color"] == "#FF3D1E"
        # Format Smart View minimal (reste dans le panneau dédié).
        assert plan.items[0]["format"] == "bimdata-smartview"
        assert "description" not in plan.items[0]
