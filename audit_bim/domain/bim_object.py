"""Ré-export du contrat :class:`BimObject` (et :class:`ClassificationRef`),
désormais hébergé dans ``bim-core``.

Point d'import historique conservé
(``from audit_bim.domain.bim_object import BimObject``).
"""

from __future__ import annotations

from bim_core.bim_object import BimObject, ClassificationRef

__all__ = ["BimObject", "ClassificationRef"]
