"""Ré-export : résolution des assets de la charte BIMData (``bim_reporting.brand``).

L'implémentation vit dans le socle générique ``bim-reporting`` ; ce module la
ré-expose derrière les noms historiques (``from audit_bim.reporting.bimdata_brand
import WORDMARK, find_logo``) — aucun call-site à réécrire.

**Pourquoi ce ne sont pas des ré-exports directs.** La recherche « sibling » du
brand kit et du logo « vrac » remonte l'arborescence depuis un fichier de
référence. Tant que le code vivait ici, ce fichier était nécessairement dans le
dépôt ; installé en dépendance, ``bim_reporting.brand.__file__`` pointe dans
``site-packages`` et la remontée ne trouve plus rien. Le logo disparaîtrait des
livrables **sans la moindre erreur**, puisque son absence dégrade proprement
vers le wordmark texte.

Ces deux fonctions figent donc ``search_from`` sur **ce fichier-ci**, ce qui
reproduit exactement la résolution d'avant l'extraction.
"""

from __future__ import annotations

from pathlib import Path

from bim_reporting.brand import WORDMARK  # noqa: F401 — ré-export direct
from bim_reporting.brand import find_brand_kit_dir as _find_brand_kit_dir
from bim_reporting.brand import find_logo as _find_logo

__all__ = ["WORDMARK", "find_brand_kit_dir", "find_logo"]

#: Origine de la recherche « sibling » — l'emplacement historique du module.
_SEARCH_FROM = Path(__file__)


def find_brand_kit_dir() -> Path | None:
    """Renvoie le dossier racine du brand kit BIMData ou ``None``.

    Ordre : ``BIMDATA_BRAND_KIT_DIR`` / ``KORHUS_BRAND_KIT_DIR``, puis dossier
    sibling ``bimdata_brand_kit/`` / ``korhus_brand_kit/`` remonté **depuis ce
    dépôt**. Aucun side effect ; ne lève pas.
    """
    return _find_brand_kit_dir(search_from=_SEARCH_FROM)


def find_logo(variant: str = "light") -> Path | None:
    """Renvoie le chemin d'un fichier de logo BIMData, ou ``None``.

    Args:
        variant: clé parmi ``primary | dark | light | mark_primary |
            mark_dark | mark_light``. Défaut ``"light"`` (inversé, adapté à la
            couverture sombre du rapport).
    """
    return _find_logo(variant, search_from=_SEARCH_FROM)
