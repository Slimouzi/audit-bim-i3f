"""Ré-export : conversion .docx → .pdf best-effort (``bim_reporting.pdf``).

L'implémentation vit dans le socle générique ``bim-reporting``. Comportement
inchangé : LibreOffice headless s'il est présent, sinon ``None`` — le ``.docx``
reste le livrable, aucun échec dur.

``AUDIT_BIM_SOFFICE`` reste honoré côté socle (en second, après le nom canonique
``BIM_REPORTING_SOFFICE``) : les déploiements qui le positionnent continuent de
fonctionner.
"""

from __future__ import annotations

from bim_reporting.pdf import docx_to_pdf  # noqa: F401 — ré-export direct

__all__ = ["docx_to_pdf"]
