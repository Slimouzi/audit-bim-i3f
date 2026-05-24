"""Tests du parseur OCR Tesseract.

Skipif global si le binaire Tesseract n'est pas installé sur la machine.
La CI GitHub Actions ne l'a pas par défaut — ces tests ne tournent que
sur les environnements où ``brew install tesseract`` (ou équivalent) a
été fait.
"""

from __future__ import annotations

import pytest

from audit_bim.doe.extractors.ocr import (
    _group_words_into_lines,
    is_tesseract_available,
)

# Pré-requis : pytesseract + binaire Tesseract
pytesseract = pytest.importorskip("pytesseract")
pytestmark = pytest.mark.skipif(
    not is_tesseract_available(),
    reason="Tesseract OCR non installé sur cette machine.",
)


class TestGroupWordsIntoLines:
    """Tests des helpers internes (n'exigent pas Tesseract installé)."""

    def test_empty_input(self):
        assert _group_words_into_lines([]) == []

    def test_single_word(self):
        words = [{"text": "X", "top": 10, "left": 5, "width": 20, "height": 15}]
        lines = _group_words_into_lines(words)
        assert len(lines) == 1
        assert lines[0] == words

    def test_two_words_same_line(self):
        # Mêmes coordonnées verticales (centres alignés) → 1 ligne
        words = [
            {"text": "A", "top": 10, "left": 5, "width": 20, "height": 15},
            {"text": "B", "top": 12, "left": 50, "width": 20, "height": 15},
        ]
        lines = _group_words_into_lines(words)
        assert len(lines) == 1
        # Triés par left
        assert [w["text"] for w in lines[0]] == ["A", "B"]

    def test_two_words_different_lines(self):
        # Écart vertical large → 2 lignes
        words = [
            {"text": "A", "top": 10, "left": 5, "width": 20, "height": 15},
            {"text": "B", "top": 80, "left": 5, "width": 20, "height": 15},
        ]
        lines = _group_words_into_lines(words)
        assert len(lines) == 2


@pytest.mark.slow
class TestParseDoePdfOcr:
    """Test bout-en-bout : génère une image avec PIL, l'OCR.

    Ces tests sont marqués 'slow' (quelques secondes par image) et
    skipés automatiquement si Tesseract n'est pas disponible.
    """

    def test_ocr_simple_image(self, tmp_path):
        # Skipé d'office si Pillow absent
        pytest.importorskip("PIL")
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (800, 200), color="white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("Arial.ttf", 36)
        except OSError:
            font = ImageFont.load_default()
        draw.text((50, 50), "TEST OCR ABC123", fill="black", font=font)

        text = pytesseract.image_to_string(img)
        assert "TEST" in text.upper() or "ABC" in text.upper()
