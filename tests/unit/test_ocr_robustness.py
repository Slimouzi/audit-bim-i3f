"""Tests des garde-fous OCR — confiance flottante + isolation par page.

Les dépendances OCR (``pytesseract`` + ``pdf2image``) sont dans
l'extra optionnel ``[ocr]`` du package. Quand elles ne sont pas
installées (CI standard, dev sans Tesseract), les tests qui les
exercent sont skippés ; ``_parse_conf`` reste testable seul.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from audit_bim.doe.extractors.ocr import _parse_conf, parse_doe_pdf_ocr

_ocr_deps_available = True
try:
    import pdf2image  # noqa: F401
    import pytesseract  # noqa: F401
except ImportError:
    _ocr_deps_available = False

needs_ocr_deps = pytest.mark.skipif(
    not _ocr_deps_available,
    reason="extras [ocr] (pytesseract + pdf2image) non installés",
)


class TestParseConf:
    def test_int_value(self):
        assert _parse_conf(95) == 95.0

    def test_string_int(self):
        assert _parse_conf("95") == 95.0

    def test_string_float(self):
        # Tesseract peut renvoyer un float en string
        assert _parse_conf("95.123") == pytest.approx(95.123)

    def test_negative_sentinel(self):
        # -1 est la sentinelle Tesseract pour les mots sans alternatives
        assert _parse_conf("-1") is None
        assert _parse_conf(-1) is None

    def test_none(self):
        assert _parse_conf(None) is None

    def test_garbage(self):
        assert _parse_conf("not a number") is None
        assert _parse_conf("") is None

    def test_zero_allowed(self):
        # 0 est une confiance valide (juste très basse)
        assert _parse_conf(0) == 0.0


@needs_ocr_deps
class TestPerPageIsolation:
    """Vérifie qu'une erreur OCR sur une page n'interrompt pas les autres."""

    def test_tesseract_error_on_one_page_does_not_kill_others(self, tmp_path):
        # On simule un PDF de 3 pages dont la page 2 plante
        import pytesseract

        pdf = tmp_path / "fake.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        # ``pdfinfo_from_path`` est importé en lazy à l'intérieur de la
        # fonction (``from pdf2image.pdf2image import ...``). On patche
        # le symbole *à la source*, pas dans ``ocr``.
        with (
            patch("pdf2image.pdf2image.pdfinfo_from_path") as mock_info,
            patch("audit_bim.doe.extractors.ocr._ocr_single_page") as mock_page,
        ):
            mock_info.return_value = {"Pages": 3}

            from audit_bim.doe.models import DoeRecord

            def side_effect(*, path, page_num, **kwargs):
                if page_num == 2:
                    raise pytesseract.TesseractError(1, "timeout")
                return [
                    DoeRecord(
                        source=f"{path}#page={page_num}",
                        row_index=1,
                        uuid_hint=f"uuid-page-{page_num}",
                    )
                ]

            mock_page.side_effect = side_effect
            records = parse_doe_pdf_ocr(pdf, lang="fra")

        assert len(records) == 2
        sources = [r.source for r in records]
        assert any("page=1" in s for s in sources)
        assert any("page=3" in s for s in sources)

    def test_generic_exception_also_isolated(self, tmp_path):
        pdf = tmp_path / "fake.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        with (
            patch("pdf2image.pdf2image.pdfinfo_from_path") as mock_info,
            patch("audit_bim.doe.extractors.ocr._ocr_single_page") as mock_page,
        ):
            mock_info.return_value = {"Pages": 2}

            from audit_bim.doe.models import DoeRecord

            def side_effect(*, path, page_num, **kwargs):
                if page_num == 1:
                    raise RuntimeError("poppler crash")
                return [DoeRecord(source=str(path), row_index=1, uuid_hint=f"u-{page_num}")]

            mock_page.side_effect = side_effect
            records = parse_doe_pdf_ocr(pdf, lang="fra")

        assert len(records) == 1
        assert records[0].uuid_hint == "u-2"


@needs_ocr_deps
class TestEnvBounds:
    def test_max_pdf_pages_env_caps(self, tmp_path, monkeypatch):
        # On limite à 2 pages via env même si le PDF en a "5"
        monkeypatch.setenv("AUDIT_MAX_PDF_PAGES", "2")

        pdf = tmp_path / "big.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        with (
            patch("pdf2image.pdf2image.pdfinfo_from_path") as mock_info,
            patch("audit_bim.doe.extractors.ocr._ocr_single_page") as mock_page,
        ):
            mock_info.return_value = {"Pages": 5}
            mock_page.return_value = []
            parse_doe_pdf_ocr(pdf, lang="fra")

        # _ocr_single_page appelé exactement 2 fois (cap), pas 5
        assert mock_page.call_count == 2
