"""Aucun livrable client ne peut porter l'identité d'un projet d'exemple.

« Tarare 0546L » est le projet de **référence MOA** : il a sa place dans les
fixtures, la documentation et les comparaisons de mise en forme — jamais dans
le nom d'un fichier remis au client. Le classeur de contrôle MOA étant
auto-découvert dans les documents maître d'ouvrage, son entête nommait les
livrables d'après ce projet-là, quelle que soit la maquette auditée.

Ces tests verrouillent la règle : l'identité vient des paramètres explicites,
sinon du contexte du modèle actif, sinon **on demande sans générer**.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.session import _Session, current_session

EXEMPLE_MOA = ("Tarare", "0546L")


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("AUDIT_INPUT_DIR", raising=False)
    sess = _Session()
    token = current_session.set(sess)
    try:
        yield sess, tmp_path
    finally:
        current_session.reset(token)


def _moa_template(path, *, projet="Tarare", esi="0546L", phase="AVP"):
    """Classeur de contrôle du projet de RÉFÉRENCE MOA (Tarare 0546L)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Grille de contrôle"
    r = 1
    for label, val in (("Projet", projet), ("ESI", esi), ("Phase", phase)):
        ws.cell(r, 2, label)
        ws.cell(r, 3, val)
        r += 1
    ws.cell(r, 1, "CODE 3F")
    ws.cell(r, 2, "POINTS DE CONTROLE")
    wb.save(path)
    return str(path)


def _snapshot(sess, project_name="I3F"):
    sess.snapshot = ModelSnapshot(
        project={"name": project_name}, model={"name": "DIEPPE-7427L.ifc"}
    ).index()


# ── sans identité : on demande, on ne génère pas ───────────────────────


def test_missing_identity_asks_and_generates_nothing(session):
    sess, tmp_path = session
    sess.snapshot = ModelSnapshot(model={"name": "M.ifc"}).index()  # aucun nom projet

    res = mcp_server.generate_avp_i3f_pack(auditor="AMO BIM", export_pdf=False)

    assert res["status"] == "needs_context"
    assert {"project_name", "project_code"} <= set(res["missing"])
    keys = {q["key"] for q in res["questions"]}
    assert {"project_name", "project_code"} <= keys
    # Rien n'a été écrit.
    assert not list(Path(tmp_path).glob("**/*.xlsx"))
    assert not list(Path(tmp_path).glob("**/*.docx"))


def test_identity_cannot_be_bypassed_by_confirm_context(session):
    """``confirm_context`` couvre le contexte documentaire, pas l'identité."""
    sess, tmp_path = session
    sess.snapshot = ModelSnapshot(model={"name": "M.ifc"}).index()

    res = mcp_server.generate_avp_i3f_pack(confirm_context=True, export_pdf=False)

    assert res["status"] == "needs_context"
    assert "project_code" in res["missing"]
    assert "OBLIGATOIRE" in res["next_step"]
    assert not list(Path(tmp_path).glob("**/*.xlsx"))


def test_moa_template_identity_never_reaches_the_deliverables(session):
    """Le template MOA fournit la MISE EN FORME, jamais l'identité projet."""
    sess, tmp_path = session
    _snapshot(sess)
    ctrl = _moa_template(tmp_path / "controle maquettes.xlsx")

    res = mcp_server.generate_avp_i3f_pack(controle_xlsx=ctrl, auditor="AMO BIM", export_pdf=False)

    assert res["status"] == "needs_context"  # le code ESI manque toujours
    assert not list(Path(tmp_path).glob("**/*Tarare*"))
    assert not list(Path(tmp_path).glob("**/*0546L*"))


# ── avec identité explicite : le vrai projet, partout ──────────────────


def test_explicit_identity_names_every_deliverable(session):
    sess, tmp_path = session
    _snapshot(sess)
    ctrl = _moa_template(tmp_path / "controle maquettes.xlsx")

    res = mcp_server.generate_avp_i3f_pack(
        controle_xlsx=ctrl,
        project_name="Dieppe",
        project_code="7427L",
        phase="AVP",
        auditor="CdP BIM 3F",
        date_controle="260801",
        export_pdf=False,
    )

    assert res.get("status") != "needs_context", res
    assert res["project_name"] == "Dieppe"
    assert res["project_code"] == "7427L"

    noms = [Path(p).name for p in res["paths"]]
    assert noms, "le pack doit produire des livrables"
    for nom in noms:
        assert nom.startswith("260801 Dieppe 7427L AVP - "), nom


def test_no_example_identity_anywhere_in_the_generated_pack(session):
    """Ni dans les noms de fichiers, ni dans le contenu des livrables."""
    sess, tmp_path = session
    _snapshot(sess)
    ctrl = _moa_template(tmp_path / "controle maquettes.xlsx")

    res = mcp_server.generate_avp_i3f_pack(
        controle_xlsx=ctrl,
        project_name="Dieppe",
        project_code="7427L",
        phase="AVP",
        auditor="CdP BIM 3F",
        export_pdf=False,
    )
    assert res.get("status") != "needs_context", res

    for chemin in res["paths"]:
        p = Path(chemin)
        for exemple in EXEMPLE_MOA:
            assert exemple not in p.name, f"{exemple} dans le nom : {p.name}"
        if p.suffix == ".xlsx":
            wb = openpyxl.load_workbook(p, data_only=True)
            texte = "\n".join(
                str(c)
                for ws in wb.worksheets
                for row in ws.iter_rows(values_only=True)
                for c in row
                if c is not None
            )
            wb.close()
            for exemple in EXEMPLE_MOA:
                assert exemple not in texte, f"{exemple} dans le contenu de {p.name}"


def test_model_context_supplies_the_name_when_not_passed(session):
    """Le contexte du modèle actif est la 2e source — avant toute question."""
    sess, tmp_path = session
    _snapshot(sess, project_name="Dieppe")

    res = mcp_server.generate_avp_i3f_pack(
        project_code="7427L", phase="AVP", auditor="CdP BIM 3F", export_pdf=False
    )

    assert res.get("status") != "needs_context", res
    assert res["project_name"] == "Dieppe"


# ── auteur du contrôle : demandé, jamais inventé ───────────────────────


def test_missing_auditor_is_asked_not_defaulted(session):
    sess, tmp_path = session
    _snapshot(sess, project_name="Dieppe")

    res = mcp_server.generate_avp_i3f_pack(project_code="7427L", phase="AVP", export_pdf=False)

    assert res["status"] == "needs_context"
    assert "auteur_controle" in res["missing"]
    assert not list(Path(tmp_path).glob("**/*.xlsx"))


def test_word_report_has_no_hardcoded_auditor_name():
    """``generate_word_report`` ne porte plus de nom d'auteur codé en dur."""
    import inspect

    from audit_bim.mcp import tools_reporting

    sig = inspect.signature(tools_reporting.generate_word_report)
    assert sig.parameters["auditor"].default is None
    assert sig.parameters["auditor_name"].default is None
