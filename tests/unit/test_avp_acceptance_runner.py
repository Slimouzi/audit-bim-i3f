"""Gardes du runner d'acceptation AVP (`scripts/avp_acceptance/run_acceptance.py`).

Teste, hors réseau, les refus purs du runner : garde catalogue CCH (document
absent / catalogue vide / catalogue valide) et garde d'écriture hors dépôt
(chemin dans le repo refusé, /tmp accepté). Le module est chargé par chemin (il
vit sous ``scripts/``) ; ses imports ``audit_bim`` sont tardifs (dans ``main``),
donc l'import du module ne déclenche aucune dépendance lourde.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

_RUNNER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "avp_acceptance" / "run_acceptance.py"
)
_spec = importlib.util.spec_from_file_location("avp_acceptance_runner", _RUNNER_PATH)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def _fake_catalog(n_props: int, n_rules: int):
    return types.SimpleNamespace(properties=[0] * n_props, naming_rules=[0] * n_rules)


# ── Garde catalogue CCH ───────────────────────────────────────────────────


def test_catalog_guard_refuses_missing_document(tmp_path):
    docs = {"cch_pdf": str(tmp_path / "absent.pdf")}  # fichier inexistant
    with pytest.raises(SystemExit):
        runner.assert_catalog_usable(docs, _fake_catalog(10, 10))


def test_catalog_guard_refuses_empty_catalog(tmp_path):
    doc = tmp_path / "cch.pdf"
    doc.write_text("x")  # document présent...
    # ...mais catalogue sans règle de nommage → refus.
    with pytest.raises(SystemExit):
        runner.assert_catalog_usable({"cch_pdf": str(doc)}, _fake_catalog(10, 0))


def test_catalog_guard_refuses_empty_properties(tmp_path):
    doc = tmp_path / "cch.pdf"
    doc.write_text("x")
    with pytest.raises(SystemExit):
        runner.assert_catalog_usable({"cch_pdf": str(doc)}, _fake_catalog(0, 10))


def test_catalog_guard_accepts_valid(tmp_path):
    doc = tmp_path / "cch.pdf"
    doc.write_text("x")
    # Ne doit pas lever.
    runner.assert_catalog_usable({"cch_pdf": str(doc)}, _fake_catalog(5, 5))


# ── Garde d'écriture hors dépôt ───────────────────────────────────────────


def test_outside_repo_refuses_path_in_repo():
    # Un chemin sous le dépôt (à côté du runner) doit être refusé.
    inside = Path(runner.__file__).resolve().parent / "out"
    with pytest.raises(SystemExit):
        runner._assert_outside_repo(inside)


def test_outside_repo_accepts_tmp(tmp_path):
    # tmp_path (hors du dépôt) est accepté : ne doit pas lever.
    runner._assert_outside_repo(tmp_path)
