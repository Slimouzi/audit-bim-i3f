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

from audit_bim.audit.engine import AuditResult
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.reporting import avp_i3f
from audit_bim.reporting.avp_i3f import _count_business_rows, write_avp_i3f_report_pack
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
    empty = {label: p.name for label, p in annexes.items() if _count_business_rows(p) == 0}
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


def test_qa_gate_now_covers_controle(tmp_path, monkeypatch):
    """La 5ᵉ annexe (Contrôle) est désormais gardée par le QA gate anti-vide."""
    result = _representative_result()
    pack = write_avp_i3f_report_pack(
        result,
        tmp_path / "out",
        sources=None,
        project_name="X",
        project_code="Y",
        export_pdf=False,
    )
    real = avp_i3f._count_business_rows
    # Seul le Contrôle est simulé vide → seul « Contrôle » doit être signalé.
    monkeypatch.setattr(
        avp_i3f,
        "_count_business_rows",
        lambda p: 0 if Path(p) == Path(pack.controle_xlsx) else real(p),
    )
    assert avp_i3f._qa_empty_deliverables(pack, result.snapshot) == ["Contrôle"]
