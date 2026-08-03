"""Le mode de filtrage d'enveloppe est pilotable depuis le tool, sans bricolage.

La recette Dieppe a d'abord été obtenue en filtrant **à la main** le contrat
``envelope.json`` produit par le backend : un résultat juste, mais non
reproductible par le produit — donc inutilisable pour un livrable client.

Ces tests verrouillent le chemin paramétrique de bout en bout :
``generate_avp_i3f_pack(envelope_filter_mode=…, envelope_type_pattern=…)``
atteint le backend, et un mode incohérent est refusé au lieu de se dégrader.

Ils verrouillent aussi la **note de lecture** : en façade Revit multicouche, les
baies sont portées par le mur porteur et non par la peau retenue comme façade.
La colonne « ouvertures » du livrable est alors nulle sur toutes les lignes face
à un total non nul — sans explication, cela se lit comme un défaut de calcul.
"""

from __future__ import annotations

import json

import pytest

from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.session import _Session, current_session
from audit_bim.reporting import avp_autocompute
from audit_bim.reporting.avp.xlsx_enveloppe import _note_menuiseries
from audit_bim.reporting.avp_sources import read_envelope_json

PERIMETRE_AVANT_FILTRE = "murs_exterieurs_avant_filtre_type"


def _contrat(**diagnostics):
    return {
        "schema": "envelope_quantities/v1",
        "source": {"producer": "ifc-geometry", "ifc_file": "DIEPPE-7427L.ifc"},
        "created_at": "2026-08-03T08:00:00+00:00",
        "summary": {
            "superficie_facades_m2": 2206.19,
            "superficie_facades_nette_m2": 2206.19,
            "superficie_menuiseries_m2": 375.89,
            "shab_m2": 2392.64,
            "ratio_fac_shab": 0.9221,
            "methode_facade": "geometric_type_filter",
        },
        "par_type": [
            {
                "type": "Mur de base:MUR ENDUIT 20 mm",
                "etages": ["RDC"],
                "net_side_area_m2": 900.13,
                "n": 54,
                "menuiseries_m2": 0.0,
            }
        ],
        "hors_filtre_type": [
            {
                "type": "Mur de base:BETON 200mm",
                "etages": ["RDC"],
                "net_side_area_m2": 4001.30,
                "n": 279,
            }
        ],
        "diagnostics": diagnostics,
    }


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_INPUT_DIR", str(tmp_path))
    sess = _Session()
    sess.snapshot = ModelSnapshot(
        project={"name": "MCP_Audit"},
        model={"name": "DIEPPE-7427L.ifc"},
        elements=[{"uuid": "W1", "type": "IfcWall", "name": "Mur de base:MUR ENDUIT 20 mm"}],
    ).index()
    token = current_session.set(sess)
    try:
        yield sess, tmp_path
    finally:
        current_session.reset(token)


# ── le mode traverse bien tool -> autocompute -> backend ───────────────


def test_filter_mode_reaches_the_geometry_backend(session, tmp_path, monkeypatch):
    """Sans cette transmission, le mode resterait un paramètre décoratif."""
    recu = {}

    def _fake(ifc_path, **kw):
        recu.update(kw)
        return _contrat()

    monkeypatch.setattr(avp_autocompute, "compute_envelope_payload", _fake)
    ifc = tmp_path / "DIEPPE-7427L.ifc"
    ifc.write_text("ISO-10303-21;", encoding="utf-8")

    mcp_server.generate_avp_i3f_pack(
        project_name="Dieppe",
        project_code="7427L",
        phase="APD",
        auditor_name="Stanislas Limouzi",
        envelope_filter_mode="geometric_type_filter",
        envelope_type_pattern=r"MUR ENDUIT|BARDAGE BOIS|ZINC|VERRE REGLIT",
        auto_compute_quantities=False,
        ifc_path=str(ifc),
        export_pdf=False,
    )

    assert recu["filter_mode"] == "geometric_type_filter"
    assert recu["type_pattern"] == r"MUR ENDUIT|BARDAGE BOIS|ZINC|VERRE REGLIT"
    assert recu["layer_pattern"] is None


def test_incoherent_filter_mode_is_refused_not_degraded(session, tmp_path, monkeypatch):
    """Le backend refuse ; le tool traduit en erreur d'appel, pas en exception."""

    def _fake(ifc_path, **kw):
        raise ValueError("``filter_mode='geometric_type_filter'`` exige ``type_pattern``")

    monkeypatch.setattr(avp_autocompute, "compute_envelope_payload", _fake)
    ifc = tmp_path / "DIEPPE-7427L.ifc"
    ifc.write_text("ISO-10303-21;", encoding="utf-8")

    res = mcp_server.generate_avp_i3f_pack(
        project_name="Dieppe",
        project_code="7427L",
        phase="APD",
        auditor_name="Stanislas Limouzi",
        envelope_filter_mode="geometric_type_filter",
        auto_compute_quantities=False,
        ifc_path=str(ifc),
        export_pdf=False,
    )

    assert res["status"] == "error"
    assert res["error"] == "invalid_envelope_filter_mode"
    assert res["envelope_filter_mode"] == "geometric_type_filter"
    assert "type_pattern" in res["message"]


# ── la note de lecture des menuiseries ─────────────────────────────────


def test_envelope_source_carries_the_menuiserie_scope(tmp_path):
    chemin = tmp_path / "env.json"
    chemin.write_text(
        json.dumps(
            _contrat(
                menuiseries_perimetre=PERIMETRE_AVANT_FILTRE,
                menuiseries_m2_sur_types_rejetes=375.89,
            )
        ),
        encoding="utf-8",
    )

    src = read_envelope_json(chemin)

    assert src.menuiseries_perimetre == PERIMETRE_AVANT_FILTRE
    assert src.menuiseries_sur_types_rejetes == pytest.approx(375.89)


def test_note_explains_a_zero_openings_column(tmp_path):
    chemin = tmp_path / "env.json"
    chemin.write_text(
        json.dumps(
            _contrat(
                menuiseries_perimetre=PERIMETRE_AVANT_FILTRE,
                menuiseries_m2_sur_types_rejetes=375.89,
            )
        ),
        encoding="utf-8",
    )

    note = _note_menuiseries(read_envelope_json(chemin))

    assert note is not None
    assert "375.89" in note or "375,89" in note.replace(".", ",")
    assert "mur porteur" in note


def test_no_note_when_the_openings_are_attributed_to_kept_types(tmp_path):
    """Rien à expliquer sur une maquette ArchiCAD : pas de bruit inutile."""
    chemin = tmp_path / "env.json"
    chemin.write_text(
        json.dumps(
            _contrat(
                menuiseries_perimetre=PERIMETRE_AVANT_FILTRE,
                menuiseries_m2_sur_types_rejetes=0.0,
            )
        ),
        encoding="utf-8",
    )

    assert _note_menuiseries(read_envelope_json(chemin)) is None


def test_no_note_when_the_producer_says_nothing(tmp_path):
    """Contrat d'un producteur antérieur : aucune régression, aucune note."""
    chemin = tmp_path / "env.json"
    chemin.write_text(json.dumps(_contrat()), encoding="utf-8")

    src = read_envelope_json(chemin)

    assert src.menuiseries_perimetre is None
    assert _note_menuiseries(src) is None
