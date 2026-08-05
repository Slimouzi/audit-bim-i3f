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
    assert not [t for t in report["tools"] if t["category"] == "inconnu"]
    for claim in (
        "| **Extractibles** | 33 |",
        "| **Irréductiblement I3F** | 12 |",
        "**25 outils extractibles et autonomes**",
        "### Les 25 extractibles autonomes",
    ):
        assert claim in text, f"le document ne porte plus : {claim}"


def _tools_cited(section: str, known: set[str]) -> set[str]:
    """Noms d'outils cités entre backticks dans ``section``.

    Le motif capture ``[^`]+`` puis intersecte avec les noms réels. Filtrer par
    ``[a-z_]+`` laissait passer des chaînes tronquées — ``i3f`` contient un
    chiffre — et retenait des noms de modules ou d'attributs qui ne sont pas des
    outils. L'intersection avec l'inventaire mesuré est le seul filtre exact.
    """
    return set(re.findall(r"`([^`]+)`", section)) & known


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def known_tools(report) -> set[str]:
    return {t["tool"] for t in report["tools"]}


def _measured(report: dict, category: str, upstream: bool | None = None) -> set[str]:
    return {
        t["tool"]
        for t in report["tools"]
        if t["category"] == category and (upstream is None or t["requires_upstream"] is upstream)
    }


def test_the_document_lists_the_right_upstream_bound_tools(report, doc, known_tools):
    """Les 8 outils suspendus à un amont sont nommés — un compte ne suffit pas."""
    section = _section(doc, "suspendus à un amont", "**12 outils I3F**")
    assert _tools_cited(section, known_tools) == _measured(report, "extractible", upstream=True)


def test_the_document_lists_the_right_autonomous_tools(report, doc, known_tools):
    """Les 25 autonomes, nommément.

    C'est la table sur laquelle E7 s'appuiera. Un outil qui y glisserait sans
    l'être resterait invisible tant que le total ne bouge pas — et c'est
    précisément un total qui ne bouge pas quand deux erreurs se compensent.
    """
    section = _section(doc, "### Les 25 extractibles autonomes", "Ces outils s'appuient")
    assert _tools_cited(section, known_tools) == _measured(report, "extractible", upstream=False)


def test_the_document_lists_the_right_i3f_tools(report, doc, known_tools):
    """Les 12 outils du référentiel, nommément."""
    section = _section(doc, "### Les 12 outils I3F", "## Ce que cela dit pour E7")
    assert _tools_cited(section, known_tools) == _measured(report, "i3f")


def test_the_e7_first_circle_is_exactly_what_the_measurement_supports(report, doc, known_tools):
    """La recommandation d'E7 doit rester adossée à la mesure.

    Ce paragraphe est le seul du document qui engage le lot suivant. Un outil
    qu'on y ajouterait — parce qu'il *semble* générique — deviendrait une
    décision de périmètre prise sans preuve, et la seule chose que ce dossier
    devait empêcher.
    """
    section = _section(doc, "1. **Cible, identité, lecture**", "2. **Requêtes sur snapshot**")
    cited = _tools_cited(section, known_tools)

    assert cited == {
        "parse_bimdata_target",
        "check_bimdata_access",
        "verify_active_model",
        "extract_model_snapshot",
        "download_model_ifc",
    }
    # Et chacun doit être mesuré comme extractible ET autonome.
    assert cited <= _measured(report, "extractible", upstream=False)


def test_the_section_parsing_is_not_vacuous(report, doc, known_tools):
    """Une découpe qui ne capterait rien ferait passer tous les tests ci-dessus."""
    section = _section(doc, "### Les 25 extractibles autonomes", "Ces outils s'appuient")
    assert len(_tools_cited(section, known_tools)) == 25

    # Le filtre par intersection doit écarter ce qui n'est pas un outil : cette
    # section cite aussi des modules entre backticks, juste après.
    modules = _section(doc, "Ces outils s'appuient", "### Les 12 outils I3F")
    assert "audit_bim.doe" in modules
    assert _tools_cited(modules, known_tools) == set()


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


def test_no_unclassified_state_fields_are_allowed(report):
    """Un champ de session inconnu ne doit pas être présumé neutre.

    Le script calculait ces champs sans en tirer de conséquence : un futur
    ``_State.contexte_client`` lu par un outil l'aurait laissé compté dans le
    socle, sans qu'aucun compteur ne bouge. Le classement est désormais fermé —
    catégorie ``inconnu`` et code de retour non nul.
    """
    offenders = {
        t["tool"]: t["unclassified_state_fields"]
        for t in report["tools"]
        if t["unclassified_state_fields"]
    }
    assert not offenders, (
        f"champs de session non classés : {offenders}. Les ranger dans "
        f"I3F_STATE_FIELDS, UPSTREAM_STATE_FIELDS ou NEUTRAL_STATE_FIELDS."
    )
    assert not [t for t in report["tools"] if t["category"] == "inconnu"]


def test_an_unknown_state_field_would_be_caught():
    """Non-vacuité : le classement fermé doit savoir refuser.

    On retire un champ des listes connues et on vérifie qu'un outil qui le lit
    bascule en ``inconnu`` — sans quoi le contrôle ci-dessus ne prouverait que
    l'absence actuelle de champ inattendu, pas la capacité à en voir un.
    """
    import inventory_shared_tools as inv

    removed = "snapshot"
    original = set(inv.NEUTRAL_STATE_FIELDS)
    try:
        inv.NEUTRAL_STATE_FIELDS.discard(removed)
        degraded = inv.analyse()
    finally:
        inv.NEUTRAL_STATE_FIELDS.clear()
        inv.NEUTRAL_STATE_FIELDS.update(original)

    unknown = [t["tool"] for t in degraded["tools"] if t["category"] == "inconnu"]
    assert unknown, f"{removed!r} déclassé n'a fait basculer aucun outil"

    # Et la mutation ne laisse pas de trace : l'inventaire réel reste propre.
    assert not [t for t in inv.analyse()["tools"] if t["category"] == "inconnu"]


@pytest.mark.parametrize("argv", [[], ["--json"]])
def test_every_output_mode_fails_closed_on_an_unknown_field(monkeypatch, capsys, argv):
    """Le code de retour ne doit pas dépendre du format d'affichage.

    Le contrôle vivait après le branchement de sortie : ``--json`` imprimait et
    rendait 0. Or c'est le mode qu'un script ou une CI consomme — donc celui où
    le silence coûte le plus cher. Les deux modes sont vérifiés ensemble pour
    que la protection ne puisse pas se perdre d'un seul côté.
    """
    import inventory_shared_tools as inv

    monkeypatch.setattr(inv, "NEUTRAL_STATE_FIELDS", inv.NEUTRAL_STATE_FIELDS - {"snapshot"})
    monkeypatch.setattr(sys, "argv", ["inventory_shared_tools.py", *argv])

    assert inv.main() == 1, "un champ inconnu doit faire échouer l'inventaire"

    # Et la sortie reste exploitable : on doit pouvoir voir *qui* lit *quoi*.
    out = capsys.readouterr().out
    assert "extract_model_snapshot" in out


@pytest.mark.parametrize("argv", [[], ["--json"]])
def test_every_output_mode_succeeds_on_the_real_inventory(monkeypatch, capsys, argv):
    """Non-vacuité : sans champ inconnu, les deux modes rendent 0."""
    import inventory_shared_tools as inv

    monkeypatch.setattr(sys, "argv", ["inventory_shared_tools.py", *argv])
    assert inv.main() == 0
    assert capsys.readouterr().out
