"""Tests du fix payload size sur ``suggest_classifications``.

Couvre :
- bornes ``limit`` (1..200, défaut 50) et ``top_n`` (1..5, défaut 3),
- compacting (``reasons`` cap 2, ``layers``/``materials`` cap 5),
- dump JSON sous ``AUDIT_OUTPUT_DIR`` via ``output_path`` /
  ``include_full_output``,
- refus hors sandbox / refus écrasement sans ``overwrite=True``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.session import _Session, current_session
from audit_bim.safe_paths import UnsafePathError


@pytest.fixture
def _isolated_session():
    """Bind une session fraîche pour la durée du test."""
    sess = _Session()
    token = current_session.set(sess)
    try:
        yield sess
    finally:
        current_session.reset(token)


@pytest.fixture
def _export_root(tmp_path, monkeypatch):
    """Pointe ``AUDIT_OUTPUT_DIR`` vers un tmp dédié."""
    root = tmp_path / "out"
    root.mkdir()
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(root))
    return root


def _make_suggestion(uuid: str = "u1") -> dict:
    """Forge un item du suggester avec champs verbeux (reasons, layers…)."""
    return {
        "element_uuid": uuid,
        "ifc_type": "IfcWall",
        "name": f"Mur ext {uuid}",
        "layers": [f"Layer{i}" for i in range(10)],
        "materials": [f"Béton-{i}" for i in range(10)],
        "is_external": True,
        "suggestions": [
            {
                "code": "B2010",
                "label": "Exterior Walls",
                "system": "uniformat",
                "confidence": 0.9,
                "reasons": [f"raison-{i}" for i in range(10)],
            },
            {
                "code": "B2020",
                "label": "Windows",
                "system": "uniformat",
                "confidence": 0.6,
                "reasons": [f"alt-raison-{i}" for i in range(10)],
            },
        ],
    }


def _patch_audit_state(session, n_items: int):
    """Pose un ``_State.result`` minimal et stub le suggester.

    Le code accède à ``_State.result.findings`` et ``.snapshot`` avant
    d'appeler le suggester — il faut donc un objet qui répond à ces
    attributs même si on les ignore (le suggester réel est mocké).
    """
    result = MagicMock()
    result.findings = []
    result.snapshot = MagicMock()
    session.result = result


# ── Bornes ──────────────────────────────────────────────────────────────


class TestLimitsClamp:
    def test_default_limit_is_50(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=300)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion(f"u{i}") for i in range(300)]
            res = mcp_server.suggest_classifications()
        assert res["limit"] == 50
        assert res["n_returned"] == 50
        assert res["n_total"] == 300

    def test_limit_20_returns_at_most_20(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=100)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion(f"u{i}") for i in range(100)]
            res = mcp_server.suggest_classifications(limit=20)
        assert res["limit"] == 20
        assert res["n_returned"] == 20
        assert len(res["suggestions"]) == 20

    def test_limit_above_max_is_capped(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=500)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion(f"u{i}") for i in range(500)]
            res = mcp_server.suggest_classifications(limit=9999)
        # Borne haute 200
        assert res["limit"] == 200
        assert res["n_returned"] == 200

    def test_limit_below_min_clamped_to_1(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=5)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion(f"u{i}") for i in range(5)]
            res = mcp_server.suggest_classifications(limit=0)
        assert res["limit"] == 1
        assert res["n_returned"] == 1

    def test_top_n_clamped(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=1)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion("u0")]
            mcp_server.suggest_classifications(top_n=99)
        # Vérifie que la valeur passée au suggester est cappée à 5
        kwargs = mock_sug.call_args.kwargs
        assert kwargs["top_n"] == 5


# ── Compacting ──────────────────────────────────────────────────────────


class TestCompacting:
    def test_compact_caps_reasons_layers_materials(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=1)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion("u0")]
            res = mcp_server.suggest_classifications(compact=True)
        item = res["suggestions"][0]
        # Layers / materials cap 5
        assert len(item["layers"]) == 5
        assert len(item["materials"]) == 5
        # Reasons par suggestion : cap 2
        for sug in item["suggestions"]:
            assert len(sug["reasons"]) <= 2

    def test_non_compact_keeps_full_inline(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=1)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion("u0")]
            res = mcp_server.suggest_classifications(compact=False)
        item = res["suggestions"][0]
        # Sans compactage on retrouve les 10 layers / 10 reasons
        assert len(item["layers"]) == 10
        for sug in item["suggestions"]:
            assert len(sug["reasons"]) == 10


# ── Dump JSON ───────────────────────────────────────────────────────────


class TestJsonDump:
    def test_output_path_writes_json(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=3)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion(f"u{i}") for i in range(3)]
            res = mcp_server.suggest_classifications(output_path="suggestions.json", limit=2)
        assert res["output_path"] is not None
        target = _export_root / "suggestions.json"
        assert target.exists()
        data = json.loads(target.read_text())
        # Le dump est COMPLET (3 items), pas tronqué à limit
        assert len(data) == 3
        # Et NON compacté (10 layers d'origine)
        assert len(data[0]["layers"]) == 10
        # L'inline reste limité à 2 et compacté
        assert res["n_returned"] == 2

    def test_include_full_output_auto_filename(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=2)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion(f"u{i}") for i in range(2)]
            res = mcp_server.suggest_classifications(include_full_output=True)
        assert res["output_path"] is not None
        assert res["output_path"].endswith(".json")
        assert "suggestions_" in res["output_path"]

    def test_output_path_outside_export_dir_refused(
        self, _isolated_session, _export_root, tmp_path
    ):
        _patch_audit_state(_isolated_session, n_items=1)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion("u0")]
            with pytest.raises(UnsafePathError):
                mcp_server.suggest_classifications(output_path=str(tmp_path / "evil.json"))

    def test_existing_output_refused_without_overwrite(self, _isolated_session, _export_root):
        (_export_root / "suggestions.json").write_text("{}")
        _patch_audit_state(_isolated_session, n_items=1)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion("u0")]
            with pytest.raises(UnsafePathError, match="overwrite"):
                mcp_server.suggest_classifications(output_path="suggestions.json")

    def test_existing_output_allowed_with_overwrite(self, _isolated_session, _export_root):
        (_export_root / "suggestions.json").write_text("{}")
        _patch_audit_state(_isolated_session, n_items=1)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion("u0")]
            res = mcp_server.suggest_classifications(output_path="suggestions.json", overwrite=True)
        assert res["output_path"] == str(_export_root / "suggestions.json")


# ── Forme du retour ─────────────────────────────────────────────────────


class TestReturnShape:
    def test_returns_dict_with_expected_keys(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=1)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion("u0")]
            res = mcp_server.suggest_classifications()
        assert isinstance(res, dict)
        for key in ("n_total", "n_returned", "limit", "compact", "output_path", "suggestions"):
            assert key in res, f"Clé absente du retour : {key}"

    def test_default_output_path_is_none(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=1)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = [_make_suggestion("u0")]
            res = mcp_server.suggest_classifications()
        assert res["output_path"] is None

    def test_empty_audit_returns_zero(self, _isolated_session, _export_root):
        _patch_audit_state(_isolated_session, n_items=0)
        with patch("audit_bim.mcp.server.suggest_for_findings") as mock_sug:
            mock_sug.return_value = []
            res = mcp_server.suggest_classifications()
        assert res["n_total"] == 0
        assert res["n_returned"] == 0
        assert res["suggestions"] == []
