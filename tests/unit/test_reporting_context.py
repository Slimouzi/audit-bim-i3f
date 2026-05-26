"""Tests de :mod:`audit_bim.reporting.context`."""

from __future__ import annotations

from audit_bim.audit.engine import AuditResult
from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.reporting.context import (
    ControlDescription,
    ReportProjectContext,
    build_report_context,
)
from audit_bim.requirements.models import (
    BIMPhase,
    NamingRule,
    PropertySpec,
    RequirementsCatalog,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _catalog(version: str | None = "3.6") -> RequirementsCatalog:
    return RequirementsCatalog(
        cch_version=version,
        cch_source_pdf="/tmp/cch.pdf" if version else None,
        data_spec_source="/tmp/data.xlsx" if version else None,
        naming_spec_source="/tmp/naming.xlsx" if version else None,
        properties=[
            PropertySpec(
                theme="Architecture",
                objet="Mur",
                ifc_class="IfcWall",
                property_name="Surface",
                pset_or_attribute="BaseQuantities/NetSideArea",
                required_phases=[BIMPhase.PRO],
                ref_cch="Chap 6.2",
            ),
        ],
        naming_rules=[
            NamingRule(
                objet="Étage",
                ifc_class="IfcBuildingStorey",
                ifc_attribute="Name",
                allowed_values=["REZ", "1ER"],
                case_sensitive=True,
                ref_cch="Chap 6.3",
            ),
        ],
        storey_names=[],
        zone_specs=[],
        room_specs=[],
    )


def _audit_result(
    *,
    project: dict | None = None,
    model: dict | None = None,
    sites: list[dict] | None = None,
    buildings: list[dict] | None = None,
    findings: list[Finding] | None = None,
    catalog: RequirementsCatalog | None = None,
    phase: BIMPhase = BIMPhase.PRO,
) -> AuditResult:
    snap = ModelSnapshot(
        project=project or {"name": "Programme Test"},
        model=model or {"name": "TEST.ifc"},
        sites=sites or [],
        buildings=buildings or [],
        storeys=[{"uuid": "F1", "name": "REZ", "type": "IfcBuildingStorey"}],
        spaces=[],
        zones=[],
        elements=[
            {"uuid": "W1", "type": "IfcWallStandardCase", "name": "Mur 01"},
            {"uuid": "W2", "type": "IfcWallStandardCase", "name": "Mur 02"},
        ],
    ).index()
    return AuditResult(
        phase=phase,
        catalog=catalog or _catalog(),
        snapshot=snap,
        findings=findings or [],
    )


# ── ControlDescription ──────────────────────────────────────────────────


class TestControlDescription:
    def test_minimal(self):
        c = ControlDescription(theme="Nommage", objective="Vérifier", checked_items="IfcSpace.Name")
        assert c.theme == "Nommage"
        assert c.rule_source is None

    def test_frozen(self):
        c = ControlDescription(theme="t", objective="o", checked_items="i")
        try:
            c.theme = "altered"  # type: ignore[misc]
        except (AttributeError, ValueError):
            pass
        else:
            raise AssertionError("ControlDescription devrait être frozen")


# ── ReportProjectContext ────────────────────────────────────────────────


class TestReportProjectContext:
    def test_defaults(self):
        ctx = ReportProjectContext()
        assert ctx.project_name is None
        assert ctx.controls_performed == []
        assert ctx.bim_objectives == []
        assert ctx.missing_information == []


# ── build_report_context ────────────────────────────────────────────────


class TestBuildReportContext:
    def test_basic_extraction(self):
        result = _audit_result(
            project={
                "name": "Réhabilitation Liffré",
                "description": "Programme social 24 logements",
            },
            model={"name": "LIFFRE_PRO.ifc"},
            sites=[{"uuid": "S1", "name": "Site Liffré", "type": "IfcSite"}],
            buildings=[{"uuid": "B1", "name": "Bât A", "type": "IfcBuilding"}],
        )
        ctx = build_report_context(result)
        assert ctx.project_name == "Réhabilitation Liffré"
        assert ctx.model_name == "LIFFRE_PRO.ifc"
        assert ctx.project_description == "Programme social 24 logements"
        assert ctx.project_phase == "PRO"
        assert ctx.site_name == "Site Liffré"
        assert ctx.building_name == "Bât A"
        assert ctx.bim_reference == "CCH BIM I3F V3.6"
        assert ctx.cch_version == "3.6"
        # Comptages
        assert ctx.n_elements == 2
        assert ctx.n_storeys == 1
        assert ctx.n_sites == 1
        assert ctx.n_buildings == 1

    def test_controls_performed_minimum_themes(self):
        ctx = build_report_context(_audit_result())
        themes = {c.theme for c in ctx.controls_performed}
        # Le brief CTO demande au minimum les contrôles : classification,
        # nommage, propriétés, spatial.
        assert "Classification IFC" in themes
        assert any("Nommage" in t for t in themes)
        assert "Propriétés attendues" in themes
        assert "Hiérarchie spatiale" in themes

    def test_missing_information_when_no_description(self):
        result = _audit_result(project={"name": "Projet sans description"})
        ctx = build_report_context(result)
        # Description absente → doit apparaître dans missing_information
        assert any("Description du projet" in m for m in ctx.missing_information)

    def test_missing_information_when_no_owner(self):
        result = _audit_result(project={"name": "X"})  # pas de client/owner
        ctx = build_report_context(result)
        assert any("Maîtrise d'ouvrage" in m for m in ctx.missing_information)

    def test_missing_information_when_no_address(self):
        result = _audit_result(project={"name": "X"})
        ctx = build_report_context(result)
        assert any("Adresse" in m for m in ctx.missing_information)

    def test_no_hallucination_owner(self):
        """Le builder ne doit JAMAIS inventer un MOA depuis le nom du
        projet ou un autre champ."""
        result = _audit_result(project={"name": "Projet OPH XYZ"})
        ctx = build_report_context(result)
        # OPH dans le nom — ne doit pas devenir client_name
        assert ctx.client_name is None
        assert ctx.owner_name is None

    def test_owner_from_explicit_project_field(self):
        result = _audit_result(project={"name": "X", "owner": "OPH Rennes Métropole"})
        ctx = build_report_context(result)
        assert ctx.owner_name == "OPH Rennes Métropole"

    def test_bim_objectives_keyword_detection_in_description(self):
        """Si la description du projet mentionne des mots-clés BIM
        explicites, on les remonte ; sinon, liste vide."""
        result = _audit_result(
            project={
                "name": "X",
                "description": ("Programme orienté DOE numérique et exploitation patrimoniale."),
            }
        )
        ctx = build_report_context(result)
        labels = " ".join(ctx.bim_objectives).lower()
        assert "doe numérique" in labels
        assert "exploitation patrimoniale" in labels

    def test_bim_objectives_empty_when_no_match(self):
        result = _audit_result(project={"name": "X", "description": "Bref."})
        ctx = build_report_context(result)
        assert ctx.bim_objectives == []
        # missing_information signale l'absence
        assert any("Objectifs BIM" in m for m in ctx.missing_information)

    def test_address_from_site_long_name(self):
        result = _audit_result(
            sites=[
                {
                    "uuid": "S1",
                    "name": "Site Liffré",
                    "long_name": "12 rue de la Paix, 35340 LIFFRÉ",
                    "type": "IfcSite",
                }
            ]
        )
        ctx = build_report_context(result)
        assert ctx.address == "12 rue de la Paix, 35340 LIFFRÉ"

    def test_phase_extracted(self):
        ctx = build_report_context(_audit_result(phase=BIMPhase.DOE))
        assert ctx.project_phase == "DOE"

    def test_catalog_metadata(self):
        ctx = build_report_context(_audit_result())
        assert ctx.cch_source == "/tmp/cch.pdf"
        assert ctx.data_spec_source == "/tmp/data.xlsx"
        assert ctx.naming_spec_source == "/tmp/naming.xlsx"
        assert ctx.n_property_specs == 1
        assert ctx.n_naming_rules == 1

    def test_missing_when_no_catalog_sources(self):
        result = _audit_result(catalog=_catalog(version=None))
        ctx = build_report_context(result)
        msgs = " ".join(ctx.missing_information)
        assert "Cahier des Charges" in msgs
        assert "Spécifications" in msgs
        assert "Nommage" in msgs

    def test_findings_counter(self):
        findings = [
            Finding(
                theme=Theme.CLASSIFICATION,
                severity=Severity.MEDIUM,
                error_type=ErrorType.CLASSIFICATION_MISSING,
                element_uuid="W1",
                ifc_type="IfcWallStandardCase",
            )
        ]
        ctx = build_report_context(_audit_result(findings=findings))
        assert ctx.n_findings == 1
        # Pas de message "aucun finding" puisque findings > 0
        assert not any("Findings : aucun" in m for m in ctx.missing_information)

    def test_assumptions_includes_perimeter(self):
        ctx = build_report_context(_audit_result())
        assumptions_str = " ".join(ctx.assumptions).lower()
        assert "snapshot" in assumptions_str
        assert "périmètre" in assumptions_str or "perimetre" in assumptions_str
