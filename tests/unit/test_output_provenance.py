"""Provenance written into produced artifacts must use the generic product name."""

from __future__ import annotations

from pathlib import Path

from bim_publication.bcf import ORIGINATING_SYSTEM as PUBLICATION_ORIGINATING_SYSTEM

from audit_bim.actions.doe_planner import _build_pset_payload as build_plan_pset_payload
from audit_bim.audit.engine import AuditResult
from audit_bim.doe.enricher import _build_pset_payload as build_apply_pset_payload
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.provenance import ORIGINATING_SYSTEM
from audit_bim.reporting.avp.xlsx_controle import _audit_controle_table, _controle_rows_for_moa
from audit_bim.reporting.avp_sources import SheetTable
from audit_bim.requirements.models import BIMPhase

REPO = Path(__file__).resolve().parents[2]
OLD_ORIGIN = "audit-bim-i3f"
EXPECTED_ORIGIN = "audit-bim-mcp"


def test_output_provenance_is_shared_with_bim_publication():
    assert ORIGINATING_SYSTEM == PUBLICATION_ORIGINATING_SYSTEM == EXPECTED_ORIGIN


def test_doe_pset_payloads_write_current_originating_system():
    for build in (build_plan_pset_payload, build_apply_pset_payload):
        payload = build("Pset_Documentation", {"Indice": "A"})
        assert EXPECTED_ORIGIN in payload["description"]
        assert OLD_ORIGIN not in payload["description"]


def test_controle_rows_from_source_grid_write_current_originating_system():
    source = SheetTable(
        title="Grille",
        headers=["TOTAL", "CONFORME", "NON CONFORME", "%"],
        rows=[["Zones Nommage", 1, 1, 0, 1.0]],
    )

    row = _controle_rows_for_moa(source)[0]

    assert row[2] == f"Contrôle automatisé MCP {EXPECTED_ORIGIN}"


def test_controle_rows_from_audit_result_write_current_originating_system():
    snapshot = ModelSnapshot(spaces=[{"uuid": "S1", "name": "Pièce"}]).index()
    result = AuditResult(phase=BIMPhase.AVP, catalog=None, snapshot=snapshot, findings=[])

    table = _audit_controle_table(result)

    assert table is not None
    assert table.rows[0][2] == f"Contrôle automatisé MCP {EXPECTED_ORIGIN}"


def test_active_output_provenance_no_longer_mentions_old_distribution():
    active_outputs = [
        "audit_bim/actions/doe_planner.py",
        "audit_bim/doe/enricher.py",
        "audit_bim/reporting/avp/xlsx_controle.py",
        "tests/unit/golden/bcf_payloads.json",
        "tests/unit/golden/prepare_bcf.json",
    ]

    offenders = [
        path for path in active_outputs if OLD_ORIGIN in (REPO / path).read_text(encoding="utf-8")
    ]

    assert not offenders
