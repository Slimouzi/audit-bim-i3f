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
