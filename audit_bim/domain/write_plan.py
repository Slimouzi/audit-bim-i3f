"""Ré-export des squelettes ``WritePlan`` / ``ActionResult`` (pattern
prepare/apply), désormais hébergés dans ``bim-core``.

Point d'import historique conservé
(``from audit_bim.domain.write_plan import WritePlan``).
"""

from __future__ import annotations

from bim_core.write_plan import ActionResult, WritePlan, WritePlanKind

__all__ = ["WritePlanKind", "WritePlan", "ActionResult"]
