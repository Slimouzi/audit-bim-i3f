"""Tests du module ``audit_bim.reporting.theming``."""
from __future__ import annotations

import re

from audit_bim.audit.findings import Severity
from audit_bim.reporting.theming import (
    I3F_BLUE,
    I3F_GREY,
    SEVERITY_COLORS,
    THEME_COLORS,
)

HEX6 = re.compile(r"^[0-9A-Fa-f]{6}$")


class TestPalette:
    def test_all_severity_colors_hex6(self):
        for k, v in SEVERITY_COLORS.items():
            assert HEX6.match(v), f"{k} = {v!r} n'est pas un hex 6 chars"

    def test_all_theme_colors_hex6(self):
        for k, v in THEME_COLORS.items():
            assert HEX6.match(v), f"{k} = {v!r} n'est pas un hex 6 chars"

    def test_i3f_brand_colors(self):
        assert HEX6.match(I3F_BLUE)
        assert HEX6.match(I3F_GREY)


class TestSeverityCoverage:
    def test_every_severity_has_color(self):
        for sev in Severity:
            assert sev.value in SEVERITY_COLORS

    def test_traffic_light_convention(self):
        # HIGH = rouge, MEDIUM = orange, LOW = vert (demande utilisateur)
        # On vérifie que les codes sont dans les bonnes nuances par teinte rouge
        # → rouge dominant : R > G+B/2 etc. Critère simple :
        red_hex = SEVERITY_COLORS["HIGH"]
        r = int(red_hex[0:2], 16)
        g = int(red_hex[2:4], 16)
        b = int(red_hex[4:6], 16)
        assert r > g and r > b  # rouge dominant

        orange_hex = SEVERITY_COLORS["MEDIUM"]
        r = int(orange_hex[0:2], 16)
        g = int(orange_hex[2:4], 16)
        assert r > 200 and g > 100  # rouge + vert (orange)

        green_hex = SEVERITY_COLORS["LOW"]
        r = int(green_hex[0:2], 16)
        g = int(green_hex[2:4], 16)
        assert g > r  # vert dominant
