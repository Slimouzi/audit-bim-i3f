"""C2 (audit profond 2ᵉ passe) — côté consommateur : l'audit **refuse** un snapshot
inexploitable plutôt que de rendre un rapport faussement « modèle vide ».

Le champ ``ModelSnapshot.extraction_errors`` (bim-core v0.1.2) est peuplé par
``bimdata_read.extract_snapshot`` quand une route BIMData échoue ; ``model`` vide
signale une extraction complètement échouée (token expiré, cible injoignable).
"""

from __future__ import annotations

import pytest

from audit_bim.extraction.model_data import ModelSnapshot, assert_snapshot_usable


def test_usable_snapshot_passes():
    snap = ModelSnapshot(model={"name": "M.ifc"}, buildings=[{"uuid": "b1"}]).index()
    assert_snapshot_usable(snap)  # ne lève pas


def test_empty_model_refused():
    snap = ModelSnapshot(model={}, sites=[{"uuid": "s1"}]).index()
    with pytest.raises(ValueError, match="snapshot vide"):
        assert_snapshot_usable(snap)


def test_extraction_errors_refused():
    snap = ModelSnapshot(
        model={"name": "M.ifc"},
        extraction_errors=["get_raw_elements: HTTPError: 401"],
    ).index()
    with pytest.raises(ValueError, match="snapshot partiel"):
        assert_snapshot_usable(snap)


def test_error_message_lists_failed_routes():
    snap = ModelSnapshot(
        model={"name": "M"},
        extraction_errors=["get_zones: Timeout", "get_spaces: HTTPError: 500"],
    ).index()
    with pytest.raises(ValueError, match="get_zones.*get_spaces"):
        assert_snapshot_usable(snap)


# ── status du modèle BIMData (C = Completed seul exploitable) ─────────────────
def test_status_completed_passes():
    snap = ModelSnapshot(model={"name": "M.ifc", "status": "C"}, buildings=[{"uuid": "b1"}]).index()
    assert_snapshot_usable(snap)  # ne lève pas


def test_status_none_passes():
    # Modèle sans champ status (API/mock) → on ne bloque pas là-dessus.
    snap = ModelSnapshot(model={"name": "M.ifc"}, buildings=[{"uuid": "b1"}]).index()
    assert_snapshot_usable(snap)


@pytest.mark.parametrize(
    "status,needle",
    [
        ("D", "supprimé"),
        ("P", "en cours"),
        ("W", "en attente"),
        ("I", "en cours"),
        ("E", "erreur"),
    ],
)
def test_non_completed_status_refused_with_cause(status, needle):
    snap = ModelSnapshot(model={"name": "M.ifc", "status": status}).index()
    with pytest.raises(ValueError, match="non exploitable") as ei:
        assert_snapshot_usable(snap)
    msg = str(ei.value)
    assert f"status={status!r}" in msg
    assert needle in msg
