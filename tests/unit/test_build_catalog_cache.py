"""Mémoïsation de ``build_catalog`` (PR4 §4c) — keyée chemins + (mtime, taille).

Les 3 parseurs sont neutralisés : on teste le **cache**, pas le parsing.
"""

from __future__ import annotations

import pytest

from audit_bim.requirements import catalog as cat


@pytest.fixture
def _no_parse(monkeypatch):
    monkeypatch.setattr(cat, "parse_data_spec", lambda p: [])
    monkeypatch.setattr(cat, "parse_naming_spec", lambda p: ([], [], [], []))
    monkeypatch.setattr(cat, "parse_pdf", lambda p: {})


def test_same_sources_return_same_object(tmp_path, _no_parse):
    x = tmp_path / "data.xlsx"
    x.write_text("x")
    c1 = cat.build_catalog(data_spec_xlsx=str(x))
    c2 = cat.build_catalog(data_spec_xlsx=str(x))
    assert c1 is c2  # cache hit → identité


def test_modified_source_rebuilds(tmp_path, _no_parse):
    x = tmp_path / "data.xlsx"
    x.write_text("x")
    c1 = cat.build_catalog(data_spec_xlsx=str(x))
    x.write_text("xxxx")  # taille (et mtime) changent → nouvelle clé
    c2 = cat.build_catalog(data_spec_xlsx=str(x))
    assert c2 is not c1


def test_different_sources_differ(tmp_path, _no_parse):
    a = tmp_path / "a.xlsx"
    a.write_text("a")
    b = tmp_path / "b.xlsx"
    b.write_text("b")
    assert cat.build_catalog(data_spec_xlsx=str(a)) is not cat.build_catalog(data_spec_xlsx=str(b))


def test_missing_provided_source_is_not_cached(tmp_path, _no_parse):
    ghost = tmp_path / "ghost.xlsx"  # fourni mais absent
    c1 = cat.build_catalog(data_spec_xlsx=str(ghost))
    c2 = cat.build_catalog(data_spec_xlsx=str(ghost))
    assert c1 is not c2  # pas de cache → objet neuf à chaque appel


def test_clear_cache_forces_rebuild(tmp_path, _no_parse):
    x = tmp_path / "data.xlsx"
    x.write_text("x")
    c1 = cat.build_catalog(data_spec_xlsx=str(x))
    cat.clear_catalog_cache()
    assert cat.build_catalog(data_spec_xlsx=str(x)) is not c1
