"""Isolation de l'état MCP par session client.

Le serveur audit-bim-i3f conserve un état (catalogue d'exigences, client
BIMData authentifié, snapshot modèle, résultat d'audit). En transport
``stdio`` (mono-client), un état global suffit. En transport HTTP / SSE
multi-clients, deux auditeurs distincts ne doivent pas se voir.

Architecture :

- :class:`_Session` — un dataclass-like qui porte l'état d'une session.
- :class:`_SessionStore` — registry borné (TTL + LRU) keyed par
  ``session_id`` MCP.
- :data:`current_session` — :class:`contextvars.ContextVar` qui pointe
  vers la session active du tool en cours d'exécution. Bindée par
  :class:`audit_bim.mcp.middleware.SessionBindingMiddleware` avant
  chaque appel de tool.
- :data:`_State` — proxy d'attributs (drop-in remplacement de l'ancien
  ``class _State``). Toute lecture/écriture est routée vers
  ``current_session.get()``. Les tools n'ont rien à modifier.

Pour stdio, ``current_session`` reste sur la session par défaut tout au
long du process — comportement strictement identique à l'ancien
``_State`` global.
"""

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from contextvars import ContextVar
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..audit.engine import AuditResult
    from ..classifier.suggestion_store import ClassificationSuggestionStore
    from ..extraction.client import BIMDataClient
    from ..extraction.model_data import ModelSnapshot
    from ..requirements.models import BIMPhase, RequirementsCatalog

logger = logging.getLogger("audit_bim.mcp.session")

SESSION_TTL_ENV = "AUDIT_BIM_SESSION_TTL_S"
MAX_SESSIONS_ENV = "AUDIT_BIM_MAX_SESSIONS"
DEFAULT_SESSION_TTL_S = 3600
DEFAULT_MAX_SESSIONS = 64


def _read_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


# ── Session ──────────────────────────────────────────────────────────────


class _Session:
    """État d'une session MCP isolée.

    Mêmes champs que l'ancien ``_State`` (compat ascendante des tools).
    Les chemins documentaires par défaut (CCH PDF, annexes) sont lus
    depuis l'environnement à la construction — chaque nouvelle session
    HTTP démarre donc avec les mêmes pointeurs que la session stdio.
    """

    def __init__(self) -> None:
        # Import paresseux pour éviter le cycle config ↔ session.
        from .. import config

        self.cch_pdf: Path | None = Path(config.I3F_CCH_PDF) if config.I3F_CCH_PDF else None
        self.data_spec_xlsx: Path | None = (
            Path(config.I3F_DATA_SPEC_XLSX) if config.I3F_DATA_SPEC_XLSX else None
        )
        self.naming_spec_xlsx: Path | None = (
            Path(config.I3F_NAMING_SPEC_XLSX) if config.I3F_NAMING_SPEC_XLSX else None
        )
        self.catalog: RequirementsCatalog | None = None

        self.client: BIMDataClient | None = None
        self.cloud_id: str | None = None
        self.project_id: str | None = None
        self.model_id: str | None = None
        self.phase: BIMPhase | None = None
        self.classification_system: str = "UniFormat II"
        self.doe_available: bool | None = None

        self.snapshot: ModelSnapshot | None = None
        self.result: AuditResult | None = None
        self.suggestion_store: ClassificationSuggestionStore | None = None

    def ensure_catalog(self) -> None:
        if self.catalog is None:
            raise RuntimeError(
                "Le catalogue d'exigences n'est pas chargé — appelez "
                "`parse_owner_requirements` (ou `full_audit`) au préalable."
            )

    def ensure_client(self) -> None:
        if self.client is None:
            raise RuntimeError("Aucune cible BIMData configurée — appelez `set_active_model`.")

    def ensure_snapshot(self) -> None:
        if self.snapshot is None:
            raise RuntimeError("Aucun snapshot — appelez `extract_model_snapshot`.")

    def ensure_result(self) -> None:
        if self.result is None:
            raise RuntimeError("Aucun audit en cours — appelez `run_audit`.")


# ── Store : TTL + LRU + thread-safe ──────────────────────────────────────


class _SessionStore:
    """Registry borné de sessions MCP, keyed par ``session_id`` client.

    - TTL (``AUDIT_BIM_SESSION_TTL_S``, défaut 3600 s) : sessions
      inactives purgées à la prochaine lecture.
    - Cap (``AUDIT_BIM_MAX_SESSIONS``, défaut 64) avec éviction LRU.

    Thread-safe.
    """

    def __init__(self, *, ttl_s: int | None = None, max_sessions: int | None = None) -> None:
        self._ttl_s = (
            ttl_s if ttl_s is not None else _read_int_env(SESSION_TTL_ENV, DEFAULT_SESSION_TTL_S)
        )
        self._max = (
            max_sessions
            if max_sessions is not None
            else _read_int_env(MAX_SESSIONS_ENV, DEFAULT_MAX_SESSIONS)
        )
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._touched: dict[str, float] = {}
        self._lock = Lock()

    def _evict_expired(self, now: float) -> None:
        expired = [k for k, t in self._touched.items() if now - t > self._ttl_s]
        for k in expired:
            self._sessions.pop(k, None)
            self._touched.pop(k, None)
            logger.info("session evicted (ttl) key=%s", k)

    def _evict_lru(self) -> None:
        while len(self._sessions) >= self._max:
            k, _ = self._sessions.popitem(last=False)
            self._touched.pop(k, None)
            logger.info("session evicted (lru) key=%s", k)

    def get(self, key: str) -> _Session:
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            if key in self._sessions:
                self._sessions.move_to_end(key)
                self._touched[key] = now
                return self._sessions[key]
            self._evict_lru()
            sess = _Session()
            self._sessions[key] = sess
            self._touched[key] = now
            return sess

    def clear(self, key: str) -> bool:
        with self._lock:
            existed = self._sessions.pop(key, None) is not None
            self._touched.pop(key, None)
            return existed

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._sessions)


_store = _SessionStore()


# ── ContextVar + proxy de compatibilité ──────────────────────────────────


# Session par défaut : utilisée en stdio (mono-client) et comme fallback
# hors middleware (tests unitaires, scripts internes).
_default_session = _Session()

current_session: ContextVar[_Session] = ContextVar(
    "audit_bim_current_session",
    default=_default_session,
)


class _StateProxy:
    """Proxy d'attributs : route toutes les lectures/écritures vers la
    session courante (cf. :data:`current_session`).

    Permet aux tools écrits avec ``_State.foo`` de fonctionner sans
    modification, en obtenant automatiquement la session du client MCP
    actif (bindée par le middleware).
    """

    def __getattr__(self, name: str):
        return getattr(current_session.get(), name)

    def __setattr__(self, name: str, value) -> None:
        setattr(current_session.get(), name, value)


_State = _StateProxy()
