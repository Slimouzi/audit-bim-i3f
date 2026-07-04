"""Ré-export des contrats d'audit (``Finding``, ``Severity``, ``Theme``,
``ErrorType``) désormais hébergés dans ``bim-core``.

Ce module reste le point d'import historique
(``from audit_bim.audit.findings import Finding``) et conserve
``severity_color()`` qui, lui, dépend du thème de reporting local et ne
relève donc pas des contrats communs.
"""

from __future__ import annotations

from bim_core.findings import ErrorType, Finding, Severity, Theme

__all__ = ["Severity", "Theme", "ErrorType", "Finding", "severity_color"]


def severity_color(sev: Severity) -> str:
    """Code couleur hexadécimal (sans ``#``) par sévérité.

    Délègue à ``audit_bim.reporting.theming.SEVERITY_COLORS`` qui est la
    *single source of truth*. Palette feux tricolores :

    - ``CRITICAL`` → rouge foncé (``8B0000``)
    - ``HIGH``     → rouge       (``DC3545``)
    - ``MEDIUM``   → orange      (``FF8C00``)
    - ``LOW``      → vert        (``28A745``)
    - ``INFO``     → bleu        (``4682B4``)

    Args:
        sev: La sévérité dont on veut la couleur.

    Returns:
        Code hex sur 6 caractères, sans préfixe (ex: ``"DC3545"``).

    Raises:
        KeyError: Si la sévérité n'a pas de couleur définie (jamais en
            usage normal puisque les Enum couvrent toutes les valeurs).
    """
    from ..reporting.theming import SEVERITY_COLORS

    return SEVERITY_COLORS[sev.value]
