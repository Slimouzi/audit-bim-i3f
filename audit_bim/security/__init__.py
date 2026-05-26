"""Composants de gouvernance et journalisation des écritures.

Note : la gate des écritures par transport (``ensure_writes_allowed``)
et la garde sur ``access_token`` réseau vivent toujours dans
``audit_bim.mcp.security`` — historique du module.

Ce package contient les composants de *suivi* / *audit trail* qui ne
sont pas couplés au transport MCP :

- :mod:`write_journal` — append-only des opérations ``apply_*``.
"""

from __future__ import annotations

from .write_journal import WriteJournal, WriteJournalEntry, get_journal

__all__ = ["WriteJournal", "WriteJournalEntry", "get_journal"]
