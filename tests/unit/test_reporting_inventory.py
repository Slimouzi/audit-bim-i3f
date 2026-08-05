"""L'inventaire de `audit_bim/reporting` doit rester vrai.

`docs/scope-reporting-facade.md` sert de base de décision aux lots R1–R3 : ses
chiffres viennent du code, et doivent le rester. Un document d'inventaire
recopié à la main cesse d'être exact au premier commit — et continue d'être cité
comme s'il l'était.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "scope-reporting-facade.md"

sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def report() -> dict:
    from inventory_reporting_modules import analyse

    return analyse()


def test_the_document_figures_match_the_measurement(report):
    counts = Counter(m["kind"] for m in report["modules"])
    lines = Counter()
    for m in report["modules"]:
        lines[m["kind"]] += m["lines"]

    assert len(report["modules"]) == 24
    assert sum(m["lines"] for m in report["modules"]) == 8231
    assert counts["façade"] == 3 and lines["façade"] == 153
    assert counts["orchestration_i3f"] == 12 and lines["orchestration_i3f"] == 5980

    text = DOC.read_text(encoding="utf-8")
    for claim in ("**8 231 lignes**", "| Façade vers `bim-reporting` | 3 | **153** |", "**1,9 %**"):
        assert claim in text, f"le document ne porte plus : {claim}"


def test_the_three_facades_are_the_ones_named(report):
    """La liste du lot R1, nommément — un compte laisserait un module s'y glisser."""
    facades = {m["module"] for m in report["modules"] if m["kind"] == "façade"}
    assert facades == {"theming.py", "bimdata_brand.py", "pdf_export.py"}

    text = DOC.read_text(encoding="utf-8")
    for module in facades:
        assert f"`{module}`" in text


def test_writing_modules_are_counted_as_claimed(report):
    """Le nombre de modules qui écrivent commande le coût de recette des lots."""
    writers = [m for m in report["modules"] if m["writes_files"]]
    assert len(writers) == 10
    assert sum(m["lines"] for m in writers) == 4973
    assert "**4 973 dans dix modules qui écrivent un fichier**" in DOC.read_text(encoding="utf-8")


def test_avp_snapshot_is_neutral_by_dependency_but_bound_by_use(report):
    """La nuance qui commande le découpage — mesurée, pas supposée.

    Le module est le plus gros bloc sans dépendance I3F ni terme client. Ce
    n'est pas pour autant une brique extractible : tous ses appelants servent le
    pack AVP. Le classer « extractible » promettrait à un second AMO une brique
    dont il n'aurait aucun usage.
    """
    entry = next(m for m in report["modules"] if m["module"] == "avp_snapshot.py")

    assert entry["attaches"] == [] and entry["client_terms"] == []
    assert entry["lines"] == 1057
    assert len(entry["consumers"]) == 6
    assert all("avp" in c or "tools_reporting" in c for c in entry["consumers"]), entry["consumers"]

    text = DOC.read_text(encoding="utf-8")
    assert "il n'existe que pour alimenter le pack AVP" in text
    assert "**Extraire `avp_snapshot.py` vers un socle.**" in text


def test_client_vocabulary_is_measured_in_written_strings_not_docstrings(report):
    """Non-vacuité du signal client — et preuve qu'il ne vient pas des commentaires.

    Le contrôle porte sur les chaînes littérales hors docstrings : ce sont elles
    qui finissent dans une cellule. Sans cette restriction, un module qui *parle*
    du CCH passerait pour un module qui *l'écrit*.
    """
    flagged = {m["module"]: m["client_terms"] for m in report["modules"] if m["client_terms"]}
    assert "avp/docx_analyse.py" in flagged
    assert set(flagged["avp/docx_analyse.py"]) >= {"i3f", "cch", "avp"}

    # Le socle partagé, lui, ne doit rien porter : c'est la contre-épreuve.
    shared = REPO / "audit_bim" / "tools_shared" / "session.py"
    assert shared.exists()
