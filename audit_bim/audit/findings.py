"""Ré-export des contrats d'audit (``Finding``, ``Severity``, ``Theme``,
``ErrorType``) désormais hébergés dans ``bim-core``.

Ce module reste le point d'import historique
(``from audit_bim.audit.findings import Finding``) et héberge la palette
**feux tricolores** ``SEVERITY_COLORS`` + ``severity_color()`` : c'est une
convention métier attachée à l'enum ``Severity`` (pas de la charte de marque),
elle vit donc ici, à côté de la sévérité qu'elle décrit. ``reporting/theming``
la **ré-exporte** (import descendant légal) — casse le cycle audit ↔ reporting.
"""

from __future__ import annotations

from bim_core.findings import ErrorType, Finding, Severity, Theme

__all__ = ["Severity", "Theme", "ErrorType", "Finding", "SEVERITY_COLORS", "severity_color"]

# Palette feux tricolores standard (single source of truth). Convention métier,
# indépendante de la charte BIMData (qui, elle, reste dans ``reporting/theming``).
SEVERITY_COLORS = {
    "CRITICAL": "8B0000",  # rouge très foncé (dark red)
    "HIGH": "DC3545",  # rouge
    "MEDIUM": "FF8C00",  # orange (dark orange)
    "LOW": "28A745",  # vert
    "INFO": "4682B4",  # bleu (steel blue) — pas de gravité
}


def severity_color(sev: Severity) -> str:
    """Code couleur hexadécimal (sans ``#``) par sévérité — lookup direct dans
    :data:`SEVERITY_COLORS`.

    Palette feux tricolores : ``CRITICAL`` → ``8B0000``, ``HIGH`` → ``DC3545``,
    ``MEDIUM`` → ``FF8C00``, ``LOW`` → ``28A745``, ``INFO`` → ``4682B4``.

    Args:
        sev: La sévérité dont on veut la couleur.

    Returns:
        Code hex sur 6 caractères, sans préfixe (ex: ``"DC3545"``).

    Raises:
        KeyError: Si la sévérité n'a pas de couleur définie (jamais en usage
            normal puisque les Enum couvrent toutes les valeurs).
    """
    return SEVERITY_COLORS[sev.value]
