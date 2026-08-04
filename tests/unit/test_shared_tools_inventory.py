"""L'inventaire du socle partagé doit rester vrai (E6).

`docs/scope-shared-tools.md` sert de base de décision pour E7 : ses chiffres
doivent venir du code, et le rester. Un document d'inventaire recopié à la main
cesse d'être exact au premier commit suivant, sans que rien ne le signale — et
il continue d'être cité comme s'il l'était.

Ces tests verrouillent aussi les **deux corrections de méthode** qui ont changé
le résultat pendant l'analyse. Chacune avait produit un classement faux dans un
sens différent, et aucune des deux ne se voyait dans le total.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "scope-shared-tools.md"

sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def report() -> dict:
    from inventory_shared_tools import analyse

    return analyse()


def test_the_inventory_covers_every_tool_of_the_profile(report):
    assert len(report["tools"]) == 45


def test_the_document_figures_match_the_measurement(report):
    """Les nombres du document sortent du script, pas d'une relecture."""
    counts = Counter(t["category"] for t in report["tools"])
    autonomous = [
        t for t in report["tools"] if t["category"] == "extractible" and not t["requires_upstream"]
    ]
    upstream = [
        t for t in report["tools"] if t["category"] == "extractible" and t["requires_upstream"]
    ]

    assert counts["extractible"] == 33
    assert counts["parametrable"] == 0
    assert counts["i3f"] == 12
    assert len(autonomous) == 25
    assert len(upstream) == 8

    text = DOC.read_text(encoding="utf-8")
    for claim in (
        "| **Extractibles** | 33 |",
        "| **Irréductiblement I3F** | 12 |",
        "**25 outils extractibles et autonomes**",
        "### Les 25 extractibles autonomes",
    ):
        assert claim in text, f"le document ne porte plus : {claim}"


def test_the_document_lists_the_right_upstream_bound_tools(report):
    """Les 8 outils suspendus à un amont sont nommés — un compte ne suffit pas."""
    measured = {
        t["tool"]
        for t in report["tools"]
        if t["category"] == "extractible" and t["requires_upstream"]
    }
    text = DOC.read_text(encoding="utf-8")
    section = text[text.index("suspendus à un amont") : text.index("**12 outils I3F**")]
    cited = set(re.findall(r"`([a-z_]+)`", section))
    assert cited == measured, f"document {sorted(cited)} vs mesure {sorted(measured)}"


def test_the_ten_proven_neutral_modules_come_from_the_second_profile(report):
    """La seule liste du dossier qui ne soit pas un jugement."""
    proven = set(report["proven_neutral_modules"])
    assert len(proven) == 10, sorted(proven)
    for module in (
        "audit_bim.extraction.snapshot_health",
        "audit_bim.mcp.model_identity",
        "audit_bim.safe_paths",
    ):
        assert module in proven


# ── Les deux corrections de méthode, verrouillées ─────────────────────


def _entry(report: dict, name: str) -> dict:
    return next(t for t in report["tools"] if t["tool"] == name)


def test_writing_a_session_field_is_not_a_dependency(report):
    """`set_active_model` écrit `_State.result = None` : ce n'est pas un besoin.

    En comptant les écritures, l'outil par lequel on **commence** était classé
    « exige un audit en amont » — l'inverse exact de ce que la ligne signifie.
    """
    entry = _entry(report, "set_active_model")
    assert entry["requires_upstream"] is False
    assert "result" not in entry["upstream_state_fields"]

    # Non-vacuité : un outil qui le **lit** doit, lui, être marqué.
    assert _entry(report, "query_findings")["requires_upstream"] is True


def test_a_dependency_hidden_in_a_helper_is_still_found(report):
    """`generate_xlsx_annex` n'atteint `_State.phase` qu'à travers un helper.

    Sans fermeture transitive sur les fonctions du même module, il passait pour
    neutre : la dépendance existait, une ligne plus bas. C'est le cas qui a fait
    tomber la catégorie « paramétrable » de 1 à 0.
    """
    entry = _entry(report, "generate_xlsx_annex")
    assert entry["category"] == "i3f"
    assert "_default_output_paths" in entry["helpers_followed"]
    assert entry["i3f_state_fields"] == ["phase"]

    # Et le document annonce bien cette attache comme ténue — un nom de fichier.
    assert "dans un nom de fichier" in DOC.read_text(encoding="utf-8")


def test_the_lexical_approach_would_have_been_wrong(report):
    """Preuve que la mesure par AST n'était pas un excès de zèle.

    `filter_bim_objects` contient « CCH » dans sa docstring et ne dépend de rien
    d'I3F ; `generate_xlsx_annex` n'en contient aucun marqueur et en dépend. Le
    classement lexical se serait trompé sur les deux, en sens contraires.
    """
    source = (REPO / "audit_bim" / "profiles" / "i3f" / "tools_query.py").read_text(
        encoding="utf-8"
    )
    assert "CCH" in source, "prémisse du test : le mot est bien présent dans ce module"
    assert _entry(report, "filter_bim_objects")["category"] == "extractible"

    # Bornée par AST : une tranche de caractères déborde sur la fonction
    # suivante — qui, elle, parle bien d'AVP. Le test aurait alors échoué sur sa
    # prémisse plutôt que sur sa thèse.
    annex = (REPO / "audit_bim" / "profiles" / "i3f" / "tools_reporting.py").read_text(
        encoding="utf-8"
    )
    node = next(
        n
        for n in ast.parse(annex).body
        if isinstance(n, ast.FunctionDef) and n.name == "generate_xlsx_annex"
    )
    body = ast.get_source_segment(annex, node) or ""
    assert body, "prémisse : la fonction doit être localisée"
    assert not re.search(r"\b(CCH|AVP|I3F)\b", body), "prémisse : aucun marqueur dans cet outil"
    assert _entry(report, "generate_xlsx_annex")["category"] == "i3f"
