"""Tests du module ``audit_bim.doe.reporter``."""

from __future__ import annotations

from audit_bim.doe.models import DoeRecord, Match
from audit_bim.doe.reporter import summarize_matches


def _make_match(strategy: str | None, confidence: float, **kwargs) -> Match:
    rec = DoeRecord(source="/tmp/doe.xlsx", row_index=1, **kwargs)
    if strategy is None:
        return Match(record=rec, reason=kwargs.get("reason", "no match"))
    return Match(
        record=rec,
        ifc_uuid=f"UUID-{strategy}",
        ifc_type="IfcDoor",
        ifc_name="Door 1",
        confidence=confidence,
        strategy=strategy,
    )


def test_empty_input_zero_rate():
    summary = summarize_matches([])
    assert summary["n_records_total"] == 0
    assert summary["match_rate"] == 0


def test_all_matched():
    matches = [
        _make_match("guid", 1.0),
        _make_match("tag", 0.9),
        _make_match("name", 0.85),
    ]
    s = summarize_matches(matches)
    assert s["n_matched"] == 3
    assert s["n_records_total"] == 3
    assert s["match_rate"] == 1.0


def test_ventilation_by_strategy():
    matches = [
        _make_match("guid", 1.0),
        _make_match("guid", 1.0),
        _make_match("tag", 0.9),
    ]
    s = summarize_matches(matches)
    assert s["by_strategy"]["guid"] == 2
    assert s["by_strategy"]["tag"] == 1


def test_confidence_bands():
    matches = [
        _make_match("guid", 1.0),  # ≥0.9
        _make_match("name", 0.8),  # 0.75-0.9
        _make_match("name", 0.65),  # 0.6-0.75
        _make_match("loc", 0.55),  # <0.6
    ]
    s = summarize_matches(matches)
    assert s["by_confidence_band"]["≥0.9"] == 1
    assert s["by_confidence_band"]["0.75–0.9"] == 1
    assert s["by_confidence_band"]["0.6–0.75"] == 1
    assert s["by_confidence_band"]["<0.6"] == 1


def test_unmatched_reasons_counted():
    matches = [
        _make_match(None, 0.0, reason="Aucun indice"),
        _make_match(None, 0.0, reason="Aucun indice"),
        _make_match(None, 0.0, reason="Tag ambigu"),
    ]
    s = summarize_matches(matches)
    assert s["n_unmatched"] == 3
    assert s["top_unmatch_reasons"]["Aucun indice"] == 2
