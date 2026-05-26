"""Garde-fou d'identité du modèle BIMData actif.

Avant de générer un audit, on veut s'assurer que la maquette
effectivement chargée côté serveur correspond bien à celle attendue par
l'auditeur. Un risque concret : ``_State.snapshot`` est servi depuis le
cache local (clé = ``modified_date``), mais ``set_active_model`` peut
avoir pointé vers un *autre* ``model_id`` entre-temps — on génèrerait
alors un rapport sur la mauvaise maquette sans s'en apercevoir.

Ce module expose deux helpers purs :

- :func:`normalize_model_name` — normalise une chaîne (casse, accents,
  espaces multiples) pour comparaison robuste.
- :func:`model_matches_expected` — vérifie que la valeur attendue
  apparaît bien (par inclusion normalisée) dans le nom de la maquette.

Politique de matching : *expected* est traité comme un fragment
attendu. Cela couvre le cas usuel où l'utilisateur tape
``"LIFFRE"`` et où le modèle s'appelle ``"Maquette BIM - LIFFRÉ -
DOE.ifc"``. Un *expected* vide ou ``None`` désactive la vérification
(retour ``True``).
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_model_name(value: str | None) -> str:
    """Normalise une chaîne pour comparaison insensible à casse/accents.

    - ``None`` ou non-``str`` → chaîne vide.
    - Supprime les diacritiques (NFKD).
    - Passe en minuscules.
    - Compacte les blancs successifs en un seul espace, trim.
    """
    if not isinstance(value, str) or not value:
        return ""
    # NFKD décompose les caractères accentués → on jette les combining marks
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WHITESPACE_RE.sub(" ", stripped).strip().lower()


def model_matches_expected(model_name: str | None, expected: str | None) -> bool:
    """Renvoie ``True`` si ``expected`` est contenu dans ``model_name``.

    Politique :

    - ``expected`` ``None`` ou vide (après normalisation) → la
      vérification est désactivée, on renvoie ``True``.
    - Sinon, comparaison par inclusion sur les versions normalisées.
    """
    expected_norm = normalize_model_name(expected)
    if not expected_norm:
        return True
    return expected_norm in normalize_model_name(model_name)
