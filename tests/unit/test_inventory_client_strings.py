"""Smoke test du script d'inventaire — il devient un outil durable.

Sans ça, `scripts/inventory_client_strings.py` pourrirait en silence : ruff le
lint, mais rien ne l'exécute. Or il sert à cadrer les PR d'extraction — un
script qui plante ou qui compte faux oriente la décision, pas juste la doc.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import inventory_client_strings as inv  # noqa: E402


def test_scan_returns_classified_rows():
    rows = inv.scan(inv.REPORTING / "word_report.py")
    assert rows, "aucune occurrence : le script ne trouve plus rien"
    assert {r["context"] for r in rows} <= {"docstring", "comment", "internal", "printed"}
    assert all(r["destination"] for r in rows)


def test_docstrings_and_comments_are_not_counted_as_printed():
    """La distinction est la raison d'être du script : un grep surcompte du double."""
    rows = inv.scan(inv.REPORTING / "word_report.py")
    printed = [r for r in rows if r["context"] == "printed"]
    assert len(printed) < len(rows), "aucune occurrence écartée : la classification ne marche plus"


def test_field_descriptions_are_classified_internal():
    """Un `Field(description=…)` n'atteint jamais le livrable."""
    rows = inv.scan(inv.REPORTING / "context.py")
    assert any(r["context"] == "internal" for r in rows)


def test_word_report_has_no_printed_client_string_left():
    """Après PR C1, le module de rendu ne doit plus rien imprimer de client."""
    rows = inv.scan(inv.REPORTING / "word_report.py")
    printed = [r for r in rows if r["context"] == "printed"]
    assert not printed, f"chaînes client encore imprimées : {printed}"


def test_xlsx_annex_has_no_printed_client_string_left():
    """Après PR C2, le module Excel ne doit plus rien imprimer de client.

    Les deux occurrences visées — en-tête « Référence CCH » et onglet
    « Référentiel I3F » — viennent désormais du profil. Ce test remplace celui
    qui les épinglait pendant C1.
    """
    rows = inv.scan(inv.REPORTING / "xlsx_annex.py")
    printed = [r for r in rows if r["context"] == "printed"]
    assert not printed, f"chaînes client encore imprimées depuis xlsx_annex.py : {printed}"


@pytest.mark.parametrize("name", inv.TARGETS)
def test_every_target_file_is_parsable(name):
    assert inv.scan(inv.REPORTING / name) is not None
