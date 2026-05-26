"""Journal append-only des écritures via API BIMData.

Toute opération ``apply_*`` (création BCF, Smart Views, classifications,
enrichissement DOE) **doit** se terminer par un :func:`WriteJournal.record`
qui décrit ce qui s'est passé :

- horodatage UTC ISO 8601,
- type d'action et plan source (``plan_id`` du :class:`WritePlan`),
- cible BIMData (cloud / project / model + nom du modèle),
- compteurs (succeeded / failed / skipped) et UUIDs impactés,
- erreurs (déjà scrubées des tokens, par convention de l'appelant).

Conception
----------

- **Append-only JSONL** : 1 ligne JSON par entrée, jamais réécrit.
- **Sandbox** : écrit sous ``AUDIT_OUTPUT_DIR/write_log/journal.jsonl``,
  passe par :func:`audit_bim.safe_paths.safe_export_path` pour la
  création initiale puis fait des append directs (pas de re-validation
  par ligne — la racine est déjà figée à l'init).
- **Pas de tokens** : la signature de :meth:`record` n'accepte pas de
  bearer ; tout ce qui transite par ``errors`` doit déjà être scrubé.
- **Singleton paresseux** : :func:`get_journal` instancie au premier
  appel. Pas par session — le journal est un audit trail global du
  serveur (utile pour les déploiements HTTP multi-clients).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..safe_paths import get_export_root

logger = logging.getLogger("audit_bim.security.write_journal")

JOURNAL_SUBDIR = "write_log"
JOURNAL_FILENAME = "journal.jsonl"


class WriteJournalEntry(BaseModel):
    """Une entrée du journal d'écritures.

    Volontairement plate (un seul niveau de dict) pour rester lisible en
    ``grep`` / ``jq``. Le champ ``target`` est imbriqué car il identifie
    la cible BIMData de bout en bout (cloud + project + model).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    action: str = Field(
        ...,
        description="Nom de l'action : 'apply_bcf_topics' | 'apply_smart_views' "
        "| 'apply_classification_update' | 'apply_doe_enrichment'.",
    )
    plan_id: str | None = Field(
        None,
        description="UUID du WritePlan source. None pour les actions legacy "
        "qui n'utilisent pas encore le pattern prepare/apply.",
    )
    plan_kind: str | None = None
    target: dict[str, Any] = Field(
        default_factory=dict,
        description="cloud_id / project_id / model_id / model_name.",
    )
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    impacted_uuids_count: int = 0
    # ⚠ on stocke seulement le compte par défaut — les UUIDs détaillés
    # peuvent être très nombreux. Le caller peut passer ``impacted_uuids``
    # via ``extra`` s'il veut les inclure (utilise alors ``echo_uuids=True``).
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Champs additionnels (ex: échantillon errors, mode dry_run, etc). "
        "Le caller est responsable du scrubbing des tokens.",
    )


class WriteJournal:
    """Journal JSONL append-only des opérations ``apply_*``.

    Thread-safe (lock interne pour la concurrence HTTP).
    """

    def __init__(self, journal_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._explicit_path = journal_path

    # ── Résolution du chemin ─────────────────────────────────────────────

    def _resolve_path(self) -> Path:
        """Résout le chemin du journal (sandbox)."""
        if self._explicit_path is not None:
            return self._explicit_path
        root = get_export_root()
        directory = root / JOURNAL_SUBDIR
        directory.mkdir(parents=True, exist_ok=True)
        return directory / JOURNAL_FILENAME

    @property
    def path(self) -> Path:
        return self._resolve_path()

    # ── API publique ─────────────────────────────────────────────────────

    def record(
        self,
        *,
        action: str,
        plan_id: str | None = None,
        plan_kind: str | None = None,
        target: dict[str, Any] | None = None,
        succeeded: int = 0,
        failed: int = 0,
        skipped: int = 0,
        impacted_uuids: list[str] | None = None,
        extra: dict[str, Any] | None = None,
        echo_uuids: bool = False,
    ) -> WriteJournalEntry:
        """Ajoute une entrée au journal et la retourne.

        Args:
            action: Nom du tool MCP exécuté.
            plan_id: UUID du :class:`WritePlan` source si applicable.
            plan_kind: Type d'opération (cf. :class:`WritePlanKind`).
            target: ``{"cloud_id": ..., "project_id": ..., "model_id": ...,
                "model_name": ...}``. Le caller scrub les tokens.
            succeeded / failed / skipped: Compteurs.
            impacted_uuids: Liste des UUIDs effectivement modifiés (utilisé
                pour calculer ``impacted_uuids_count``).
            extra: Champs additionnels — **ne pas mettre de tokens**, le
                caller scrub avant.
            echo_uuids: Si True, inclut la liste complète d'UUIDs dans
                ``extra["impacted_uuids"]`` (par défaut on n'écrit que
                le compte).
        """
        entry_extra = dict(extra or {})
        if echo_uuids and impacted_uuids is not None:
            entry_extra["impacted_uuids"] = impacted_uuids

        entry = WriteJournalEntry(
            action=action,
            plan_id=plan_id,
            plan_kind=plan_kind,
            target=dict(target or {}),
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            impacted_uuids_count=len(impacted_uuids or []),
            extra=entry_extra,
        )

        line = entry.model_dump_json() + "\n"
        path = self._resolve_path()
        with self._lock:
            try:
                # 'a' mode : append-only, créé si absent
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError as exc:
                logger.error(
                    "write_journal: échec écriture %s (%s) — entrée perdue",
                    path,
                    exc,
                )
        return entry

    def tail(self, n: int = 20) -> list[WriteJournalEntry]:
        """Retourne les ``n`` dernières entrées (lecture seule).

        Utile pour les tools MCP de revue : ``audit_trail`` (à venir).
        """
        path = self._resolve_path()
        if not path.exists():
            return []
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        out: list[WriteJournalEntry] = []
        for raw in lines[-n:]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(WriteJournalEntry.model_validate_json(raw))
            except ValueError:
                # Ligne corrompue → on l'ignore plutôt que de planter
                # la lecture du journal entier.
                continue
        return out


# ── Singleton ────────────────────────────────────────────────────────────


_journal: WriteJournal | None = None
_journal_lock = threading.Lock()


def get_journal() -> WriteJournal:
    """Renvoie le journal global (paresseusement instancié).

    Le chemin est résolu à chaque ``record()`` via :func:`get_export_root`
    — donc compatible avec ``monkeypatch.setenv("AUDIT_OUTPUT_DIR", ...)``
    en tests.
    """
    global _journal
    if _journal is None:
        with _journal_lock:
            if _journal is None:
                _journal = WriteJournal()
    return _journal


def _reset_journal_for_tests() -> None:
    """Reset du singleton — utilisé par les fixtures pytest."""
    global _journal
    with _journal_lock:
        _journal = None


# Variable interne lisible par les tests (pas dans __all__).
__all_internal__ = (_reset_journal_for_tests, _journal)
del __all_internal__  # marque inutilisé pour ruff


# Utilitaire env exporté (test-friendly)
def journal_path_from_env() -> Path:
    """Chemin canonique du journal — utilitaire de test."""
    return Path(os.environ.get("AUDIT_OUTPUT_DIR", "./out")) / JOURNAL_SUBDIR / JOURNAL_FILENAME
