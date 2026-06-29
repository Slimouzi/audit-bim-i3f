"""Tests des tools MCP de filtrage (``filter_bim_objects`` &co).

Couvre :
- enregistrement correct des 4 tools côté FastMCP ;
- pagination + ``next_offset`` ;
- overflow disque > 256 KB + ``items_path`` ;
- respect du sandbox ``AUDIT_OUTPUT_DIR`` ;
- propagation du store de suggestions au tool ``list_classification_suggestions``.
"""

from __future__ import annotations

import json

import pytest

from audit_bim.audit.engine import AuditResult
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.classifier.suggestion_store import (
    ClassificationSuggestionEntry,
    ClassificationSuggestionStore,
)
from audit_bim.domain.filters import ConfidenceBand, SuggestionStatus
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.session import _Session, current_session
from audit_bim.requirements.models import BIMPhase, RequirementsCatalog
from audit_bim.safe_paths import UnsafePathError

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


# ── Enregistrement des tools ────────────────────────────────────────────


class TestToolsRegistered:
    def test_new_filter_tools_registered(self):
        # ``mcp.list_tools`` est async côté FastMCP. On l'exécute via
        # ``anyio.run`` (déjà transitivement disponible via FastMCP)
        # pour éviter d'ajouter pytest-asyncio uniquement pour ce test.
        import anyio

        tools = anyio.run(mcp_server.mcp.list_tools)
        names = {t.name for t in tools}
        assert "filter_bim_objects" in names
        assert "list_audit_findings" in names
        assert "get_object_detail" in names
        assert "list_classification_suggestions" in names


# ── filter_bim_objects ───────────────────────────────────────────────────


class TestFilterBimObjects:
    def test_requires_snapshot(self, _isolated_session):
        with pytest.raises(RuntimeError, match="snapshot"):
            mcp_server.filter_bim_objects(filter={})

    def test_returns_all_when_no_filter(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        res = mcp_server.filter_bim_objects()
        assert res["total"] == 2
        assert len(res["items"]) == 2

    def test_filters_by_ifc_type(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        res = mcp_server.filter_bim_objects(filter={"ifc_types": ["IfcWallStandardCase"]})
        assert res["total"] == 2

    def test_filters_by_has_classification(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        res = mcp_server.filter_bim_objects(filter={"has_any_classification": False})
        assert res["total"] == 1
        assert res["items"][0]["uuid"] == "W2"

    def test_output_path_writes_disk_and_returns_compact(self, _isolated_session, tmp_path):
        _isolated_session.snapshot = _snapshot_two_walls()
        res = mcp_server.filter_bim_objects(filter={}, output_path="out.json")
        assert res.get("items_truncated") is True
        path = tmp_path / "out.json"
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["total"] == 2
        assert len(payload["items"]) == 2

    def test_output_path_rejects_traversal(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        with pytest.raises(UnsafePathError):
            mcp_server.filter_bim_objects(filter={}, output_path="../escape.json")

    def test_pagination_returns_next_offset(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        res = mcp_server.filter_bim_objects(filter={"limit": 1, "offset": 0})
        assert res["total"] == 2
        assert len(res["items"]) == 1
        assert res["next_offset"] == 1

    def test_uuids_is_full_selection_not_just_page(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        res = mcp_server.filter_bim_objects(filter={"limit": 1, "offset": 0})
        # total = cardinal post-filtres / pré-pagination ; uuids = sélection complète.
        assert res["total"] == 2
        assert len(res["items"]) == 1
        assert set(res["uuids"]) == {"W1", "W2"}

    # ── Intersection avec l'audit (with_finding_*) ──────────────────────

    def test_finding_filter_requires_audit(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        with pytest.raises(RuntimeError, match="audit"):
            mcp_server.filter_bim_objects(with_finding_error_types=["classification_missing"])

    def test_finding_error_type_intersect(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        _isolated_session.result = _result_with_two_walls()
        res = mcp_server.filter_bim_objects(with_finding_error_types=["classification_missing"])
        assert set(res["uuids"]) == {"W2"}
        assert res["total"] == 1

    def test_finding_theme_intersect(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        _isolated_session.result = _result_with_two_walls()
        res = mcp_server.filter_bim_objects(with_finding_themes=["Propriété manquante"])
        assert set(res["uuids"]) == {"W1"}

    def test_structural_intersect_audit(self, _isolated_session):
        # W2 a la finding classification_missing ET n'a aucune classification.
        _isolated_session.snapshot = _snapshot_two_walls()
        _isolated_session.result = _result_with_two_walls()
        res = mcp_server.filter_bim_objects(
            filter={"has_any_classification": False},
            with_finding_error_types=["classification_missing"],
        )
        assert set(res["uuids"]) == {"W2"}

    def test_invalid_finding_value_raises(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        _isolated_session.result = _result_with_two_walls()
        with pytest.raises(ValueError, match="with_finding_error_types invalide"):
            mcp_server.filter_bim_objects(with_finding_error_types=["nope"])

    def test_invalid_finding_theme_raises(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        _isolated_session.result = _result_with_two_walls()
        with pytest.raises(ValueError, match="with_finding_themes invalide"):
            mcp_server.filter_bim_objects(with_finding_themes=["Pas un thème"])

    @staticmethod
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

    def test_spatial_excluded_by_default(self, _isolated_session):
        # Sélection non ciblée spatiale → IfcSpace exclus.
        _isolated_session.snapshot = self._snapshot_space_and_wall()
        res = mcp_server.filter_bim_objects(filter={})
        assert set(res["uuids"]) == {"W1"}

    def test_spatial_auto_included_when_ifc_type_targets_space(self, _isolated_session):
        # ifc_types spatial → include_spatial auto-activé (pas de piège).
        _isolated_session.snapshot = self._snapshot_space_and_wall()
        res = mcp_server.filter_bim_objects(
            filter={"ifc_types": ["IfcSpace"], "has_base_quantities": False}
        )
        assert set(res["uuids"]) == {"SP1"}

    def test_spatial_auto_included_for_audit_filter(self, _isolated_session):
        # Scénario clé : « quantités manquantes selon l'audit » sur IfcSpace
        # doit retourner la pièce SANS include_spatial explicite.
        snap = self._snapshot_space_and_wall()
        _isolated_session.snapshot = snap
        _isolated_session.result = AuditResult(
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
        res = mcp_server.filter_bim_objects(with_finding_error_types=["spatial_missing_quantity"])
        assert set(res["uuids"]) == {"SP1"}

    def test_uuids_compacted_on_disk_overflow(self, _isolated_session):
        # Grosse sélection forcée sur disque → uuids tronqué + uuids_count.
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
        res = mcp_server.filter_bim_objects(filter={"limit": 500}, output_path="big.json")
        assert res["items_truncated"] is True
        assert res["uuids_count"] == 60
        assert res["uuids_truncated"] is True
        assert len(res["uuids"]) == 50  # aperçu


# ── list_audit_findings ─────────────────────────────────────────────────


class TestListAuditFindings:
    def test_requires_audit(self, _isolated_session):
        with pytest.raises(RuntimeError, match="audit"):
            mcp_server.list_audit_findings(filter={})

    def test_returns_all(self, _isolated_session):
        _isolated_session.result = _result_with_two_walls()
        res = mcp_server.list_audit_findings()
        assert res["total"] == 2

    def test_filter_severity_min(self, _isolated_session):
        _isolated_session.result = _result_with_two_walls()
        res = mcp_server.list_audit_findings(filter={"severity_min": "HIGH"})
        assert res["total"] == 1
        assert res["items"][0]["severity"] == "HIGH"

    def test_filter_error_types(self, _isolated_session):
        _isolated_session.result = _result_with_two_walls()
        res = mcp_server.list_audit_findings(filter={"error_types": ["classification_missing"]})
        assert res["total"] == 1


# ── get_object_detail ────────────────────────────────────────────────────


class TestGetObjectDetail:
    def test_unknown_uuid_raises(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        with pytest.raises(ValueError, match="UUID inconnu"):
            mcp_server.get_object_detail(uuid="NOPE")

    def test_returns_object_with_findings(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        _isolated_session.result = _result_with_two_walls()
        res = mcp_server.get_object_detail(uuid="W2")
        assert res["object"]["uuid"] == "W2"
        assert res["n_findings"] == 1
        assert res["findings"][0]["error_type"] == "classification_missing"

    def test_excludes_psets_when_flag_false(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        res = mcp_server.get_object_detail(uuid="W1", include_psets=False)
        assert "properties" not in res["object"]

    def test_includes_suggestion_when_in_store(self, _isolated_session):
        _isolated_session.snapshot = _snapshot_two_walls()
        store = ClassificationSuggestionStore()
        store.add(
            ClassificationSuggestionEntry(
                element_uuid="W2",
                ifc_type="IfcWallStandardCase",
                proposed_classification="C1010",
                proposed_level_3="C1010",
                confidence=0.65,
                confidence_band=ConfidenceBand.MEDIUM,
            )
        )
        _isolated_session.suggestion_store = store
        res = mcp_server.get_object_detail(uuid="W2")
        assert res["suggestion"] is not None
        assert res["suggestion"]["proposed_classification"] == "C1010"


# ── list_classification_suggestions ──────────────────────────────────────


class TestListClassificationSuggestions:
    def test_populates_lazily_from_audit(self, _isolated_session):
        _isolated_session.result = _result_with_two_walls()
        res = mcp_server.list_classification_suggestions()
        # W2 a un finding classification_missing → 1 suggestion attendue.
        assert res["total"] >= 1
        assert res["store_counts"]["total"] >= 1
        # Le store doit être peuplé en session.
        assert _isolated_session.suggestion_store is not None

    def test_does_not_repopulate_when_populate_false(self, _isolated_session):
        _isolated_session.result = _result_with_two_walls()
        # Pré-remplit le store avec un statut accepted.
        store = ClassificationSuggestionStore()
        store.add(
            ClassificationSuggestionEntry(
                element_uuid="WX",
                ifc_type="IfcWallStandardCase",
                proposed_classification="C1010",
                proposed_level_3="C1010",
                confidence=0.9,
                confidence_band=ConfidenceBand.HIGH,
                status=SuggestionStatus.ACCEPTED,
            )
        )
        _isolated_session.suggestion_store = store
        res = mcp_server.list_classification_suggestions(populate=False)
        assert res["total"] == 1
        assert res["items"][0]["element_uuid"] == "WX"

    def test_filter_min_confidence(self, _isolated_session):
        _isolated_session.result = _result_with_two_walls()
        # Filtre haut → 0 suggestion attendue (suggester sur IfcWallStandardCase
        # sans IsExternal renvoie ~0.5).
        res = mcp_server.list_classification_suggestions(filter={"min_confidence": 0.95})
        assert res["total"] == 0
