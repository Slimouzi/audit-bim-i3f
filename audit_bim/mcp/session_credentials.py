"""Store de credentials BIMData par session web (façade ``/mcp-setup``).

Cette couche est **dédiée** et indépendante du ``_SessionStore`` générique
(``audit_bim.mcp.session``). Elle relie une session créée par la page web à
un **token opaque** remis au client, lui-même mappé — côté serveur — vers
une session MCP crédentialée (`_Session`) que les outils consomment.

Principes de sécurité :

- Les credentials BIMData (clé API, cloud/project/model) restent **en
  mémoire serveur** ; jamais sur disque, jamais renvoyés au client.
- Le token remis au client a la forme ``"<session_id>.<secret>"`` :
  ``session_id`` est un identifiant **public** de lookup, ``secret`` est la
  partie haute entropie (``secrets.token_urlsafe(32)``).
- Le store ne conserve que le **hash SHA-256 du secret** — jamais le secret
  brut, jamais le token en clair. La vérification se fait en **temps
  constant** (``hmac.compare_digest``).
- TTL **1h** (configurable via ``AUDIT_BIM_SETUP_SESSION_TTL_S``) +
  révocation explicite (``DELETE``).
- Aucune valeur sensible (clé, secret, token) ne doit transiter dans les
  logs : utiliser :func:`audit_bim.mcp.security.scrub` pour corréler.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass, field

from ..requirements.models import BIMPhase

# TTL par défaut : 1 heure. Surchargé par l'env pour les tests / l'ops.
_DEFAULT_TTL_S = 3600


def _ttl_seconds() -> int:
    raw = os.getenv("AUDIT_BIM_SETUP_SESSION_TTL_S")
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return _DEFAULT_TTL_S


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CredentialError(Exception):
    """Token absent, invalide, expiré, ou credentials refusés."""


@dataclass
class _Record:
    """Entrée interne du store (jamais exposée telle quelle au client)."""

    session_id: str
    secret_hash: str  # SHA-256 du secret — JAMAIS le secret brut
    api_key: str
    cloud_id: str
    project_id: str
    model_id: str
    phase: BIMPhase
    auditor_name: str | None
    project_address: str | None
    created_at: float
    expires_at: float
    # Session MCP crédentialée, construite à la 1re liaison et réutilisée
    # pour préserver snapshot/catalog/result entre appels d'outils.
    mcp_session: object | None = field(default=None)

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at


@dataclass(frozen=True)
class SessionInfo:
    """Vue **non sensible** d'une session (pour status / réponses API)."""

    session_id: str
    cloud_id: str
    project_id: str
    model_id: str
    phase: str
    auditor_name: str | None
    project_address: str | None
    expires_in_s: int


class SetupSessionStore:
    """Registre thread-safe token → credentials, avec TTL et révocation."""

    def __init__(self, ttl_s: int | None = None) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, _Record] = {}
        self._ttl_s = ttl_s if ttl_s is not None else _ttl_seconds()

    # ── Cycle de vie ────────────────────────────────────────────────────

    def create(
        self,
        *,
        api_key: str,
        cloud_id: str | int,
        project_id: str | int,
        model_id: str | int,
        phase: str,
        auditor_name: str | None = None,
        project_address: str | None = None,
    ) -> tuple[str, str]:
        """Crée une session crédentialée et renvoie ``(session_id, token)``.

        ``token`` (``"<session_id>.<secret>"``) est l'**unique** moment où
        le secret existe en clair : il est remis au client puis oublié. Le
        store n'en garde que le hash.

        Raises:
            CredentialError: si ``phase`` n'est pas une ``BIMPhase`` valide
                ou si un champ requis est vide.
        """
        if not api_key or not str(api_key).strip():
            raise CredentialError("Clé API BIMData requise.")
        for label, val in (
            ("cloud_id", cloud_id),
            ("project_id", project_id),
            ("model_id", model_id),
        ):
            if val is None or str(val).strip() == "":
                raise CredentialError(f"{label} requis.")
        try:
            phase_enum = BIMPhase(str(phase).upper())
        except ValueError as exc:
            valid = ", ".join(p.value for p in BIMPhase)
            raise CredentialError(f"Phase invalide : {phase!r}. Valeurs : {valid}.") from exc

        session_id = secrets.token_urlsafe(16)
        secret = secrets.token_urlsafe(32)
        now = time.time()
        rec = _Record(
            session_id=session_id,
            secret_hash=_sha256(secret),
            api_key=str(api_key),
            cloud_id=str(cloud_id),
            project_id=str(project_id),
            model_id=str(model_id),
            phase=phase_enum,
            auditor_name=(auditor_name or None),
            project_address=(project_address or None),
            created_at=now,
            expires_at=now + self._ttl_s,
        )
        with self._lock:
            self._by_id[session_id] = rec
        return session_id, f"{session_id}.{secret}"

    def get_session(self, session_id: str, secret: str) -> _Record:
        """Résout ``(session_id, secret)`` → record valide (sinon lève).

        ``secret`` est la partie haute entropie du token client (après le
        point). La vérification est en **temps constant**.

        Raises:
            CredentialError: token inconnu, secret invalide, ou expiré.
        """
        now = time.time()
        with self._lock:
            rec = self._by_id.get(session_id)
            if rec is None:
                raise CredentialError("Session inconnue ou révoquée.")
            if rec.is_expired(now):
                self._by_id.pop(session_id, None)
                raise CredentialError("Session expirée.")
            if not hmac.compare_digest(rec.secret_hash, _sha256(secret or "")):
                raise CredentialError("Token invalide.")
            return rec

    def resolve_token(self, raw_token: str | None) -> _Record:
        """Parse ``"<session_id>.<secret>"`` et délègue à :meth:`get_session`.

        Point d'entrée du middleware MCP (en-tête ``X-MCP-Session-Token``).
        """
        session_id, secret = split_token(raw_token)
        if not session_id or not secret:
            raise CredentialError("Token absent ou mal formé.")
        return self.get_session(session_id, secret)

    def revoke(self, session_id: str, secret: str) -> bool:
        """Révoque une session si le secret correspond. Idempotent."""
        with self._lock:
            rec = self._by_id.get(session_id)
            if rec is None:
                return False
            if not hmac.compare_digest(rec.secret_hash, _sha256(secret or "")):
                raise CredentialError("Token invalide.")
            self._by_id.pop(session_id, None)
            return True

    def ensure_mcp_session(self, rec: _Record, factory) -> object:
        """Construit (1×) et met en cache la session MCP crédentialée.

        ``factory`` est un callable sans argument qui fabrique le
        ``_Session`` (client + cloud/project/model/phase). Réutilisé entre
        appels d'outils pour préserver snapshot / catalogue / résultat.
        Construction sous lock pour éviter une double création concurrente.
        """
        with self._lock:
            if rec.mcp_session is None:
                rec.mcp_session = factory()
            return rec.mcp_session

    def purge_expired(self) -> int:
        now = time.time()
        with self._lock:
            expired = [sid for sid, rec in self._by_id.items() if rec.is_expired(now)]
            for sid in expired:
                self._by_id.pop(sid, None)
            return len(expired)

    # ── Vues non sensibles ──────────────────────────────────────────────

    def info(self, rec: _Record) -> SessionInfo:
        return SessionInfo(
            session_id=rec.session_id,
            cloud_id=rec.cloud_id,
            project_id=rec.project_id,
            model_id=rec.model_id,
            phase=rec.phase.value,
            auditor_name=rec.auditor_name,
            project_address=rec.project_address,
            expires_in_s=max(0, int(rec.expires_at - time.time())),
        )


def split_token(raw_token: str | None) -> tuple[str, str]:
    """Découpe ``"<session_id>.<secret>"`` → ``(session_id, secret)``.

    Tolérant : renvoie ``("", "")`` si le format est invalide (le caller
    transforme ça en refus). Un secret peut contenir des ``.`` (urlsafe
    n'en produit pas, mais on coupe sur le **premier** point).
    """
    if not raw_token or "." not in raw_token:
        return "", ""
    session_id, secret = raw_token.split(".", 1)
    return session_id, secret


# Singleton process-wide (partagé entre la façade web et le middleware MCP).
_store = SetupSessionStore()


def get_store() -> SetupSessionStore:
    return _store
