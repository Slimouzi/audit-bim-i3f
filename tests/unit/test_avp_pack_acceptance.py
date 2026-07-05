"""Acceptation du pack AVP I3F — les **5 annexes non vides** + **charte BIMData**.

Test d'acceptation déterministe (hors-ligne, CI) : sur un snapshot représentatif
(le chemin réel piloté par la maquette, ``sources=None``), le pack doit livrer les
CINQ annexes xlsx avec des lignes métier, toutes habillées de la charte BIMData
(wordmark, primaire ``#2F374A``, police Roboto) et **sans** trace de l'ancienne
charte (KORHUS). Double la garde runtime ``_qa_empty_deliverables`` d'une garantie
de test permanente.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from audit_bim.audit.engine import AuditResult
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.reporting.avp_i3f import (
    AvpQaError,
    _count_business_rows,
    _count_controle_rows,
    write_avp_i3f_report_pack,
)
from audit_bim.reporting.bimdata_brand import WORDMARK
from audit_bim.reporting.theming import BIMDATA_FONT_PRIMARY, BIMDATA_PRIMARY
from audit_bim.requirements.models import BIMPhase, RequirementsCatalog


def _catalog() -> RequirementsCatalog:
    return RequirementsCatalog(
        cch_version="3.6",
        cch_source_pdf="x",
        data_spec_source="x",
        naming_spec_source="x",
        properties=[],
        naming_rules=[],
        storey_names=[],
        zone_specs=[],
        room_specs=[],
    )


def _representative_result() -> AuditResult:
    """Maquette représentative peuplant **les 5 annexes** via le repli snapshot :
    espace (SHAB), zone (Zones/Espaces), mur d'enveloppe au calque réel
    ArchiCAD (Enveloppe), fenêtre + porte (Menuiseries) ; la Grille de contrôle
    (Contrôle) est toujours produite."""
    wall = {
        "uuid": "W1",
        "type": "IfcWall",
        "name": "Mur péri 221",
        "layers": [{"name": "221 - MURS - Extérieurs périphériques.Exndo"}],
        "property_sets": [
            {
                "name": "BaseQuantities",
                "properties": [{"definition": {"name": "NetSideArea"}, "value": 30.0}],
            }
        ],
    }
    window = {
        "uuid": "WIN1",
        "type": "IfcWindow",
        "name": "F25",
        "property_sets": [
            {
                "name": "BaseQuantities",
                "properties": [
                    {"definition": {"name": "Width"}, "value": 0.6},
                    {"definition": {"name": "Height"}, "value": 1.3},
                ],
            }
        ],
    }
    door = {"uuid": "D1", "type": "IfcDoor", "name": "P1"}
    space = {
        "uuid": "S1",
        "type": "IfcSpace",
        "name": "CHAMBRE",
        "longname": "Chambre 01",
        "storey": {"uuid": "ST1", "name": "R+1"},
        "property_sets": [
            {
                "name": "BaseQuantities",
                "properties": [{"definition": {"name": "NetFloorArea"}, "value": 12.98}],
            }
        ],
    }
    zone = {"uuid": "Z1", "type": "IfcZone", "name": "Logement A101", "spaces": ["S1"]}
    snap = ModelSnapshot(
        project={"name": "Programme"},
        model={"name": "M.ifc"},
        storeys=[{"uuid": "ST1", "name": "R+1"}],
        spaces=[space],
        zones=[zone],
        elements=[wall, window, door],
    ).index()
    return AuditResult(phase=BIMPhase.AVP, catalog=_catalog(), snapshot=snap, findings=[])


def _annexes(pack) -> dict[str, Path]:
    """Les 5 annexes xlsx du pack, par libellé métier."""
    return {
        "Contrôle": pack.controle_xlsx,
        "SHAB": pack.shab_xlsx,
        "Zones/Espaces": pack.zones_espaces_xlsx,
        "Enveloppe": pack.enveloppe_xlsx,
        "Menuiseries": pack.menuiseries_xlsx,
    }


def _xml_blob(path: Path) -> bytes:
    with zipfile.ZipFile(path) as z:
        return b"".join(z.read(n) for n in z.namelist() if n.endswith((".xml", ".rels"))).upper()


def _annex_rows(label: str, path: Path) -> int:
    """Compteur adapté : Contrôle a son compteur propre (lignes sous la grille),
    les 4 autres annexes utilisent le compteur générique de lignes métier."""
    return _count_controle_rows(path) if label == "Contrôle" else _count_business_rows(path)


def test_five_annexes_are_non_empty(tmp_path):
    pack = write_avp_i3f_report_pack(
        _representative_result(),
        tmp_path / "out",
        sources=None,
        project_name="X",
        project_code="Y",
        export_pdf=False,
    )
    annexes = _annexes(pack)
    assert len(annexes) == 5
    empty = {label: p.name for label, p in annexes.items() if _annex_rows(label, p) == 0}
    assert not empty, f"annexes vides: {empty}"


def test_charte_bimdata_on_all_five_annexes(tmp_path):
    pack = write_avp_i3f_report_pack(
        _representative_result(),
        tmp_path / "out",
        sources=None,
        project_name="X",
        project_code="Y",
        export_pdf=False,
    )
    wordmark = WORDMARK.encode().upper()
    primary = BIMDATA_PRIMARY.encode().upper()
    font = BIMDATA_FONT_PRIMARY.encode().upper()
    for label, p in _annexes(pack).items():
        blob = _xml_blob(p)
        assert wordmark in blob, f"wordmark BIMDATA absent: {label}"
        assert primary in blob, f"primaire {BIMDATA_PRIMARY} absent: {label}"
        assert font in blob, f"police {BIMDATA_FONT_PRIMARY} absente: {label}"
        assert b"KORHUS" not in blob, f"ancienne charte (KORHUS) trouvée: {label}"


def test_controle_grid_is_populated_from_audit(tmp_path):
    """Sans source I3F « Contrôle », la grille est générée depuis l'AuditResult
    (points de contrôle réels), donc le compteur propre est > 0."""
    pack = write_avp_i3f_report_pack(
        _representative_result(),
        tmp_path / "out",
        sources=None,
        project_name="X",
        project_code="Y",
        export_pdf=False,
    )
    assert _count_controle_rows(pack.controle_xlsx) > 0


def test_qa_gate_flags_truly_empty_controle(tmp_path):
    """Une grille de contrôle **réellement vide** (audit sans point de contrôle
    exploitable) déclenche ``AvpQaError`` — sans monkeypatch du compteur."""
    empty_snap = ModelSnapshot(project={"name": "P"}, model={"name": "M.ifc"}).index()
    result = AuditResult(phase=BIMPhase.AVP, catalog=_catalog(), snapshot=empty_snap, findings=[])
    with pytest.raises(AvpQaError) as exc:
        write_avp_i3f_report_pack(
            result,
            tmp_path / "out",
            sources=None,
            project_name="X",
            project_code="Y",
            export_pdf=False,
        )
    assert "Contrôle" in exc.value.empty
