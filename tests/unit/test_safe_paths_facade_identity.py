"""Gate d'identité/parité : ``audit_bim.safe_paths`` ré-exporte le profil audit
de ``bim_core.paths`` (aucune logique dupliquée), signatures et erreurs
inchangées.
"""

from __future__ import annotations

import bim_core.paths as core_paths
import pytest

from audit_bim import safe_paths as sp


def test_export_functions_are_bim_core_paths():
    # Ré-exports directs (mêmes objets) — pas de réimplémentation locale.
    assert sp.safe_export_path is core_paths.safe_export_path
    assert sp.safe_export_read_path is core_paths.safe_export_read_path
    assert sp.safe_export_dir is core_paths.safe_export_dir
    assert sp.get_export_root is core_paths.get_export_root
    assert sp.UnsafePathError is core_paths.UnsafePathError
    assert sp.ALLOWED_INPUT_EXTENSIONS is core_paths.ALLOWED_INPUT_EXTENSIONS


def test_allowed_extensions_preserved():
    # Contrat métier préservé (jeu d'extensions I3F attendu).
    for ext in (".pdf", ".xlsx", ".docx", ".json"):
        assert ext in sp.ALLOWED_INPUT_EXTENSIONS


def test_safe_input_path_uses_audit_profile(tmp_path, monkeypatch):
    # Wrapper mince : profil audit (base cwd + whitelist défaut + fichier régulier).
    monkeypatch.delenv("AUDIT_INPUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ok.pdf").write_bytes(b"x")
    # Résolution base cwd (profil audit) : "ok.pdf" -> cwd/ok.pdf.
    assert sp.safe_input_path("ok.pdf") == (tmp_path / "ok.pdf").resolve()
    # Whitelist défaut appliquée (profil audit) : .exe refusé.
    (tmp_path / "bad.exe").write_bytes(b"x")
    with pytest.raises(sp.UnsafePathError):
        sp.safe_input_path("bad.exe")
    # `..` interdits.
    with pytest.raises(sp.UnsafePathError):
        sp.safe_input_path("../x.pdf")


def test_safe_input_path_matches_bim_core_audit_profile(tmp_path, monkeypatch):
    # Parité stricte : le wrapper == profil audit du package, sur un cas valide.
    monkeypatch.delenv("AUDIT_INPUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.json").write_bytes(b"{}")
    via_shim = sp.safe_input_path("a.json")
    via_pkg = core_paths.safe_input_path("a.json", profile="audit")
    assert via_shim == via_pkg
