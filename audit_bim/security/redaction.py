"""Redaction centralisée des secrets pour les messages d'erreur et logs.

Les exceptions HTTP / API peuvent contenir, dans leur ``str()``, des
URLs signées, des en-têtes ``Authorization``, des paramètres
``access_token=...`` ou des clés API. Si on log brut un message
d'exception dans le journal d'audit ou dans un ``ActionResult.errors``
retourné côté MCP, on fuit ces secrets.

Ce module fournit :class:`redact_secrets` (regex multi-pattern) qui
remplace les secrets reconnus par ``<scrub:sha8>`` — la même primitive
que :func:`audit_bim.mcp.security.scrub` côté tokens MCP.

Patterns couverts
-----------------

- ``Bearer <token>`` (avec/sans espace)
- ``access_token=<value>``, ``access_token: <value>``
- ``Authorization: <value>``, ``authorization=<value>``
- ``api_key=<value>``, ``API_KEY: <value>``
- ``BIMDATA_API_KEY=<value>``
- ``client_secret=<value>``
- URLs avec query params : ``?access_token=...`` → param scrubé

Limites connues
---------------

- On ne fait pas d'analyse syntaxique URL complète — uniquement des
  regex. Les patterns inhabituels (clés en JSON, en YAML, en log
  Python brut) peuvent passer. La règle de défense en profondeur : ne
  jamais inclure de payload brut, toujours passer par
  :func:`redact_secrets` avant journalisation.
- Les secrets très courts (< 8 chars) ne sont pas scrubés (probable
  faux positif : ``id=1``).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# Longueur minimale d'un secret pour déclencher la redaction.
# En dessous, c'est très probablement un identifiant non-sensible
# (``id=42``, ``page=3``).
_MIN_SECRET_LENGTH = 8


def _scrub_value(value: str) -> str:
    """Produit ``<scrub:sha8>`` à partir d'une valeur (mêmes 8 chars
    que :func:`audit_bim.mcp.security.scrub`)."""
    if not value:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"<scrub:{digest[:8]}>"


# ── Patterns ─────────────────────────────────────────────────────────────


def _make_kv_pattern(key: str) -> re.Pattern[str]:
    """Capture ``key=value`` ou ``key: value`` (case-insensitive).

    Valeur = suite de caractères non-séparateurs (\\S sans guillemets).
    """
    return re.compile(
        rf"""(?ix)
        \b ({re.escape(key)}) \s* [:=] \s*       # key + séparateur
        ["']?                                    # guillemet optionnel
        ([^\s"',;&\)]+ )                         # value (>= 1 char, sans séparateurs)
        ["']?                                    # guillemet optionnel
        """,
    )


_BEARER_PATTERN = re.compile(
    r"""(?ix)
    \b (Bearer | Token) \s+      # mot-clé d'auth HTTP
    ([A-Za-z0-9._\-]+)           # token (lettres, chiffres, ._-)
    """,
)

_KV_PATTERNS: tuple[re.Pattern[str], ...] = (
    _make_kv_pattern("access_token"),
    _make_kv_pattern("refresh_token"),
    _make_kv_pattern("id_token"),
    _make_kv_pattern("authorization"),
    _make_kv_pattern("api_key"),
    _make_kv_pattern("apikey"),
    _make_kv_pattern("client_secret"),
    _make_kv_pattern("BIMDATA_API_KEY"),
    _make_kv_pattern("BIMDATA_CLIENT_SECRET"),
    _make_kv_pattern("password"),
    _make_kv_pattern("passwd"),
)


def _redact_str(text: str) -> str:
    """Applique tous les patterns sur une chaîne et retourne la version
    scrubée."""
    if not text:
        return text

    def _bearer_sub(m: re.Match[str]) -> str:
        keyword, value = m.group(1), m.group(2)
        if len(value) < _MIN_SECRET_LENGTH:
            return m.group(0)
        return f"{keyword} {_scrub_value(value)}"

    text = _BEARER_PATTERN.sub(_bearer_sub, text)

    for pattern in _KV_PATTERNS:

        def _kv_sub(m: re.Match[str]) -> str:
            key, value = m.group(1), m.group(2)
            if len(value) < _MIN_SECRET_LENGTH:
                return m.group(0)
            # Détecte si on était sur ``key: value`` ou ``key=value`` pour
            # respecter le séparateur d'origine.
            sep = "=" if "=" in m.group(0) else ":"
            return f"{key}{sep}{_scrub_value(value)}"

        text = pattern.sub(_kv_sub, text)

    return text


# ── API publique ─────────────────────────────────────────────────────────


def redact_secrets(value: Any) -> Any:
    """Scrub récursivement les secrets dans ``value``.

    Args:
        value: Chaîne, dict, liste, tuple ou n'importe quel objet. Les
            structures imbriquées sont traversées en profondeur ; les
            types non-collection autres que ``str`` sont retournés
            inchangés (``int``, ``float``, ``bool``, ``None``).

    Returns:
        Même structure avec les chaînes scrubées.

    Examples:
        >>> redact_secrets("Authorization: Bearer abcd12345678")
        'Authorization: Bearer <scrub:...>'
        >>> redact_secrets({"err": "401 ?access_token=xxxx12345678"})
        {'err': '401 ?access_token=<scrub:...>'}
    """
    if isinstance(value, str):
        return _redact_str(value)
    if isinstance(value, dict):
        return {k: redact_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(v) for v in value)
    return value
