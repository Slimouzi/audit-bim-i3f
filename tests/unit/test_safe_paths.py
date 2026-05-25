"""Tests de :mod:`audit_bim.safe_paths` — sandbox écriture + lecture."""

from __future__ import annotations

import pytest

from audit_bim.safe_paths import (
    ALLOWED_INPUT_EXTENSIONS,
    UnsafePathError,
    safe_export_dir,
    safe_export_path,
    safe_input_path,
)


@pytest.fixture
def export_root(tmp_path, monkeypatch):
    root = tmp_path / "exports"
    root.mkdir()
    monkeypatch.setenv("AUDIT_OUTPUT_DIR", str(root))
    return root


@pytest.fixture
def input_root(tmp_path, monkeypatch):
    root = tmp_path / "inputs"
    root.mkdir()
    monkeypatch.setenv("AUDIT_INPUT_DIR", str(root))
    return root


# ── safe_export_path ─────────────────────────────────────────────────────


class TestSafeExportPath:
    def test_relative_resolved_under_root(self, export_root):
        p = safe_export_path("audit.xlsx")
        assert p.parent == export_root
        assert p.name == "audit.xlsx"

    def test_subdir_created(self, export_root):
        p = safe_export_path("sub/nested/out.docx")
        assert p.parent == export_root / "sub" / "nested"
        assert p.parent.is_dir()

    def test_absolute_inside_root_ok(self, export_root):
        p = safe_export_path(str(export_root / "ok.xlsx"))
        assert p == export_root / "ok.xlsx"

    def test_absolute_outside_root_refused(self, export_root, tmp_path):
        with pytest.raises(UnsafePathError, match="rester sous"):
            safe_export_path(str(tmp_path / "evil.xlsx"))

    def test_traversal_refused(self, export_root):
        with pytest.raises(UnsafePathError, match=r"\.\."):
            safe_export_path("../escape.xlsx")

    def test_existing_refused_without_overwrite(self, export_root):
        (export_root / "x.xlsx").write_text("data")
        with pytest.raises(UnsafePathError, match="overwrite"):
            safe_export_path("x.xlsx")

    def test_overwrite_flag_allows(self, export_root):
        (export_root / "x.xlsx").write_text("data")
        p = safe_export_path("x.xlsx", overwrite=True)
        assert p == export_root / "x.xlsx"


# ── safe_export_dir ──────────────────────────────────────────────────────


class TestSafeExportDir:
    def test_creates_dir_under_root(self, export_root):
        d = safe_export_dir(".cache")
        assert d == export_root / ".cache"
        assert d.is_dir()

    def test_refuses_traversal(self, export_root):
        with pytest.raises(UnsafePathError):
            safe_export_dir("../cache")

    def test_refuses_outside_root(self, export_root, tmp_path):
        with pytest.raises(UnsafePathError):
            safe_export_dir(str(tmp_path / "outside-cache"))


# ── safe_input_path ──────────────────────────────────────────────────────


class TestSafeInputPath:
    def test_no_root_accepts_existing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUDIT_INPUT_DIR", raising=False)
        f = tmp_path / "doe.xlsx"
        f.write_bytes(b"x")
        p = safe_input_path(f)
        assert p == f

    def test_root_enforced_when_set(self, input_root, tmp_path):
        # Fichier hors racine
        outside = tmp_path / "evil.xlsx"
        outside.write_bytes(b"x")
        with pytest.raises(UnsafePathError, match="AUDIT_INPUT_DIR"):
            safe_input_path(outside)

    def test_root_accepts_inside(self, input_root):
        f = input_root / "doe.xlsx"
        f.write_bytes(b"x")
        p = safe_input_path(f)
        assert p == f

    def test_refuses_extension_not_in_whitelist(self, tmp_path):
        f = tmp_path / "evil.exe"
        f.write_bytes(b"x")
        with pytest.raises(UnsafePathError, match="Extension"):
            safe_input_path(f)

    def test_refuses_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            safe_input_path(tmp_path / "ghost.pdf")

    def test_refuses_dir(self, tmp_path):
        d = tmp_path / "subdir.xlsx"
        d.mkdir()
        with pytest.raises(UnsafePathError, match="fichier régulier"):
            safe_input_path(d)

    def test_refuses_oversize(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIT_MAX_INPUT_MB", "1")
        f = tmp_path / "big.pdf"
        f.write_bytes(b"\x00" * (2 * 1024 * 1024))
        with pytest.raises(UnsafePathError, match="trop volumineux"):
            safe_input_path(f)

    def test_traversal_refused(self, tmp_path):
        with pytest.raises(UnsafePathError, match=r"\.\."):
            safe_input_path("../evil.pdf")

    def test_custom_extensions(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text("{}")
        # Refuse .json par défaut ? Non — il est dans ALLOWED_INPUT_EXTENSIONS.
        assert ".json" in ALLOWED_INPUT_EXTENSIONS
        # Mais on peut restreindre encore plus
        with pytest.raises(UnsafePathError, match="Extension"):
            safe_input_path(f, allowed_extensions={".pdf"})
