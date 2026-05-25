"""Tests directs des tools serveur qui touchent au filesystem.

On vérifie ici que ``set_owner_documents`` et ``enrich_with_public_data``
appliquent bien la sandbox d'inputs (cf. fix review CTO round 2).
"""

from __future__ import annotations

from unittest.mock import patch

import openpyxl
import pytest
import reportlab.lib.pagesizes
from reportlab.pdfgen import canvas

from audit_bim.mcp import server as mcp_server
from audit_bim.mcp.session import _Session, current_session
from audit_bim.safe_paths import UnsafePathError


@pytest.fixture
def _isolated_session():
    """Bind une session fraîche pour la durée du test."""
    sess = _Session()
    token = current_session.set(sess)
    try:
        yield sess
    finally:
        current_session.reset(token)


@pytest.fixture
def _make_pdf(tmp_path):
    def _builder(name: str = "cch.pdf") -> str:
        p = tmp_path / name
        c = canvas.Canvas(str(p), pagesize=reportlab.lib.pagesizes.A4)
        c.drawString(100, 700, "CCH I3F test")
        c.save()
        return str(p)

    return _builder


@pytest.fixture
def _make_xlsx(tmp_path):
    def _builder(name: str = "spec.xlsx") -> str:
        p = tmp_path / name
        wb = openpyxl.Workbook()
        wb.active["A1"] = "header"
        wb.save(p)
        return str(p)

    return _builder


# ── set_owner_documents : validation d'extensions ───────────────────────


class TestSetOwnerDocumentsSandbox:
    def test_accepts_pdf_for_cch(self, _isolated_session, _make_pdf):
        pdf = _make_pdf()
        res = mcp_server.set_owner_documents(cch_pdf=pdf)
        assert res["cch_pdf"]["exists"] is True

    def test_refuses_xlsx_for_cch(self, _isolated_session, _make_xlsx):
        xlsx = _make_xlsx()
        with pytest.raises(UnsafePathError, match="Extension"):
            mcp_server.set_owner_documents(cch_pdf=xlsx)

    def test_accepts_xlsx_for_data_spec(self, _isolated_session, _make_xlsx):
        xlsx = _make_xlsx()
        res = mcp_server.set_owner_documents(data_spec_xlsx=xlsx)
        assert res["data_spec_xlsx"]["exists"] is True

    def test_refuses_pdf_for_data_spec(self, _isolated_session, _make_pdf):
        pdf = _make_pdf()
        with pytest.raises(UnsafePathError, match="Extension"):
            mcp_server.set_owner_documents(data_spec_xlsx=pdf)

    def test_refuses_pdf_for_naming_spec(self, _isolated_session, _make_pdf):
        pdf = _make_pdf()
        with pytest.raises(UnsafePathError, match="Extension"):
            mcp_server.set_owner_documents(naming_spec_xlsx=pdf)

    def test_refuses_missing_file(self, _isolated_session, tmp_path):
        with pytest.raises(FileNotFoundError):
            mcp_server.set_owner_documents(cch_pdf=str(tmp_path / "ghost.pdf"))

    def test_refuses_traversal(self, _isolated_session):
        with pytest.raises(UnsafePathError, match=r"\.\."):
            mcp_server.set_owner_documents(cch_pdf="../etc/passwd.pdf")


# ── enrich_with_public_data : sandbox doe_path ──────────────────────────


class TestEnrichWithPublicDataSandbox:
    def test_refuses_extension_outside_whitelist(self, _isolated_session, tmp_path):
        evil = tmp_path / "evil.exe"
        evil.write_bytes(b"x")
        _isolated_session.snapshot = object()  # ensure_snapshot passe
        with pytest.raises(UnsafePathError, match="Extension"):
            mcp_server.enrich_with_public_data(doe_path=str(evil))

    def test_refuses_missing_file(self, _isolated_session, tmp_path):
        _isolated_session.snapshot = object()
        with pytest.raises(FileNotFoundError):
            mcp_server.enrich_with_public_data(doe_path=str(tmp_path / "ghost.xlsx"))

    def test_refuses_traversal(self, _isolated_session):
        _isolated_session.snapshot = object()
        with pytest.raises(UnsafePathError, match=r"\.\."):
            mcp_server.enrich_with_public_data(doe_path="../doe.xlsx")

    def test_accepts_valid_doe_and_passes_resolved_path(self, _isolated_session, _make_xlsx):
        # On accepte le xlsx, et la valeur passée à l'enrichissement
        # interne est le chemin RÉSOLU absolu.
        _isolated_session.snapshot = object()
        doe = _make_xlsx("doe.xlsx")
        with patch("audit_bim.mcp.server._enrich_with_public_data") as mock_enrich:
            from audit_bim.enrichment.models import (
                EnrichmentReport,
                GeocodingResult,
                ProjectAddress,
            )

            mock_enrich.return_value = EnrichmentReport(
                address=ProjectAddress(),
                geocoding=GeocodingResult(matched=False),
            )
            mcp_server.enrich_with_public_data(doe_path=doe)
        assert mock_enrich.call_args.kwargs["doe_path"] is not None
        assert mock_enrich.call_args.kwargs["doe_path"].endswith("doe.xlsx")
        # Le chemin transmis est un absolu (résolu) — pas la string brute
        assert mock_enrich.call_args.kwargs["doe_path"].startswith("/")

    def test_none_doe_path_passes_through(self, _isolated_session):
        # doe_path=None → on ne valide rien, on laisse à None
        _isolated_session.snapshot = object()
        with patch("audit_bim.mcp.server._enrich_with_public_data") as mock_enrich:
            from audit_bim.enrichment.models import (
                EnrichmentReport,
                GeocodingResult,
                ProjectAddress,
            )

            mock_enrich.return_value = EnrichmentReport(
                address=ProjectAddress(),
                geocoding=GeocodingResult(matched=False),
            )
            mcp_server.enrich_with_public_data(doe_path=None)
        assert mock_enrich.call_args.kwargs["doe_path"] is None
