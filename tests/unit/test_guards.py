"""Gardes partagées des runners (``audit_bim.security.guards``) — PR4 §4a.

Tests migrés depuis ``test_avp_acceptance_runner`` (dédup : une seule garde,
un seul fichier de test).
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from audit_bim.security.guards import assert_catalog_usable, assert_outside_repo

_REPO = Path(__file__).resolve().parents[2]


def _fake_catalog(n_props: int, n_rules: int):
    return types.SimpleNamespace(properties=[0] * n_props, naming_rules=[0] * n_rules)


# ── assert_catalog_usable ─────────────────────────────────────────────────
def test_catalog_guard_refuses_missing_document(tmp_path):
    with pytest.raises(SystemExit):
        assert_catalog_usable({"cch_pdf": str(tmp_path / "absent.pdf")}, _fake_catalog(10, 10))


def test_catalog_guard_refuses_empty_naming_rules(tmp_path):
    doc = tmp_path / "cch.pdf"
    doc.write_text("x")
    with pytest.raises(SystemExit):
        assert_catalog_usable({"cch_pdf": str(doc)}, _fake_catalog(10, 0))


def test_catalog_guard_refuses_empty_properties(tmp_path):
    doc = tmp_path / "cch.pdf"
    doc.write_text("x")
    with pytest.raises(SystemExit):
        assert_catalog_usable({"cch_pdf": str(doc)}, _fake_catalog(0, 10))


def test_catalog_guard_accepts_valid(tmp_path):
    doc = tmp_path / "cch.pdf"
    doc.write_text("x")
    assert_catalog_usable({"cch_pdf": str(doc)}, _fake_catalog(5, 5))  # ne lève pas


# ── assert_outside_repo ───────────────────────────────────────────────────
def test_outside_repo_refuses_path_in_repo():
    with pytest.raises(SystemExit):
        assert_outside_repo(_REPO / "out", context="test")


def test_outside_repo_refuses_repo_root_itself():
    with pytest.raises(SystemExit):
        assert_outside_repo(_REPO, context="test")


def test_outside_repo_accepts_tmp(tmp_path):
    assert_outside_repo(tmp_path, context="test")  # hors dépôt → ne lève pas
