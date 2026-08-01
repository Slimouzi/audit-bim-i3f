"""Le pack résout lui-même ses contrats géométriques (mode « self-healing »).

Le tool ne doit pas dépendre d'une consigne : si les ``BaseQuantities``
manquent, il retrouve ou calcule le contrat
``computed_base_quantities/v1``, le fusionne, puis génère. Idem pour
``envelope_quantities/v1``.

Le calcul est appelé comme une **fonction Python** (``geometry_backend``), pas
via un second serveur MCP : un import est déterministe, testable, et ne dépend
pas de ce que le harnais a énuméré au démarrage. Ces tests substituent donc le
backend — sans avoir besoin d'ifcopenshell.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit_bim.extraction.geometry_backend import GeometryBackendUnavailable
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.session import _Session, current_session
from audit_bim.reporting import avp_autocompute


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_INPUT_DIR", str(tmp_path))
    sess = _Session()
    sess.snapshot = _snapshot_sans_quantites()
    token = current_session.set(sess)
    try:
        yield sess, tmp_path
    finally:
        current_session.reset(token)


def _snapshot_sans_quantites() -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": "Dieppe"},
        model={"name": "DIEPPE-7427L.ifc"},
        spaces=[
            {"uuid": "SP1", "type": "IfcSpace", "name": "SEJOUR", "longname": "SEJOUR"},
            {"uuid": "SP2", "type": "IfcSpace", "name": "CHAMBRE", "longname": "CHAMBRE"},
        ],
        elements=[
            {"uuid": "W1", "type": "IfcWindow", "name": "F25"},
            {"uuid": "SL1", "type": "IfcSlab", "name": "Dalle"},
        ],
    ).index()


def _payload(valeur_espace=24.5):
    return {
        "schema": "computed_base_quantities/v1",
        "source": {"producer": "ifc-geometry", "tool": "export_computed_base_quantities"},
        "created_at": "2026-08-02T08:00:00+00:00",
        "quantities": [
            _q("SP1", "IfcSpace", "Qto_SpaceBaseQuantities", "NetFloorArea", valeur_espace),
            _q("SP2", "IfcSpace", "Qto_SpaceBaseQuantities", "NetFloorArea", 12.98),
            _q("W1", "IfcWindow", "Qto_WindowBaseQuantities", "Width", 0.6),
            _q("W1", "IfcWindow", "Qto_WindowBaseQuantities", "Height", 1.3),
            _q("SL1", "IfcSlab", "Qto_SlabBaseQuantities", "NetArea", 156.4),
        ],
        "coverage": {"n_elements": 4, "n_computed": 5, "n_failed": 0},
        "warnings": [],
    }


def _q(gid, cls, qto, name, value):
    return {
        "global_id": gid,
        "ifc_class": cls,
        "qto": qto,
        "quantity": name,
        "value": value,
        "unit": "m2" if "Area" in name else "m",
        "method": "geometry",
        "status": "computed",
        "source": "computed_ifcopenshell",
    }


@pytest.fixture
def ifc_disponible(session):
    """Un .ifc du modèle actif, présent dans le dossier d'entrée."""
    _sess, tmp_path = session
    fichier = tmp_path / "DIEPPE-7427L.ifc"
    fichier.write_text("ISO-10303-21;", encoding="utf-8")
    return fichier


@pytest.fixture
def backend(monkeypatch):
    """Substitue le calcul géométrique et compte les appels réels."""
    appels = {"quantites": 0, "enveloppe": 0, "valeur": 24.5}

    def _quantites(ifc_path):
        appels["quantites"] += 1
        return _payload(appels["valeur"])

    def _enveloppe(ifc_path, **kw):
        appels["enveloppe"] += 1
        return {
            "schema": "envelope_quantities/v1",
            "source": {"producer": "ifc-geometry"},
            "created_at": "2026-08-02T08:00:00+00:00",
            "summary": {"superficie_facades_m2": 2071.18, "shab_m2": 2164.68},
            "par_type": [
                {"type": "ME_36", "etages": ["RDC"], "net_side_area_m2": 2071.18, "n": 24}
            ],
            "hors_filtre_type": [],
            "diagnostics": {},
        }

    monkeypatch.setattr(avp_autocompute, "compute_quantities_payload", _quantites)
    monkeypatch.setattr(avp_autocompute, "compute_envelope_payload", _enveloppe)
    return appels


def _generer(**kw):
    return mcp_server.generate_avp_i3f_pack(
        project_name="Dieppe",
        project_code="7427L",
        phase="APD",
        auditor_name="Stanislas Limouzi",
        export_pdf=False,
        **kw,
    )


def _nombres(path):
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    vals = [
        c
        for ws in wb.worksheets
        for row in ws.iter_rows(values_only=True)
        for c in row
        if isinstance(c, (int, float)) and not isinstance(c, bool)
    ]
    wb.close()
    return vals


def _annexe(res, libelle):
    return next(p for p in res["paths"] if libelle in Path(p).name)


# ── cas nominal : aucune consigne, le pack se soigne tout seul ──────────


def test_pack_computes_quantities_by_default(session, ifc_disponible, backend):
    """L'API cible : ni ``computed_quantities_json`` ni étape préalable."""
    res = _generer()

    assert res.get("status") not in ("error", "needs_context"), res
    assert backend["quantites"] == 1
    auto = res["auto_computed"]["quantities"]
    assert auto["computed"] is True
    assert auto["reused"] is False
    assert Path(auto["json_path"]).is_file()


@pytest.mark.parametrize(
    ("libelle", "attendue"),
    [
        ("export SHAB maquette", 24.5),
        ("Export Zones et Espaces", 12.98),
        ("export Menuiseries", 0.6),
        ("export plancher", 156.4),
    ],
)
def test_annexes_are_filled_after_autocompute(session, ifc_disponible, backend, libelle, attendue):
    res = _generer()
    assert res.get("status") not in ("error", "needs_context"), res

    nombres = _nombres(_annexe(res, libelle))
    assert any(abs(n - attendue) < 0.01 for n in nombres), (
        f"{attendue} absente de « {libelle} » (valeurs : {sorted(set(nombres))[:10]})"
    )


# ── réutilisation vs recalcul ──────────────────────────────────────────


def test_existing_contract_is_reused_without_recomputing(session, ifc_disponible, backend):
    premier = _generer()
    assert premier.get("status") not in ("error", "needs_context"), premier
    assert backend["quantites"] == 1

    second = _generer()
    assert second.get("status") not in ("error", "needs_context"), second
    assert backend["quantites"] == 1, "un contrat déjà calculé ne doit pas être recalculé"
    assert second["auto_computed"]["quantities"]["reused"] is True


def test_force_recompute_replaces_the_contract(session, ifc_disponible, backend):
    premier = _generer()
    chemin = Path(premier["auto_computed"]["quantities"]["json_path"])
    assert backend["quantites"] == 1

    backend["valeur"] = 99.9  # la maquette a changé
    second = _generer(force_recompute_quantities=True)

    assert backend["quantites"] == 2
    assert second["auto_computed"]["quantities"]["reused"] is False
    doc = json.loads(chemin.read_text(encoding="utf-8"))
    valeurs = [q["value"] for q in doc["quantities"] if q["global_id"] == "SP1"]
    assert valeurs == [99.9], "le contrat doit être remplacé, pas conservé"

    nombres = _nombres(_annexe(second, "export SHAB maquette"))
    assert any(abs(n - 99.9) < 0.01 for n in nombres)


# ── impossibilité : demande CIBLÉE, jamais vague ───────────────────────


def test_missing_ifc_asks_for_ifc_path(session, backend):
    """Aucun .ifc : la question porte sur ``ifc_path``, pas sur « les quantités »."""
    res = _generer()

    assert res["status"] == "needs_context"
    assert res["error"] == "cannot_compute_quantities"
    assert res["missing"] == ["ifc_path"]
    assert "download_model_ifc" in res["message"]
    assert backend["quantites"] == 0


def test_missing_backend_names_the_backend(session, ifc_disponible, monkeypatch):
    """Backend non installé : le message nomme le paquet et l'extra."""

    def _absent(*_a, **_k):
        raise GeometryBackendUnavailable()

    monkeypatch.setattr(avp_autocompute, "compute_quantities_payload", _absent)

    res = _generer()

    assert res["status"] == "needs_context"
    assert res["missing"] == ["geometry_backend"]
    assert "ifc-geometry-mcp" in res["message"]


def test_no_deliverable_written_when_autocompute_fails(session, tmp_path, backend):
    """Un échec d'auto-résolution ne laisse aucun livrable derrière lui."""
    res = _generer(output_dir="pack_echec")

    assert res["status"] == "needs_context"
    livrables = list(Path(tmp_path).rglob("*.xlsx")) + list(Path(tmp_path).rglob("*.docx"))
    assert livrables == [], f"livrables écrits malgré l'échec : {livrables}"


def test_autocompute_can_be_disabled(session, ifc_disponible, backend):
    """``auto_compute_quantities=False`` restaure le refus explicite."""
    res = _generer(auto_compute_quantities=False, auto_compute_envelope=False)

    assert res["status"] == "error"
    assert res["error"] == "missing_quantities"
    assert backend["quantites"] == 0


# ── enveloppe ──────────────────────────────────────────────────────────


def test_envelope_is_not_computed_when_not_expected(session, ifc_disponible, backend):
    """Sans mur d'enveloppe dans la maquette, aucun calcul n'est lancé."""
    res = _generer()

    assert res.get("status") not in ("error", "needs_context"), res
    assert backend["enveloppe"] == 0
    assert res["auto_computed"]["envelope"] is None


def test_envelope_is_computed_when_walls_are_present(session, ifc_disponible, backend):
    sess, _ = session
    snap = sess.snapshot
    snap.elements.append(
        {
            "uuid": "M1",
            "type": "IfcWall",
            "name": "Mur",
            "layers": [{"name": "221 - MURS - Extérieurs périphériques.Exndo"}],
        }
    )
    sess.snapshot = snap.index()

    res = _generer()

    assert res.get("status") not in ("error", "needs_context"), res
    assert backend["enveloppe"] == 1
    assert res["auto_computed"]["envelope"]["computed"] is True


def test_empty_envelope_decomposition_is_an_explicit_error(session, ifc_disponible, monkeypatch):
    """Aucun type retenu → erreur nommant les motifs, pas une annexe vide."""
    sess, _ = session
    snap = sess.snapshot
    snap.elements.append(
        {
            "uuid": "M1",
            "type": "IfcWall",
            "name": "Mur",
            "layers": [{"name": "221 - MURS - Extérieurs périphériques.Exndo"}],
        }
    )
    sess.snapshot = snap.index()

    monkeypatch.setattr(
        avp_autocompute,
        "compute_envelope_payload",
        lambda *_a, **_k: {
            "schema": "envelope_quantities/v1",
            "summary": {"superficie_facades_m2": 0.0, "shab_m2": 0.0},
            "par_type": [],
            "hors_filtre_type": [],
        },
    )
    monkeypatch.setattr(avp_autocompute, "compute_quantities_payload", lambda *_a, **_k: _payload())

    res = _generer()

    assert res["status"] == "needs_context"
    assert res["error"] == "cannot_compute_envelope"
    assert res["missing"] == ["envelope_layer_pattern"]
    assert "^ME[ _]" in res["message"]


# ── orchestrateur, testé directement ───────────────────────────────────


def test_ensure_reuses_then_recomputes(session, ifc_disponible, backend):
    sess, _ = session
    premier = avp_autocompute.ensure_computed_quantities_json(sess.snapshot)
    assert premier["computed"] is True

    second = avp_autocompute.ensure_computed_quantities_json(sess.snapshot)
    assert second["reused"] is True
    assert backend["quantites"] == 1

    force = avp_autocompute.ensure_computed_quantities_json(sess.snapshot, force=True)
    assert force["computed"] is True
    assert backend["quantites"] == 2


def test_contract_is_written_under_the_export_sandbox(session, ifc_disponible, backend):
    sess, tmp_path = session
    res = avp_autocompute.ensure_computed_quantities_json(sess.snapshot)

    chemin = Path(res["json_path"])
    assert chemin.is_file()
    assert avp_autocompute.CONTRACTS_SUBDIR in chemin.parts
    assert str(chemin).startswith(str(tmp_path)), "le contrat doit rester sous AUDIT_OUTPUT_DIR"
