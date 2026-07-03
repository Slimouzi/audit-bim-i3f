"""Provenance opposable des findings préliminaires (MCP ifc-openshell).

Un ``Finding`` sans ``ref_cch`` n'est pas opposable au MOA. Les findings
géométriques importés n'ont pas de chapitre CCH dédié : ils doivent porter
au minimum leur source (audit préliminaire + outil ifc-openshell) et, si
connu, le nom du fichier JSON d'origine.
"""

from __future__ import annotations

from audit_bim.audit.rules.preliminary import load_preliminary_findings

_INVENTORY = {"spaces": [{"guid": "sp1", "name": "CH1", "flags": ["sans_zone"]}]}
_CLASH = {
    "findings": [{"classification": "doublon_piece", "a_guid": "sp2", "a": "CH2", "b": "CH2bis"}]
}


def test_imported_findings_carry_provenance():
    findings = load_preliminary_findings(inventory=_INVENTORY)
    assert findings, "au moins un finding attendu"
    for f in findings:
        assert f.ref_cch, "finding préliminaire sans ref_cch (non opposable)"
        assert "ifc-openshell" in f.ref_cch


def test_provenance_names_the_source_tool_and_file():
    findings = load_preliminary_findings(
        inventory=_INVENTORY,
        source_files={"inventory": "TARARE_space_inventory.json"},
    )
    ref = findings[0].ref_cch
    assert "extract_space_inventory" in ref
    assert "TARARE_space_inventory.json" in ref


def test_provenance_per_source_tool():
    findings = load_preliminary_findings(space_clash=_CLASH)
    assert findings[0].ref_cch and "run_space_clash_audit" in findings[0].ref_cch


def test_provenance_does_not_override_existing_ref_cch():
    # Aucun finding préliminaire ne pose ref_cch aujourd'hui, mais la garde
    # protège un futur finding déjà référencé d'un écrasement silencieux.
    findings = load_preliminary_findings(inventory=_INVENTORY)
    stamped = findings[0].ref_cch
    again = load_preliminary_findings(inventory=_INVENTORY)
    assert again[0].ref_cch == stamped
