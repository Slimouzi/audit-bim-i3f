"""Lot 3 — fusion des BaseQuantities calculées (gap-only) dans le snapshot."""

from __future__ import annotations

import json

import pytest

from audit_bim.extraction.computed_quantities import (
    json_digest,
    load_computed_quantities,
    merge_into_snapshot,
)
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import tools_query, tools_session
from audit_bim.mcp.session import _Session, current_session


def _qty(gid, quantity, value, *, status="computed", qto="Qto_SpaceBaseQuantities", cls="IfcSpace"):
    return {
        "global_id": gid,
        "ifc_class": cls,
        "qto": qto,
        "quantity": quantity,
        "value": value,
        "unit": "m2",
        "method": "ifcopenshell_geometry",
        "status": status,
        "source": "computed_ifcopenshell",
    }


def _snapshot():
    # S1 sans NetFloorArea (gap → merge) ; S2 avec NetFloorArea=99 (native → gardée).
    s1 = {"uuid": "S1", "type": "IfcSpace", "name": "CH1", "property_sets": []}
    s2 = {
        "uuid": "S2",
        "type": "IfcSpace",
        "name": "CH2",
        "property_sets": [
            {
                "name": "Qto_SpaceBaseQuantities",
                "properties": [{"definition": {"name": "NetFloorArea"}, "value": 99.0}],
            }
        ],
    }
    return ModelSnapshot(elements=[s1, s2]).index()


def _doc(quantities):
    return {"schema": "computed_base_quantities/v1", "quantities": quantities}


# ── merge_into_snapshot ─────────────────────────────────────────────────


def test_gap_only_injects_missing_keeps_existing():
    snap = _snapshot()
    doc = _doc([_qty("S1", "NetFloorArea", 12.3), _qty("S2", "NetFloorArea", 4.0)])
    cov = merge_into_snapshot(snap, doc)
    # S1 comblé, S2 conservé.
    from audit_bim.reporting.avp_snapshot import _base_quantity_ordered

    assert _base_quantity_ordered(snap.element_by_uuid["S1"], ("NetFloorArea",)) == 12.3
    assert _base_quantity_ordered(snap.element_by_uuid["S2"], ("NetFloorArea",)) == 99.0
    assert cov["n_merged"] == 1 and cov["n_gap_kept"] == 1


def test_unknown_global_id_ignored_with_warning():
    snap = _snapshot()
    cov = merge_into_snapshot(snap, _doc([_qty("ZZZ", "NetFloorArea", 5.0)]))
    assert cov["n_unknown_uuid"] == 1 and cov["n_merged"] == 0
    assert any("ZZZ" in w for w in cov["warnings"])


def test_skipped_and_failed_entries_ignored():
    snap = _snapshot()
    doc = _doc(
        [
            _qty("S1", "GrossFloorArea", None, status="skipped"),
            _qty("S1", "NetFloorArea", None, status="failed"),
        ]
    )
    cov = merge_into_snapshot(snap, doc)
    assert cov["n_merged"] == 0 and cov["n_skipped_status"] == 2
    assert snap.element_by_uuid["S1"].get("computed_base_quantities") is None


def test_provenance_recorded_per_value():
    snap = _snapshot()
    merge_into_snapshot(snap, _doc([_qty("S1", "NetFloorArea", 12.3)]))
    prov = snap.element_by_uuid["S1"]["computed_base_quantities"]
    assert prov[0]["source"] == "computed_ifcopenshell"
    assert prov[0]["method"] == "ifcopenshell_geometry"
    assert prov[0]["unit"] == "m2"
    assert prov[0]["value"] == 12.3


# ── load_computed_quantities (validation) ───────────────────────────────


def test_schema_mismatch_refused(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema": "other/v9", "quantities": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="Schéma inattendu"):
        load_computed_quantities(p)


def test_missing_json_refused(tmp_path):
    with pytest.raises(ValueError, match="introuvable"):
        load_computed_quantities(tmp_path / "nope.json")


def test_json_digest_changes_with_content(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text('{"schema":"computed_base_quantities/v1","quantities":[]}', encoding="utf-8")
    b.write_text('{"schema":"computed_base_quantities/v1","quantities":[1]}', encoding="utf-8")
    assert json_digest(a) != json_digest(b)


# ── extract_model_snapshot + get_object_detail (tool level) ─────────────


@pytest.fixture
def _session(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_INPUT_DIR", str(tmp_path))
    sess = _Session()
    sess.cloud_id, sess.project_id, sess.model_id = "34140", "3281472", "1744246"
    sess.client = object()  # ensure_client passe (client non-None)
    token = current_session.set(sess)
    # extract_snapshot renvoie un snapshot synthétique frais à chaque appel.
    monkeypatch.setattr(tools_session, "extract_snapshot", lambda client: _snapshot())
    try:
        yield sess, tmp_path
    finally:
        current_session.reset(token)


def _write_json(tmp_path, name, quantities):
    p = tmp_path / name
    p.write_text(json.dumps(_doc(quantities)), encoding="utf-8")
    return str(p)


def test_compute_false_leaves_history_unchanged(_session):
    _sess, _tmp = _session
    out = tools_session.extract_model_snapshot(use_cache=False)
    assert "computed_quantities" not in out


def test_compute_true_requires_json(_session):
    with pytest.raises(ValueError, match="exige `computed_quantities_json`"):
        tools_session.extract_model_snapshot(use_cache=False, compute_missing_quantities=True)


def test_compute_merges_and_exposes_cache_key(_session):
    _sess, tmp = _session
    jp = _write_json(tmp, "c.json", [_qty("S1", "NetFloorArea", 12.3)])
    out = tools_session.extract_model_snapshot(
        use_cache=False, compute_missing_quantities=True, computed_quantities_json=jp
    )
    cq = out["computed_quantities"]
    assert cq["schema"] == "computed_base_quantities/v1"
    assert cq["n_merged"] == 1 and "compute" in cq["cache_key"]


def test_cache_key_invalidated_when_json_changes(_session):
    _sess, tmp = _session
    j1 = _write_json(tmp, "c1.json", [_qty("S1", "NetFloorArea", 12.3)])
    j2 = _write_json(tmp, "c2.json", [_qty("S1", "NetFloorArea", 55.5)])
    o1 = tools_session.extract_model_snapshot(
        use_cache=False, compute_missing_quantities=True, computed_quantities_json=j1
    )
    o2 = tools_session.extract_model_snapshot(
        use_cache=False, compute_missing_quantities=True, computed_quantities_json=j2
    )
    assert o1["computed_quantities"]["cache_key"] != o2["computed_quantities"]["cache_key"]
    # Le snapshot reflète bien la nouvelle valeur (fusion ré-appliquée, pas de stale).
    from audit_bim.reporting.avp_snapshot import _base_quantity_ordered

    assert _base_quantity_ordered(_sess.snapshot.element_by_uuid["S1"], ("NetFloorArea",)) == 55.5


def test_get_object_detail_exposes_value_and_provenance(_session):
    _sess, tmp = _session
    jp = _write_json(tmp, "c.json", [_qty("S1", "NetFloorArea", 12.3)])
    tools_session.extract_model_snapshot(
        use_cache=False, compute_missing_quantities=True, computed_quantities_json=jp
    )
    obj = tools_query.get_object_detail("S1")["object"]
    assert obj["base_quantities"]["NetFloorArea"] == 12.3
    prov = obj["computed_base_quantities"]
    assert prov[0]["source"] == "computed_ifcopenshell" and prov[0]["value"] == 12.3
