"""Normalisation de libellés — comparaison **insensible aux accents et à la casse**.

Les listes fermées du CCH (noms d'étages, de pièces…) et les libellés portés par
les maquettes divergent souvent sur les seuls diacritiques (``1ER ÉTAGE`` vs
``1ER ETAGE``, ``DÉGAGEMENT`` vs ``DEGAGEMENT``). Comparer via :func:`fold_upper`
des **deux côtés** évite un faux ``NAMING_NOT_IN_LIST`` (ou un contrôle
silencieusement désactivé). Même idiome NFKD que ``reporting/avp_snapshot`` et
``mcp/model_identity``, centralisé ici (couche ``domain``, la plus basse).
"""

from __future__ import annotations

import unicodedata


def fold_accents(s: str | None) -> str:
    """Décompose (NFKD) et retire les diacritiques ; ``None`` → ``""``."""
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def fold_upper(s: str | None) -> str:
    """Forme canonique de comparaison : sans accents, majuscules, espaces
    internes normalisés. ``"  1er  Étage "`` → ``"1ER ETAGE"``."""
    return " ".join(fold_accents(s).upper().split())
