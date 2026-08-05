"""Isolation de l'état MCP par session client.

Le serveur audit-bim-i3f conserve un état (catalogue d'exigences, client
BIMData authentifié, snapshot modèle, résultat d'audit). En transport
``stdio`` (mono-client), un état global suffit. En transport HTTP / SSE
multi-clients, deux auditeurs distincts ne doivent pas se voir.

**La mécanique vient de ``bim-mcp-runtime``** : magasin borné (TTL, plafond,
éviction LRU), session courante et proxy d'attributs. Ce module ne garde que ce
qui est propre à ce serveur — les CHAMPS de la session, qui portent catalogue
d'exigences, client BIMData, snapshot et résultat d'audit.

C'est la frontière du moteur : il sait faire vivre des sessions sans savoir ce
qu'elles contiennent.

Architecture :

- :class:`_Session` — porte l'état d'une session. **Reste ici** : ses champs
  sont métier.
- ``_store`` — ``SessionStore[_Session]`` du moteur, construit avec
  :class:`_Session` comme fabrique.
- :data:`current_session` — ``ContextVar`` du moteur, pointant la session active.
  Bindée par :class:`audit_bim.mcp.middleware.SessionBindingMiddleware`.
- :data:`_State` — proxy d'attributs du moteur, drop-in de l'ancien
  ``class _State``. Les tools n'ont rien à modifier.

Pour stdio, ``current_session`` reste sur la session par défaut tout au
long du process — comportement strictement identique à l'ancien
``_State`` global.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from bim_mcp_runtime import DEFAULT_MAX_SESSIONS as _RUNTIME_DEFAULT_MAX_SESSIONS
from bim_mcp_runtime import DEFAULT_SESSION_TTL_S as _RUNTIME_DEFAULT_TTL_S
from bim_mcp_runtime import RuntimeConfig, SessionBinding, SessionStore

if TYPE_CHECKING:
    from ..audit.engine import AuditResult
    from ..classifier.suggestion_store import ClassificationSuggestionStore
    from ..extraction.client import BIMDataClient
    from ..extraction.model_data import ModelSnapshot
    from ..requirements.models import BIMPhase, RequirementsCatalog

logger = logging.getLogger("audit_bim.mcp.session")

# Noms publics des variables lues par ce serveur — c'est SON préfixe, pas celui
# du moteur, qui les compose (cf. ``_runtime_config`` plus bas). Les valeurs par
# défaut viennent du moteur : une seule source, pas deux qui dérivent.
SESSION_TTL_ENV = "AUDIT_BIM_SESSION_TTL_S"
MAX_SESSIONS_ENV = "AUDIT_BIM_MAX_SESSIONS"
DEFAULT_SESSION_TTL_S = _RUNTIME_DEFAULT_TTL_S
DEFAULT_MAX_SESSIONS = _RUNTIME_DEFAULT_MAX_SESSIONS


# ── Session ──────────────────────────────────────────────────────────────


def _target_tool_name() -> str:
    """Nom de l'outil qui configure la cible, **dans le profil actif**.

    Le message citait ``set_active_model`` en dur. Depuis que les outils de
    lecture sont partagés (E7), ce texte est servi aussi aux profils qui ne
    l'exposent pas : le lecteur reçoit alors une instruction plausible et
    inapplicable. Import différé — la session est chargée très tôt.
    """
    from ..profiles.active import UnknownProfileError, resolve_active_profile

    try:
        return resolve_active_profile().target_tool_name
    except (UnknownProfileError, ImportError):  # pragma: no cover - repli défensif
        return "set_active_model"


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

        # Chemin du .ifc rapatrié par ``download_model_ifc`` : source la plus
        # fiable pour corréler un calcul géométrique au modèle actif.
        self.ifc_path: str | None = None
        self.snapshot: ModelSnapshot | None = None
        self.result: AuditResult | None = None
        self.suggestion_store: ClassificationSuggestionStore | None = None

        # E9 — verrou de **sérialisation intra-session** (créé paresseusement sur
        # la loop courante). Sans lui, deux appels concurrents du même client
        # (les tools sync tournent en threadpool) mutent l'état en parallèle : ex.
        # ``set_active_model`` (cible B) pendant un ``full_audit`` (findings A) →
        # plan « findings A / cible B » scellé et applicable. Le lock est **par
        # session** : la concurrence inter-clients est préservée.
        self._call_lock: asyncio.Lock | None = None

    def call_lock(self) -> asyncio.Lock:
        """Verrou async de sérialisation des ``tools/call`` de cette session (E9).

        Créé à la première utilisation, sur la loop de l'event-loop qui l'appelle
        (le middleware ``on_call_tool``). ``asyncio.Lock`` (et non ``threading``) :
        le middleware est asynchrone et tient le verrou *à travers* un ``await`` —
        un verrou bloquant figerait l'event-loop."""
        if self._call_lock is None:
            self._call_lock = asyncio.Lock()
        return self._call_lock

    def ensure_catalog(self) -> None:
        if self.catalog is None:
            raise RuntimeError(
                "Le catalogue d'exigences n'est pas chargé — appelez "
                "`parse_owner_requirements` (ou `full_audit`) au préalable."
            )

    def ensure_client(self) -> None:
        if self.client is None:
            raise RuntimeError(
                f"Aucune cible BIMData configurée — appelez `{_target_tool_name()}`."
            )

    def ensure_snapshot(self) -> None:
        if self.snapshot is None:
            raise RuntimeError("Aucun snapshot — appelez `extract_model_snapshot`.")

    def ensure_result(self) -> None:
        if self.result is None:
            raise RuntimeError("Aucun audit en cours — appelez `run_audit`.")


# ── Store, session courante et proxy : fournis par le moteur ─────────────

# Le préfixe d'environnement reste celui de ce serveur : les déploiements
# existants continuent de lire AUDIT_BIM_SESSION_TTL_S / AUDIT_BIM_MAX_SESSIONS.
# C'est exactement pourquoi le moteur prend le préfixe en paramètre plutôt que
# de le figer.
_runtime_config = RuntimeConfig(env_prefix="AUDIT_BIM")

_store: SessionStore[_Session] = SessionStore(_Session, config=_runtime_config)

_binding: SessionBinding[_Session] = SessionBinding(_Session, name="audit_bim_current_session")

#: ``ContextVar`` de la session active — bindée par le middleware.
current_session = _binding.var

#: Proxy d'attributs : route lectures et écritures vers la session courante.
_State = _binding.proxy
