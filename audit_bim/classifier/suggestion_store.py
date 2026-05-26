"""Stockage indexé des suggestions de classification.

Permet de **réutiliser** les propositions du suggester comme source de
vérité unique pour :

- les rapports Word / XLSX (synthèse classifications proposées) ;
- les BCF Topics et Smart Views groupés par code proposé ;
- les plans de correction API (:class:`audit_bim.domain.write_plan.WritePlan`) ;
- les workflows AMO : accepter / rejeter manuellement avant push.

Conception
----------

- **En mémoire** dans :class:`audit_bim.mcp.session._Session` (un store
  par session).
- **JSON roundtrip** explicite via :meth:`ClassificationSuggestionStore.to_json`
  / :meth:`from_json` — l'utilisateur déclenche l'export ; pas d'I/O
  automatique pour ne pas alourdir le canal MCP.
- **Indexé par ``element_uuid``** pour mise à jour `O(1)` (statut,
  ré-évaluation après nouvelle exécution du suggester).
- **Statuts** : ``proposed`` → ``accepted`` → ``applied``, ou
  ``proposed`` → ``rejected``. Le moteur d'``apply_classification_update``
  (tranche 2) ne traitera que les ``accepted``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.filters import ConfidenceBand, SuggestionStatus

__all__ = [
    "ClassificationSuggestionEntry",
    "ClassificationSuggestionStore",
]


class ClassificationSuggestionEntry(BaseModel):
    """Une entrée du store, indexée par ``element_uuid``.

    Champs alignés sur la spec brief CTO :
    ``element_uuid``, ``ifc_type``, ``current_classification``,
    ``proposed_classification``, ``proposed_level_3``, ``confidence``,
    ``confidence_band``, ``reason_codes``, ``evidence``, ``status``,
    ``source``.

    ``evidence`` contient les signaux bruts (layers, materials,
    is_external, etc.) qui ont contribué au score — utile pour la revue
    AMO et pour expliquer une suggestion dans un BCF Topic.
    """

    model_config = ConfigDict(extra="ignore")

    element_uuid: str
    ifc_type: str | None = None

    current_classification: str | None = Field(
        None,
        description="Code de classification actuel (None si manquante).",
    )
    current_classification_system: str | None = None

    proposed_classification: str
    proposed_label: str | None = None
    proposed_system: str = "uniformat"
    proposed_level_3: str = Field(
        ...,
        description="Niveau 3 du code proposé (5 premiers caractères pour UniFormat).",
    )

    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_band: ConfidenceBand

    reason_codes: list[str] = Field(
        default_factory=list,
        description="Codes courts machine-friendly : 'ifc_class', 'layer_match', "
        "'pset_is_external', 'keyword', 'quantity'.",
    )
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Signaux bruts (layers, materials, is_external, keywords détectés).",
    )

    status: SuggestionStatus = SuggestionStatus.PROPOSED
    source: str = Field(
        "audit",
        description="audit | xlsx_review | manual | doe",
    )

    # Suggestions secondaires (top 2..N) — non priorisées par défaut, mais
    # conservées pour basculer si une suggestion est rejetée.
    alternatives: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def is_mismatch(self) -> bool:
        """True si l'élément a une classification actuelle différente du
        niveau 3 proposé."""
        if not self.current_classification:
            return False
        cur = (self.current_classification or "").strip().upper()
        cur_l3 = cur[:5] if len(cur) >= 5 and cur[0].isalpha() else cur
        return cur_l3 != self.proposed_level_3.upper()

    @property
    def is_missing_current(self) -> bool:
        """True si l'élément n'a pas de classification actuelle."""
        return self.current_classification is None or self.current_classification.strip() == ""


class ClassificationSuggestionStore:
    """Container indexé de :class:`ClassificationSuggestionEntry`.

    Pas un Pydantic — interface impérative volontairement (ajout, mise à
    jour, itération filtrée). La sérialisation passe par
    :meth:`to_json` / :meth:`from_json`.
    """

    def __init__(self) -> None:
        self._by_uuid: dict[str, ClassificationSuggestionEntry] = {}

    # ── Insertion / lookup ───────────────────────────────────────────────

    def add(self, entry: ClassificationSuggestionEntry, *, replace: bool = False) -> bool:
        """Ajoute ou met à jour une entrée.

        Args:
            entry: L'entrée à insérer.
            replace: Si True, écrase une entrée existante pour le même
                ``element_uuid``. Si False (défaut), conserve l'ancienne
                si présente (utile pour ne pas perdre un statut
                ``accepted`` lors d'un re-run du suggester).

        Returns:
            True si l'entrée a été insérée ou remplacée, False si l'on
            a conservé l'existante.
        """
        if entry.element_uuid in self._by_uuid and not replace:
            return False
        self._by_uuid[entry.element_uuid] = entry
        return True

    def get(self, element_uuid: str) -> ClassificationSuggestionEntry | None:
        return self._by_uuid.get(element_uuid)

    def update_status(
        self, element_uuid: str, status: SuggestionStatus
    ) -> ClassificationSuggestionEntry | None:
        """Change le statut d'une entrée. Pydantic v2 frozen=False → on
        ré-instancie via ``model_copy``."""
        existing = self._by_uuid.get(element_uuid)
        if existing is None:
            return None
        updated = existing.model_copy(update={"status": status})
        self._by_uuid[element_uuid] = updated
        return updated

    def remove(self, element_uuid: str) -> bool:
        return self._by_uuid.pop(element_uuid, None) is not None

    def clear(self) -> None:
        self._by_uuid.clear()

    # ── Itération / agrégats ─────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._by_uuid)

    def __iter__(self) -> Iterator[ClassificationSuggestionEntry]:
        return iter(self._by_uuid.values())

    def __contains__(self, element_uuid: object) -> bool:
        return isinstance(element_uuid, str) and element_uuid in self._by_uuid

    def all(self) -> list[ClassificationSuggestionEntry]:
        """Liste matérialisée (copie superficielle des références)."""
        return list(self._by_uuid.values())

    def counts_by_status(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self._by_uuid.values():
            out[e.status.value] = out.get(e.status.value, 0) + 1
        return out

    def counts_by_band(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self._by_uuid.values():
            out[e.confidence_band.value] = out.get(e.confidence_band.value, 0) + 1
        return out

    def counts_by_proposed_level_3(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self._by_uuid.values():
            out[e.proposed_level_3] = out.get(e.proposed_level_3, 0) + 1
        return out

    # ── Sérialisation ────────────────────────────────────────────────────

    def to_json(self, path: str | Path | None = None) -> str:
        """Sérialise le store en JSON.

        Args:
            path: Si fourni, **doit** être pré-validé par
                :func:`audit_bim.safe_paths.safe_export_path` côté
                appelant. Le store ne fait pas de validation de chemin
                lui-même pour ne pas dupliquer la sandbox.

        Returns:
            La chaîne JSON (toujours produite, même si écrite sur disque).
        """
        payload = {
            "version": 1,
            "entries": [e.model_dump(mode="json") for e in self._by_uuid.values()],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    @classmethod
    def from_json(cls, source: str | Path) -> ClassificationSuggestionStore:
        """Recharge un store depuis un JSON (chemin ou contenu)."""
        if isinstance(source, Path) or (
            isinstance(source, str) and not source.lstrip().startswith("{")
        ):
            text = Path(source).read_text(encoding="utf-8")
        else:
            text = source
        payload = json.loads(text)
        store = cls()
        for raw in payload.get("entries", []):
            store.add(ClassificationSuggestionEntry.model_validate(raw), replace=True)
        return store
