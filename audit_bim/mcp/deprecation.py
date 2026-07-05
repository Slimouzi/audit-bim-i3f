"""Helpers de dépréciation pour les tools MCP.

Convention audit-bim-i3f
------------------------

On **ne lève pas** de ``DeprecationWarning`` Python côté MCP — les
warnings ne se propagent pas proprement à travers JSON-RPC et finissent
dans stderr serveur où aucun client ne les voit. À la place :

1. Le **retour JSON** du tool inclut explicitement :

   - ``deprecated: True``
   - ``use_instead: "<nom du tool de remplacement>"``
   - ``removal_version`` (optionnel) — version à laquelle le tool
     disparaîtra
   - ``migration_hint`` (optionnel) — phrase courte pour orienter
     l'utilisateur (« filtrer puis prepare/apply »)

2. Le **logger serveur** émet un INFO une fois par appel — visible dans
   les logs de prod / dev pour repérer les clients qui n'ont pas migré.

Cette politique permet :

- aux clients MCP scriptés (Claude, agents) de détecter la dépréciation
  via le champ ``deprecated`` et de basculer ;
- aux opérateurs serveur de mesurer l'usage des tools dépréciés via les
  logs avant de planifier la suppression.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("audit_bim.mcp.deprecation")

# Note interne (visible dans le retour) : pourquoi ce tool est conservé
# malgré sa dépréciation. Sert de "filet de sécurité" pédagogique pour
# l'utilisateur final.
_DEFAULT_DEPRECATION_NOTE = (
    "Tool conservé pour compatibilité. Préférer le pattern "
    "prepare_*/apply_* (cf. champ `use_instead` ci-dessous)."
)


@dataclass(frozen=True)
class DeprecatedToolInfo:
    """Métadonnées de dépréciation d'un tool MCP.

    Attributes:
        tool_name: Nom du tool MCP déprécié (ex: ``"create_bcf_topics"``).
        use_instead: Tool ou séquence à utiliser à la place. Texte
            humain — peut décrire plusieurs étapes
            (« prepare_bcf_topics(...) puis apply_bcf_topics(...) »).
        removal_version: Version à laquelle le tool sera supprimé
            (ex: ``"0.5.0"``). ``None`` = pas de date arrêtée.
        migration_hint: Indication courte pour orienter l'utilisateur,
            ex: « filtrer via list_classification_suggestions puis
            update_suggestion_status puis prepare_classification_update_plan ».
        legacy_status: Statut human-readable. Valeurs admises :
            - ``"deprecated"`` : à supprimer à terme, remplacement existe ;
            - ``"legacy_wrapper"`` : wrapper transitoire qui redirige
              vers le nouveau workflow par défaut.
    """

    tool_name: str
    use_instead: str
    removal_version: str | None = None
    migration_hint: str | None = None
    legacy_status: str = "deprecated"


def add_deprecation_marker(
    payload: dict | None,
    info: DeprecatedToolInfo,
) -> dict:
    """Ajoute les marqueurs de dépréciation à un retour de tool MCP.

    Args:
        payload: Retour existant du tool (sera enrichi sur place puis
            retourné). ``None`` → on crée un dict vide.
        info: Métadonnées de dépréciation.

    Returns:
        Le dict enrichi (mêmes clés que ``payload`` + clés dépréciation).
    """
    if payload is None:
        payload = {}
    elif not isinstance(payload, dict):
        # Préserve la valeur originale sous une clé `result`.
        payload = {"result": payload}

    payload["deprecated"] = True
    payload["use_instead"] = info.use_instead
    payload["legacy_status"] = info.legacy_status
    payload["deprecation_note"] = _DEFAULT_DEPRECATION_NOTE
    if info.removal_version is not None:
        payload["removal_version"] = info.removal_version
    if info.migration_hint is not None:
        payload["migration_hint"] = info.migration_hint
    return payload


def log_deprecated_tool_call(
    info: DeprecatedToolInfo,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    """Log INFO standardisé d'appel à un tool déprécié.

    Args:
        info: Métadonnées du tool déprécié.
        extra: Données contextuelles supplémentaires (ex: ``legacy_execute=True``).
            Toujours scrubbed avant log via redaction (defense-in-depth) —
            la doc des tools recommande déjà de ne pas mettre de secret
            dans ``extra``.
    """
    msg = "deprecated tool called: %s — prefer %s"
    args: list[Any] = [info.tool_name, info.use_instead]
    if extra:
        msg += " (ctx: %s)"
        # Redaction defense-in-depth : un appelant qui passerait par
        # erreur un token doit être protégé.
        from ..security.redaction import redact_secrets

        args.append(redact_secrets(extra))
    logger.info(msg, *args)


# ── Registre central des dépréciations ───────────────────────────────────

# Liste exhaustive des tools dépréciés. Mise à jour à chaque évolution
# du pattern prepare/apply. Source unique pour les tests de
# non-régression sur ``list_tools``.

DEPRECATIONS: dict[str, DeprecatedToolInfo] = {
    # Vidé en v0.5.0 : les 5 tools hérités (create_bcf_topics, create_smart_views,
    # apply_suggested_classifications, suggest_classifications, doe_enrich_model)
    # ont été supprimés. L'infrastructure de dépréciation reste disponible pour
    # d'éventuelles dépréciations futures.
}


def get_deprecation(tool_name: str) -> DeprecatedToolInfo | None:
    """Récupère les métadonnées de dépréciation pour un tool (ou None)."""
    return DEPRECATIONS.get(tool_name)


__all__ = [
    "DeprecatedToolInfo",
    "add_deprecation_marker",
    "log_deprecated_tool_call",
    "DEPRECATIONS",
    "get_deprecation",
]
